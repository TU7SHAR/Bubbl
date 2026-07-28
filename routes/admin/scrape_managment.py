import os
from flask import request, jsonify, session

from models.models import db, Bot, ScrapeJob, Organization
from tasks.scrape_tasks import async_scrape_task
from utils.scraper import is_safe_url
from utils.plan_limits import check_scrape_limit
from extensions import limiter
from . import admin_bp

# Rough per-page cost: ~2s rate-limit sleep + ~2-3s scrape/index per URL
SECONDS_PER_PAGE = 4


@admin_bp.route('/api/scrape/discover', methods=['POST'])
def discover_links():
    """
    Quick link discovery — finds all URLs on a site WITHOUT scraping them.
    Returns the FULL list so the user can see the total, plus notes how many
    will actually be scraped based on their plan limit.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    from utils.scraper import crawl_website_links, extract_sitemap_urls

    data = request.json or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)

    # When Find Max Links is ON, discover as many as possible (up to 500)
    # When OFF, respect the user's page limit
    if find_max_links:
        max_urls = 500  # Discover up to 500 links (no artificial cap)
    else:
        try:
            max_urls = int(data.get('max_urls') or 50)
        except (ValueError, TypeError):
            max_urls = 50

    if not url:
        return jsonify({"error": "URL is required."}), 400

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    # --- PLAN LIMIT ---
    plan_limit = check_scrape_limit(session.get('org_id'))
    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    urls_found = []
    method_used = 'single'

    try:
        if use_spider:
            method_used = 'deep_crawl'
            result = crawl_website_links(url, max_pages=max_urls)
            if result['success']:
                urls_found = result['urls']
            # Fallback to sitemap if spider found very few
            if len(urls_found) < 3:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
                try:
                    import requests as req
                    resp = req.head(sitemap_url, timeout=5, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
                    if resp.status_code == 200:
                        sitemap_data = extract_sitemap_urls(sitemap_url, max_urls=max_urls)
                        if sitemap_data['success'] and len(sitemap_data['urls_to_scrape']) > len(urls_found):
                            urls_found = sitemap_data['urls_to_scrape']
                            method_used = 'sitemap_fallback'
                except Exception:
                    pass
        elif url.endswith('.xml'):
            method_used = 'sitemap'
            sitemap_data = extract_sitemap_urls(url, max_urls=max_urls)
            if sitemap_data['success']:
                urls_found = sitemap_data['urls_to_scrape']
        else:
            urls_found = [url]
            method_used = 'single_page'
    except Exception as e:
        return jsonify({"error": f"Discovery failed: {str(e)[:200]}"}), 500

    # Show ALL found URLs, but note how many will actually be scraped
    capped = len(urls_found) > plan_limit
    scrape_count = min(len(urls_found), plan_limit)

    return jsonify({
        "success": True,
        "total_found": len(urls_found),
        "scrape_count": scrape_count,
        "capped": capped,
        "plan": plan_name,
        "plan_limit": plan_limit,
        "method": method_used,
        "urls": urls_found,  # Return ALL found URLs (user sees full picture)
        "estimated_seconds": scrape_count * SECONDS_PER_PAGE,
    })


@admin_bp.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # Safely handle missing JSON payload
    data = request.json or {}
    
    url = data.get('url')
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', True)
    
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
    requested = max_urls
    plan_scrape_limit = check_scrape_limit(session.get('org_id'))
    capped = requested > plan_scrape_limit
    if capped:
        max_urls = plan_scrape_limit

    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    new_job = ScrapeJob(bot_id=bot_id, url=url, status='pending', limit=max_urls)
    db.session.add(new_job)
    db.session.commit()

    # Queue the scrape in Celery (runs in separate worker process)
    async_scrape_task.delay(new_job.id, url, bot_id, use_spider, find_max_links)

    # Time estimate (single page scrapes are quick; deep crawl scales with pages)
    est_seconds = (max_urls if use_spider else 1) * SECONDS_PER_PAGE

    return jsonify({
        "success": True,
        "job_id": new_job.id,
        "pages": max_urls,
        "requested": requested,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,
        "capped": capped,
        "estimated_seconds": est_seconds,
        "message": f"Scraping started (max {max_urls} pages).",
    })

@admin_bp.route('/api/scrape/status/<int:job_id>', methods=['GET'])
@limiter.exempt
def check_scrape_status(job_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    job = ScrapeJob.query.get_or_404(job_id)
    
    # Verify the job belongs to the user's organization (or is the platform bot)
    bot = Bot.query.get(job.bot_id)
    if not bot or (bot.org_id != session.get('org_id') and bot.bot_type != 'platform'):
        return jsonify({"error": "Not found"}), 404
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "error": job.error_message,
        "logs": job.logs or ""
    })