# =========================================
# CELERY SCRAPE TASKS — BUBBL.OOO
# =========================================
# Replaces threading.Thread in scrape_managment.py
# Runs in isolated Celery worker (gevent pool)
# Auto-retries on failure, logs progress to DB

import os
import uuid
import time
from datetime import datetime, timezone
from celery.utils.log import get_task_logger
from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery

logger = get_task_logger(__name__)


# soft_time_limit: raise SoftTimeLimitExceeded so we can mark the job failed cleanly.
# time_limit: hard kill a few seconds later if soft handling doesn't return.
@celery.task(bind=True, max_retries=3, default_retry_delay=60,
             soft_time_limit=600, time_limit=660)
def async_scrape_task(self, job_id, url, bot_id, use_spider=False):
    """
    Background scrape task — replaces the old threading.Thread approach.

    Runs entirely inside the Celery worker process. Cannot affect gunicorn.
    Auto-retries up to 3 times on failure with 60s delay.
    Has a 10-minute soft time limit so a hung scrape is marked failed, not stuck forever.
    """
    from app import app

    with app.app_context():
        from models.models import db, Bot, ScrapeJob, Document
        from utils.scraper import scrape_single_url, extract_sitemap_urls, crawl_website_links, is_safe_url
        from bot.cloud import upload_to_gemini

        job = ScrapeJob.query.get(job_id)
        target_bot = Bot.query.get(bot_id)

        if not job or not target_bot:
            logger.error(f"Job {job_id} or Bot {bot_id} not found. Aborting.")
            return

        crawl_limit = job.limit if job.limit else 20

        def add_log(msg):
            """Append progress log to the ScrapeJob record."""
            logger.info(msg)
            j = ScrapeJob.query.get(job_id)
            if j:
                j.logs = (j.logs or "") + msg + "\n"
                db.session.commit()

        add_log(f"[Celery] Initializing Scraper for: {url} (Limit: {crawl_limit} pages)")

        # --- RESOLVE URLs TO SCRAPE ---
        urls_to_scrape = []

        try:
            if use_spider:
                add_log(f"Deep Crawl Enabled: Searching for internal links (Limit: {crawl_limit})...")
                spider_data = crawl_website_links(url, max_pages=crawl_limit)
                if spider_data['success']:
                    urls_to_scrape = spider_data['urls']
                    add_log(f"Spider complete. Found {len(urls_to_scrape)} valid links.")
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

                new_doc = Document(bot_id=target_bot.id, filename=safe_filename)
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
            # Extract from page content (markdown has [text](url) links, emails, phones)
            if urls_to_scrape:
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
                                # Only add same-domain links or well-known external links
                                if parsed.netloc == base_domain or parsed.netloc.endswith('.' + base_domain):
                                    existing_links.append({
                                        "label": make_label(found_url),
                                        "url": found_url,
                                        "category": auto_categorize(parsed.path),
                                    })
                                    existing_values.add(found_url)
                                    new_links_added += 1

                        # Extract email addresses
                        emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', content)
                        for email in set(emails):
                            mailto = f"mailto:{email}"
                            if mailto not in existing_values and email not in existing_values:
                                existing_links.append({
                                    "label": email,
                                    "url": mailto,
                                    "category": "email",
                                })
                                existing_values.add(mailto)
                                new_links_added += 1

                        # Extract phone numbers (common formats)
                        phones = re.findall(r'(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}', content)
                        for phone in set(phones):
                            phone_clean = phone.strip()
                            # Only add if it looks like a real phone (7+ digits)
                            digits_only = re.sub(r'\D', '', phone_clean)
                            if len(digits_only) >= 7 and len(digits_only) <= 15:
                                tel = f"tel:{digits_only}"
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
                    target_bot.managed_links = existing_links
                    db.session.commit()
                    add_log(f"[Links] Auto-extracted {new_links_added} items (URLs + emails + phones).")

        else:
            job.status = 'failed'
            job.error_message = "Failed to scrape any URLs."
            add_log("\n--- INGESTION FAILED ---")

        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Job {job_id} finished: {job.status} ({success_count} URLs scraped)")
