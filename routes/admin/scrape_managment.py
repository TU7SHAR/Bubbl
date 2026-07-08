import os
from flask import request, jsonify, session

from models.models import db, Bot, ScrapeJob
from tasks.scrape_tasks import async_scrape_task
from utils.scraper import is_safe_url
from utils.plan_limits import check_scrape_limit
from . import admin_bp

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

    # Split the 400 errors so the UI tells us exactly what failed
    if not url:
        return jsonify({"error": "Missing URL in request."}), 400
        
    if not bot_id:
        return jsonify({"error": "No Bot ID provided. Cannot link documents."}), 400

    # --- SSRF PROTECTION: Validate URL before processing ---
    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    # --- PLAN LIMIT: Cap max pages to plan allowance ---
    plan_scrape_limit = check_scrape_limit(session.get('org_id'))
    if max_urls > plan_scrape_limit:
        max_urls = plan_scrape_limit

    new_job = ScrapeJob(bot_id=bot_id, url=url, status='pending', limit=max_urls)
    db.session.add(new_job)
    db.session.commit()

    # Queue the scrape in Celery (runs in separate worker process)
    async_scrape_task.delay(new_job.id, url, bot_id, use_spider)

    return jsonify({"success": True, "job_id": new_job.id, "message": f"Scraping started (max {max_urls} pages)."})

@admin_bp.route('/api/scrape/status/<int:job_id>', methods=['GET'])
def check_scrape_status(job_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    job = ScrapeJob.query.get_or_404(job_id)
    
    # Verify the job belongs to the user's organization
    bot = Bot.query.get(job.bot_id)
    if not bot or bot.org_id != session.get('org_id'):
        return jsonify({"error": "Not found"}), 404
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "error": job.error_message,
        "logs": job.logs or ""
    })