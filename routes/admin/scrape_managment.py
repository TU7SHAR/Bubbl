import threading
import os
import uuid
import time
from datetime import datetime
from flask import request, jsonify, current_app, session

from models.models import db, Bot, ScrapeJob, Document
from utils.scraper import scrape_single_url, extract_sitemap_urls, crawl_website_links
from bot.cloud import upload_to_gemini
from . import admin_bp

def process_url_batch(app, job, target_bot, urls_to_scrape):
    with app.app_context():
        success_count = 0
        error_logs = []
        scrape_dir = app.config['UPLOAD_FOLDER']

        print(f"\nStarting batch scrape of {len(urls_to_scrape)} URLs...")

        for i, target_url in enumerate(urls_to_scrape):
            print(f"[{i+1}/{len(urls_to_scrape)}] Requesting: {target_url}")
            
            result = scrape_single_url(target_url)

            if result['success']:
                safe_title = "".join(x for x in result['title'] if x.isalnum() or x in " _-").strip()
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
                    upload_to_gemini(filepath, target_bot.store_id)
                    success_count += 1
                    print(f"  SUCCESS: Saved and uploaded as {safe_filename}")
                        
                except Exception as e:
                    print(f" GEMINI ERROR: Could not upload {safe_filename}")
                    error_logs.append(f"Gemini Upload Failed for {target_url}")
            else:
                error_msg = result.get('error', 'Unknown API Error')
                print(f"FIRECRAWL FAILED: {error_msg}")
                error_logs.append(f"Scrape Failed for {target_url}")

            time.sleep(2)

        if success_count > 0:
            job.status = 'completed'
            if error_logs:
                job.error_message = f"Partial success ({success_count} scraped). Errors: " + " | ".join(error_logs)
        else:
            job.status = 'failed'
            job.error_message = "Failed to scrape any URLs. Errors: " + " | ".join(error_logs)

        job.completed_at = datetime.utcnow()
        db.session.commit()

def async_scrape_task(app, job_id, url, bot_id, use_spider=False):
    with app.app_context():
        job = ScrapeJob.query.get(job_id)
        target_bot = Bot.query.get(bot_id)
        
        if not job or not target_bot:
            return

        # Retrieve the limit we saved in start_scrape
        crawl_limit = job.limit if job.limit else 20 

        # --- CORRECTED HELPER FUNCTION ---
        def add_log(msg):
            print(msg)  # Keep terminal output
            # We re-query inside to ensure we have the latest session state in the thread
            j = ScrapeJob.query.get(job_id)
            if j:
                j.logs = (j.logs or "") + msg + "\n"
                db.session.commit()
        # ---------------------------------

        add_log(f"Initializing Scraper for Target: {url} (Limit: {crawl_limit} pages)")
        urls_to_scrape = []
        
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

        success_count = 0
        error_logs = []
        scrape_dir = app.config['UPLOAD_FOLDER']

        add_log(f"--- Starting Batch Scrape ({len(urls_to_scrape)} URLs) ---")

        for i, target_url in enumerate(urls_to_scrape):
            add_log(f"[{i+1}/{len(urls_to_scrape)}] Reading: {target_url}")
            
            result = scrape_single_url(target_url)

            if result['success']:
                # Clean title for filename
                safe_title = "".join(x for x in result['title'] if x.isalnum() or x in " _-").strip()
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
                    add_log(f"  ➜ Pushing to Gemini Vector Store...")
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

            time.sleep(2)

        # Finalize job status
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

        job.completed_at = datetime.utcnow()
        db.session.commit()

@admin_bp.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # Safely handle missing JSON payload
    data = request.json or {}
    
    url = data.get('url')
    use_spider = data.get('use_spider', False)
    
    try:
        max_urls = int(data.get('max_urls') or 20)
    except ValueError:
        max_urls = 20

    # Try to get bot_id from JSON payload, then fallback to session
    bot_id = data.get('bot_id')
    if not bot_id:
        bot_id = session.get('active_bot_id')

    # -------- DEBUGGING PRINTS --------
    print("\n--- SCRAPE TARGET DEBUG ---")
    print(f"Payload Data: {data}")
    print(f"URL: {url}")
    print(f"BOT_ID: {bot_id}")
    print(f"---------------------------\n")

    # Split the 400 errors so the UI tells us exactly what failed
    if not url:
        return jsonify({"error": "Missing URL in request."}), 400
        
    if not bot_id:
        return jsonify({"error": "No Bot ID provided. Cannot link documents."}), 400

    new_job = ScrapeJob(bot_id=bot_id, url=url, status='pending', limit=max_urls)
    db.session.add(new_job)
    db.session.commit()

    app_obj = current_app._get_current_object()
    thread = threading.Thread(target=async_scrape_task, args=(app_obj, new_job.id, url, bot_id, use_spider))
    thread.start()

    return jsonify({"success": True, "job_id": new_job.id, "message": "Scraping started."})




# 
# @admin_bp.route('/api/scrape/start', methods=['POST'])
# def start_scrape():
#     if 'user_id' not in session:
#         return jsonify({"error": "Unauthorized"}), 401

#     data = request.json
#     url = data.get('url')
#     use_spider = data.get('use_spider', False)
#     max_urls = int(data.get('max_urls', 20))
#     bot_id = session.get('active_bot_id')

#     if not url or not bot_id:
#         return jsonify({"error": "Missing URL or no active Bot selected."}), 400

#     new_job = ScrapeJob(bot_id=bot_id, url=url, status='pending', limit=max_urls)
#     db.session.add(new_job)
#     db.session.commit()

#     app_obj = current_app._get_current_object()
#     thread = threading.Thread(target=async_scrape_task, args=(app_obj, new_job.id, url, bot_id, use_spider))
#     thread.start()

#     return jsonify({"success": True, "job_id": new_job.id, "message": "Scraping started."})

@admin_bp.route('/api/scrape/status/<int:job_id>', methods=['GET'])
def check_scrape_status(job_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    job = ScrapeJob.query.get_or_404(job_id)
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "error": job.error_message,
        "logs": job.logs or ""
    })