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
from celery_app import celery

logger = get_task_logger(__name__)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def async_scrape_task(self, job_id, url, bot_id, use_spider=False):
    """
    Background scrape task — replaces the old threading.Thread approach.
    
    Runs entirely inside the Celery worker process. Cannot affect gunicorn.
    Auto-retries up to 3 times on failure with 60s delay.
    """
    from app import app

    with app.app_context():
        from models.models import db, Bot, ScrapeJob, Document
        from utils.scraper import scrape_single_url, extract_sitemap_urls, crawl_website_links
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
        else:
            job.status = 'failed'
            job.error_message = "Failed to scrape any URLs."
            add_log("\n--- INGESTION FAILED ---")

        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Job {job_id} finished: {job.status} ({success_count} URLs scraped)")
