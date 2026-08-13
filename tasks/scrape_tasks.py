# =========================================
# CELERY SCRAPE TASKS — BUBBL.OOO
# =========================================
# Replaces threading.Thread in scrape_managment.py
# Runs in isolated Celery worker (gevent pool)
# Auto-retries on failure, logs progress to DB

import os
import uuid
import time
from datetime import datetime, timezone, timedelta
from celery.utils.log import get_task_logger
from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery

logger = get_task_logger(__name__)


# soft_time_limit: raise SoftTimeLimitExceeded so we can mark the job failed cleanly.
# time_limit: hard kill a few seconds later if soft handling doesn't return.
@celery.task(bind=True, max_retries=3, default_retry_delay=60,
             soft_time_limit=1500, time_limit=1560)
def async_scrape_task(self, job_id, url, bot_id, use_spider=False, find_max_links=True,
                      selected_urls=None, recrawl=False):
    """
    Background scrape task — replaces the old threading.Thread approach.

    Runs entirely inside the Celery worker process. Cannot affect gunicorn.
    Auto-retries up to 3 times on failure with 60s delay.
    Has a 10-minute soft time limit so a hung scrape is marked failed, not stuck forever.
    
    If selected_urls is provided, only those specific URLs are scraped (no crawling).
    """
    from app import app

    with app.app_context():
        from models.models import db, Bot, ScrapeJob, Document
        from utils.scraper import scrape_single_url, extract_sitemap_urls, crawl_website_links, is_safe_url
        from bot.cloud import upload_to_gemini, delete_from_gemini

        job = ScrapeJob.query.get(job_id)
        target_bot = Bot.query.get(bot_id)

        if not job or not target_bot:
            logger.error(f"Job {job_id} or Bot {bot_id} not found. Aborting.")
            return

        # Mark as 'running' so we can detect interrupted jobs after restart
        job.status = 'running'
        db.session.commit()

        crawl_limit = job.limit if job.limit else 20

        def add_log(msg):
            """Append a timestamped (UTC) progress log to the ScrapeJob record."""
            ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
            line = f"[{ts} UTC] {msg}"
            logger.info(line)
            j = ScrapeJob.query.get(job_id)
            if j:
                j.logs = (j.logs or "") + line + "\n"
                db.session.commit()

        add_log(f"[Celery] Initializing Scraper for: {url} (Limit: {crawl_limit} pages)")

        # --- RESOLVE URLs TO SCRAPE ---
        urls_to_scrape = []

        try:
            # If user selected specific URLs from the discovery panel, use those directly
            if selected_urls and isinstance(selected_urls, list) and len(selected_urls) > 0:
                urls_to_scrape = selected_urls[:crawl_limit]
                add_log(f"User selected {len(urls_to_scrape)} specific URL(s) to scrape.")
            elif use_spider:
                add_log(f"Deep Crawl Enabled: Searching for internal links (Limit: {crawl_limit})...")
                spider_data = crawl_website_links(url, max_pages=crawl_limit)
                if spider_data['success']:
                    urls_to_scrape = spider_data['urls']
                    add_log(f"Spider complete. Found {len(urls_to_scrape)} valid links.")

                    # AUTO-FALLBACK: If spider found very few links, the site is likely
                    # JS-rendered. Try to find and use the sitemap instead.
                    if len(urls_to_scrape) < 3:
                        add_log(f"[Warning] Spider found only {len(urls_to_scrape)} link(s). Site may be JavaScript-heavy.")
                        add_log(f"[Fallback] Attempting to find sitemap.xml...")

                        from urllib.parse import urlparse
                        parsed_base = urlparse(url)
                        sitemap_candidates = [
                            f"{parsed_base.scheme}://{parsed_base.netloc}/sitemap.xml",
                            f"{parsed_base.scheme}://{parsed_base.netloc}/sitemap_index.xml",
                            f"{parsed_base.scheme}://{parsed_base.netloc}/sitemap",
                        ]

                        sitemap_found = False
                        for sitemap_url in sitemap_candidates:
                            try:
                                import requests as req
                                resp = req.head(sitemap_url, timeout=5, allow_redirects=True,
                                               headers={'User-Agent': 'Mozilla/5.0'})
                                if resp.status_code == 200:
                                    add_log(f"[Fallback] Found sitemap at: {sitemap_url}")
                                    sitemap_data = extract_sitemap_urls(sitemap_url, max_urls=crawl_limit)
                                    if sitemap_data['success'] and len(sitemap_data['urls_to_scrape']) > len(urls_to_scrape):
                                        urls_to_scrape = sitemap_data['urls_to_scrape']
                                        add_log(f"[Fallback] Sitemap has {len(urls_to_scrape)} URLs. Using sitemap instead of spider.")
                                        sitemap_found = True
                                        break
                            except Exception:
                                continue

                        if not sitemap_found:
                            add_log(f"[Fallback] No sitemap found. Proceeding with {len(urls_to_scrape)} spider URL(s).")

                else:
                    job.status = 'failed'
                    job.error_message = spider_data.get('error', 'Spider failed')
                    add_log(f"Spider Failed: {job.error_message}")
                    db.session.commit()
                    return

            elif url.endswith('.xml'):
                add_log(f"Sitemap detected. Extracting URLs (Limit: {crawl_limit})...")
                sitemap_data = extract_sitemap_urls(url, max_urls=crawl_limit)
                if sitemap_data['success']:
                    urls_to_scrape = sitemap_data['urls_to_scrape']
                    add_log(f"Sitemap parsed. Found {len(urls_to_scrape)} links.")
                else:
                    job.status = 'failed'
                    job.error_message = sitemap_data['error']
                    add_log(f"Sitemap Failed: {job.error_message}")
                    db.session.commit()
                    return
            else:
                urls_to_scrape = [url]

        except Exception as exc:
            add_log(f"URL resolution error: {exc}. Retrying...")
            raise self.retry(exc=exc)

        # --- SCRAPE EACH URL ---
        success_count = 0
        error_logs = []
        scrape_dir = app.config['UPLOAD_FOLDER']

        # ═══════════════════════════════════════════════════════════════
        # PAGE-LEVEL DEDUP — the single choke point.
        #
        # Every scrape entry point (Edit Bot confirm, Create Bot wizard,
        # create_pipeline, super-admin public bot, retry, stuck-job recovery)
        # ends up here, so deduping in this task covers all of them at once.
        # Deduping only in start_scrape missed most of those paths.
        #
        # Two passes:
        #   1. collapse duplicates WITHIN this batch (a sitemap or a hand-picked
        #      selection can easily contain /a and /a/)
        #   2. drop pages already ingested for this bot, unless the caller
        #      explicitly asked to recrawl
        # ═══════════════════════════════════════════════════════════════
        from utils.url_tools import normalize_url, dedupe_urls

        urls_to_scrape, dupes_in_batch = dedupe_urls(urls_to_scrape)
        if dupes_in_batch:
            add_log(f"[dedup] Removed {dupes_in_batch} duplicate URL(s) from this batch.")

        # Map normalized URL -> existing Document for this bot
        already = {}
        for doc in Document.query.filter(
            Document.bot_id == target_bot.id,
            Document.source_url.isnot(None)
        ).all():
            already[doc.source_url] = doc

        if recrawl:
            # Intentional refresh: replace the old copy instead of stacking a
            # second one. Previously a recrawl just appended, so every refresh
            # permanently doubled the knowledge base.
            replaced = 0
            for target_url in urls_to_scrape:
                old = already.get(normalize_url(target_url))
                if not old:
                    continue
                try:
                    delete_from_gemini(old.filename, store_id=target_bot.store_id)
                except Exception as e:
                    add_log(f"[recrawl] Could not remove old vector for {old.filename}: {e}")
                try:
                    os.remove(os.path.join(scrape_dir, old.filename))
                except Exception:
                    pass
                db.session.delete(old)
                replaced += 1
            if replaced:
                db.session.commit()
                add_log(f"[recrawl] Replacing {replaced} previously scraped page(s).")
            already = {}
        else:
            before = len(urls_to_scrape)
            urls_to_scrape = [
                u for u in urls_to_scrape if normalize_url(u) not in already
            ]
            skipped = before - len(urls_to_scrape)
            if skipped:
                add_log(
                    f"[dedup] Skipping {skipped} page(s) already in this bot's "
                    f"knowledge base. Tick 'Refresh existing pages' to re-scrape them."
                )

        if not urls_to_scrape:
            add_log("Nothing new to scrape — every selected page is already indexed.")
            job.status = 'completed'
            job.logs = "\n".join(logs)
            db.session.commit()
            return {"status": "completed", "scraped": 0, "skipped": True}

        add_log(f"--- Starting Batch Scrape ({len(urls_to_scrape)} URLs) ---")

        for i, target_url in enumerate(urls_to_scrape):
            # SSRF check on each discovered URL (spider may find internal links)
            safe, safety_err = is_safe_url(target_url)
            if not safe:
                add_log(f"[{i+1}/{len(urls_to_scrape)}] BLOCKED (unsafe): {target_url} — {safety_err}")
                error_logs.append(f"Blocked unsafe URL: {target_url}")
                continue

            add_log(f"[{i+1}/{len(urls_to_scrape)}] Reading: {target_url}")

            try:
                result = scrape_single_url(target_url)
            except Exception as e:
                add_log(f"  SCRAPE ERROR: {e}")
                error_logs.append(f"Scrape Exception for {target_url}")
                continue

            if result['success']:
                safe_title = "".join(
                    x for x in result['title'] if x.isalnum() or x in " _-"
                ).strip()
                if not safe_title:
                    safe_title = "Scraped_Document"

                safe_filename = f"{safe_title}_{uuid.uuid4().hex[:6]}.md"
                filepath = os.path.join(scrape_dir, safe_filename)

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(result['content'])

                # Record the normalized source URL so this page can be
                # recognised as already-ingested on the next scrape.
                new_doc = Document(
                    bot_id=target_bot.id,
                    filename=safe_filename,
                    source_url=normalize_url(target_url),
                )
                db.session.add(new_doc)
                db.session.commit()

                try:
                    add_log(f"  -> Pushing to Gemini Vector Store...")
                    upload_to_gemini(filepath, target_bot.store_id)
                    success_count += 1
                    add_log(f"  SUCCESS: Encoded as {safe_filename}")
                except Exception as e:
                    add_log(f"  GEMINI ERROR: Could not upload file.")
                    error_logs.append(f"Gemini Upload Failed for {target_url}")
            else:
                error_msg = result.get('error', 'Unknown API Error')
                add_log(f"  FIRECRAWL FAILED: {error_msg}")
                error_logs.append(f"Scrape Failed for {target_url}")

            time.sleep(2)  # Rate limit between URLs

        # --- FINALIZE JOB STATUS ---
        job = ScrapeJob.query.get(job_id)
        if success_count > 0:
            job.status = 'completed'
            add_log(f"\n--- INGESTION COMPLETE. {success_count} files vectorized. ---")
            if error_logs:
                job.error_message = f"Partial success ({success_count} scraped)."

            # --- AUTO-EXTRACT LINKS, EMAILS, PHONES FROM ALL BOTS ---
            # Only if find_max_links is enabled (default: True)
            # Extract from page content (markdown has [text](url) links, emails, phones)
            if urls_to_scrape and find_max_links:
                import re
                from urllib.parse import urlparse, urljoin

                existing_links = target_bot.managed_links or []
                existing_values = {link.get('url', '') for link in existing_links}

                def auto_categorize(url_path):
                    path = url_path.lower()
                    if 'pricing' in path or 'plan' in path or 'buy' in path or 'shop' in path:
                        return 'pricing'
                    elif 'register' in path or 'signup' in path or 'sign-up' in path or 'start' in path or 'order' in path:
                        return 'action'
                    elif 'login' in path or 'signin' in path or 'account' in path:
                        return 'action'
                    elif 'contact' in path or 'support' in path or 'help' in path or 'faq' in path:
                        return 'support'
                    elif 'feature' in path or 'how' in path or 'docs' in path or 'guide' in path or 'about' in path or 'learn' in path:
                        return 'info'
                    else:
                        return 'link'

                def make_label(url_str):
                    parsed = urlparse(url_str)
                    path = parsed.path.strip('/')
                    if not path:
                        return parsed.netloc
                    segment = path.split('/')[-1]
                    segment = segment.replace('.html', '').replace('.htm', '').replace('.php', '')
                    segment = segment.replace('-', ' ').replace('_', ' ')
                    return segment.title()[:50]

                new_links_added = 0

                # 1. Add all crawled/discovered URLs
                for scraped_url in urls_to_scrape:
                    if scraped_url not in existing_values:
                        parsed = urlparse(scraped_url)
                        existing_links.append({
                            "label": make_label(scraped_url),
                            "url": scraped_url,
                            "category": auto_categorize(parsed.path),
                        })
                        existing_values.add(scraped_url)
                        new_links_added += 1

                # 2. Extract links, emails, phones from page CONTENT
                # Read all scraped markdown files for this job
                all_content = ""
                for scraped_url in urls_to_scrape:
                    # We already wrote the files — read them back for parsing
                    pass  # Content was already processed above

                # Parse links from markdown content (stored in uploads folder)
                import glob
                recent_files = sorted(
                    glob.glob(os.path.join(scrape_dir, "*.md")),
                    key=os.path.getmtime, reverse=True
                )[:len(urls_to_scrape) + 5]  # Get recently created files

                for fpath in recent_files:
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read()

                        # Extract URLs from markdown [text](url) and bare URLs
                        found_urls = re.findall(r'https?://[^\s\)\]\>"\']+', content)
                        base_domain = urlparse(url).netloc

                        for found_url in found_urls:
                            # Clean trailing punctuation
                            found_url = found_url.rstrip('.,;:!?)')
                            if found_url not in existing_values and len(found_url) < 300:
                                parsed = urlparse(found_url)
                                # Skip image/asset/media URLs
                                skip_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.pdf', '.css', '.js', '.woff', '.woff2', '.ttf', '.mp4', '.mp3')
                                if any(parsed.path.lower().endswith(ext) for ext in skip_extensions):
                                    continue
                                # Skip asset/CDN paths
                                skip_paths = ('/dam/', '/assets/', '/static/', '/images/', '/media/', '/cdn/', '/_next/')
                                if any(skip in parsed.path.lower() for skip in skip_paths):
                                    continue
                                # Only add same-domain links
                                if parsed.netloc == base_domain or parsed.netloc.endswith('.' + base_domain):
                                    existing_links.append({
                                        "label": make_label(found_url),
                                        "url": found_url,
                                        "category": auto_categorize(parsed.path),
                                    })
                                    existing_values.add(found_url)
                                    new_links_added += 1

                        # Extract email addresses (skip our own platform emails)
                        platform_emails = {
                            (os.getenv('EMAIL_ADDRESS') or '').lower(),
                            (os.getenv('SUPPORT_EMAIL') or '').lower(),
                            'bubblteams@gmail.com',
                            'system@bubbl.ooo',
                        }
                        emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', content)
                        for email in set(emails):
                            if email.lower() in platform_emails:
                                continue  # Skip our own emails
                            # Skip common no-reply/generic emails
                            if any(skip in email.lower() for skip in ['noreply', 'no-reply', 'mailer-daemon', 'postmaster']):
                                continue
                            mailto = f"mailto:{email}"
                            if mailto not in existing_values and email not in existing_values:
                                existing_links.append({
                                    "label": email,
                                    "url": mailto,
                                    "category": "email",
                                })
                                existing_values.add(mailto)
                                new_links_added += 1

                        # Extract phone numbers WITH country codes
                        # Matches: +91 98765 43210, +1-800-123-4567, (022) 1234-5678, etc.
                        phone_pattern = r'(?:\+\d{1,3}[\s\-]?)(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{3,5}'
                        phones = re.findall(phone_pattern, content)
                        for phone in set(phones):
                            phone_clean = phone.strip()
                            digits_only = re.sub(r'\D', '', phone_clean)
                            # Must be 10-15 digits (real phone numbers)
                            # AND must not appear as part of a URL/asset path
                            if len(digits_only) >= 10 and len(digits_only) <= 15:
                                # Skip if this number appears inside a URL (likely an asset ID)
                                if digits_only in ''.join(found_urls):
                                    continue
                                tel = f"tel:+{digits_only}" if not phone_clean.startswith('+') else f"tel:{phone_clean.replace(' ', '').replace('-', '')}"
                                if tel not in existing_values:
                                    existing_links.append({
                                        "label": phone_clean,
                                        "url": tel,
                                        "category": "phone",
                                    })
                                    existing_values.add(tel)
                                    new_links_added += 1

                    except Exception:
                        continue

                if new_links_added > 0:
                    target_bot.managed_links = list(existing_links)  # new list object forces SQLAlchemy dirty detection
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(target_bot, 'managed_links')
                    db.session.commit()
                    add_log(f"[Links] Auto-extracted {new_links_added} items (URLs + emails + phones).")

                    # Invalidate bot cache so chat prompt picks up new links immediately
                    try:
                        from extensions import cache
                        cache.delete(f'bot_config_{bot_id}')
                    except Exception:
                        pass  # Cache invalidation is best-effort

        else:
            job.status = 'failed'
            job.error_message = "Failed to scrape any URLs."
            add_log("\n--- INGESTION FAILED ---")

        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Job {job_id} finished: {job.status} ({success_count} URLs scraped)")



# ═══════════════════════════════════════════
# RECOVERY: Re-queue stuck/interrupted scrape jobs on worker startup
# ═══════════════════════════════════════════

@celery.task(bind=True)
def recover_stuck_scrape_jobs(self):
    """
    Finds scrape jobs stuck in 'pending' or 'running' state (older than 2 minutes)
    and re-queues them. Called once on worker startup via worker_ready signal.

    This handles the case where:
    - Celery was restarted mid-scrape (task killed, job stays 'running')
    - A task was queued but never picked up (stayed 'pending' in DB but
      the Redis message was lost/acknowledged)
    """
    from app import app

    with app.app_context():
        from models.models import db, ScrapeJob, Bot

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=2)

        # Find jobs that are stuck (pending/running and created more than 2 min ago)
        stuck_jobs = ScrapeJob.query.filter(
            ScrapeJob.status.in_(['pending', 'running']),
            ScrapeJob.created_at < cutoff
        ).all()

        if not stuck_jobs:
            logger.info("[recovery] No stuck scrape jobs found.")
            return {"recovered": 0}

        recovered = 0
        for job in stuck_jobs:
            bot = Bot.query.get(job.bot_id)
            if not bot:
                # Bot was deleted — mark job failed
                job.status = 'failed'
                job.error_message = 'Bot no longer exists.'
                db.session.commit()
                continue

            # Reset to pending and re-queue
            job.status = 'pending'
            job.logs = (job.logs or "") + f"\n[Recovery] Job re-queued after worker restart at {now.strftime('%H:%M:%S UTC')}\n"
            db.session.commit()

            # Re-dispatch the task
            async_scrape_task.delay(job.id, job.url, job.bot_id, False)
            recovered += 1
            logger.info(f"[recovery] Re-queued job {job.id} (bot {job.bot_id}, url: {job.url[:60]})")

        logger.info(f"[recovery] Recovered {recovered} stuck scrape jobs.")
        return {"recovered": recovered}


# --- Worker startup signal: auto-run recovery ---
from celery.signals import worker_ready

@worker_ready.connect
def on_worker_ready(**kwargs):
    """When the Celery worker boots up, check for stuck jobs and re-queue them."""
    recover_stuck_scrape_jobs.delay()


# ═══════════════════════════════════════════
# ASYNC DISCOVERY TASK — Live link counter
# ═══════════════════════════════════════════

@celery.task(bind=True, soft_time_limit=120, time_limit=150)
def async_discover_task(self, discover_id, url, use_spider, find_max_links, discovery_limit, scrape_limit):
    """
    Runs link discovery in a Celery worker and writes progress to Redis
    so the frontend can poll and show a live incrementing counter.

    State stored in Redis under key: discover:{discover_id}
    Format: JSON  { status, urls, total_found, estimated_total,
                    scrape_count, method, error }
    TTL: 5 minutes (discovery results are short-lived)
    """
    import json
    import redis as redis_lib
    from celery_app import REDIS_URL

    r = redis_lib.from_url(REDIS_URL, decode_responses=True)
    key = f"discover:{discover_id}"
    TTL = 300  # 5 minutes

    def save(data):
        r.setex(key, TTL, json.dumps(data))

    # Initial state
    save({"status": "running", "urls": [], "total_found": 0,
          "estimated_total": 0, "scrape_count": 0, "method": "unknown", "error": None})

    try:
        from utils.scraper import crawl_website_links, extract_sitemap_urls, is_safe_url
        from urllib.parse import urlparse

        urls_found = []
        method_used = "single_page"
        estimated_total = 0

        if use_spider:
            method_used = "deep_crawl"
            # Patch crawl_website_links to emit progress after each page
            headers_req = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            import requests as req
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            visited = set()
            queue = [url]
            domain = urlparse(url).netloc

            BAD_EXT = ('.pdf', '.jpg', '.png', '.xml', '.zip', '.css', '.js',
                       '.jpeg', '.gif', '.webp', '.svg', '.mp4', '.woff', '.ttf')

            while queue and len(urls_found) < discovery_limit:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                urls_found.append(current)

                # Push live progress to Redis after every URL found
                save({
                    "status": "running",
                    "urls": urls_found[:],
                    "total_found": len(urls_found),
                    "estimated_total": len(urls_found) + len(queue),
                    "scrape_count": min(len(urls_found), scrape_limit),
                    "method": method_used,
                    "error": None,
                })

                try:
                    resp = req.get(current, headers=headers_req, timeout=5)
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for link in soup.find_all('a', href=True):
                        full = urljoin(current, link['href']).split('?')[0]
                        if (urlparse(full).netloc == domain
                                and full not in visited
                                and full not in queue
                                and not full.lower().endswith(BAD_EXT)):
                            queue.append(full)
                except Exception:
                    pass

            estimated_total = len(urls_found) + len(queue)

            # Fallback: sitemap if spider found very few
            if len(urls_found) < 3:
                parsed = urlparse(url)
                sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
                try:
                    resp = req.head(sitemap_url, timeout=5, allow_redirects=True,
                                    headers={'User-Agent': 'Mozilla/5.0'})
                    if resp.status_code == 200:
                        sd = extract_sitemap_urls(sitemap_url, max_urls=discovery_limit)
                        if sd['success'] and len(sd['urls_to_scrape']) > len(urls_found):
                            urls_found = sd['urls_to_scrape']
                            estimated_total = len(urls_found)
                            method_used = "sitemap_fallback"
                except Exception:
                    pass

        elif url.endswith('.xml'):
            method_used = "sitemap"
            # For sitemap: parse all at once but emit progress per-URL
            sd = extract_sitemap_urls(url, max_urls=discovery_limit)
            if sd['success']:
                for u in sd['urls_to_scrape']:
                    urls_found.append(u)
                    save({
                        "status": "running",
                        "urls": urls_found[:],
                        "total_found": len(urls_found),
                        "estimated_total": len(urls_found),
                        "scrape_count": min(len(urls_found), scrape_limit),
                        "method": method_used,
                        "error": None,
                    })
            estimated_total = len(urls_found)

        else:
            urls_found = [url]
            estimated_total = 1
            method_used = "single_page"

        if estimated_total < len(urls_found):
            estimated_total = len(urls_found)

        # Final state
        save({
            "status": "done",
            "urls": urls_found,
            "total_found": len(urls_found),
            "estimated_total": estimated_total,
            "scrape_count": min(len(urls_found), scrape_limit),
            "method": method_used,
            "error": None,
        })

    except Exception as exc:
        save({
            "status": "error",
            "urls": [],
            "total_found": 0,
            "estimated_total": 0,
            "scrape_count": 0,
            "method": "unknown",
            "error": str(exc)[:300],
        })
        raise
