import os
from flask import request, jsonify, session

from models.models import db, Bot, ScrapeJob, Organization
from tasks.scrape_tasks import async_scrape_task
from utils.scraper import is_safe_url
from utils.plan_limits import check_scrape_limit
from extensions import limiter
from . import admin_bp

# Rough per-page cost: ~3s scrape + ~2s vectorize per URL
SECONDS_PER_PAGE = 5

# Discovery limits per plan — how many pages the finder crawls to show the user.
# Higher plans discover more links so users can pick from a larger pool.
PLAN_DISCOVERY_LIMITS = {
    'free': 50,
    'starter': 200,
    'growth': 300,
    'pro': 500,
}


@admin_bp.route('/api/scrape/discover', methods=['POST'])
def discover_links():
    """
    Link discovery — finds URLs on a site WITHOUT scraping content.
    Discovery depth scales with the user's plan.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    from utils.scraper import crawl_website_links, extract_sitemap_urls

    data = request.json or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)

    try:
        user_page_limit = int(data.get('max_urls') or 20)
    except (ValueError, TypeError):
        user_page_limit = 20

    if not url:
        return jsonify({"error": "URL is required."}), 400

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    # --- PLAN LIMITS ---
    plan_limit = check_scrape_limit(session.get('org_id'))  # max pages user can SCRAPE
    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    # Discovery limit: how many pages to crawl for finding links
    # Uses plan-based limit, but if user set a lower page limit AND deep crawl is OFF,
    # respect that (they want fewer results).
    max_discovery = PLAN_DISCOVERY_LIMITS.get(plan_name, 50)
    if not use_spider:
        # Without deep crawl, respect user's page limit exactly
        DISCOVERY_LIMIT = min(user_page_limit, max_discovery)
    else:
        # With deep crawl, use the full plan discovery allowance
        DISCOVERY_LIMIT = max_discovery

    urls_found = []
    method_used = 'single'
    estimated_total = 0

    try:
        if use_spider:
            method_used = 'deep_crawl'
            result = crawl_website_links(url, max_pages=DISCOVERY_LIMIT)
            if result['success']:
                urls_found = result['urls']
                remaining_queue = result.get('remaining_queue', 0)
                estimated_total = len(urls_found) + remaining_queue
            # Fallback to sitemap if spider found very few
            if len(urls_found) < 3:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
                try:
                    import requests as req
                    resp = req.head(sitemap_url, timeout=5, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
                    if resp.status_code == 200:
                        sitemap_data = extract_sitemap_urls(sitemap_url, max_urls=max_discovery)
                        if sitemap_data['success'] and len(sitemap_data['urls_to_scrape']) > len(urls_found):
                            urls_found = sitemap_data['urls_to_scrape']
                            estimated_total = len(urls_found)
                            method_used = 'sitemap_fallback'
                except Exception:
                    pass
        elif url.endswith('.xml'):
            method_used = 'sitemap'
            sitemap_data = extract_sitemap_urls(url, max_urls=max_discovery)
            if sitemap_data['success']:
                urls_found = sitemap_data['urls_to_scrape']
                estimated_total = len(urls_found)
        else:
            urls_found = [url]
            estimated_total = 1
            method_used = 'single_page'
    except Exception as e:
        return jsonify({"error": f"Discovery failed: {str(e)[:200]}"}), 500

    if estimated_total < len(urls_found):
        estimated_total = len(urls_found)

    # Scrape count = how many the user CAN scrape (capped by plan)
    capped = len(urls_found) > plan_limit
    scrape_count = min(len(urls_found), plan_limit)

    # Time estimate based on what will actually be scraped
    est_seconds = scrape_count * SECONDS_PER_PAGE

    return jsonify({
        "success": True,
        "total_found": len(urls_found),
        "estimated_total": estimated_total,
        "scrape_count": scrape_count,
        "capped": capped,
        "plan": plan_name,
        "plan_limit": plan_limit,
        "method": method_used,
        "urls": urls_found,
        "estimated_seconds": est_seconds,
    })


@admin_bp.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    
    url = data.get('url')
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', True)
    selected_urls = data.get('selected_urls', None)
    
    try:
        max_urls = int(data.get('max_urls') or 20)
    except ValueError:
        max_urls = 20

    bot_id = data.get('bot_id')
    if not bot_id:
        bot_id = session.get('active_bot_id')

    if not url:
        return jsonify({"error": "Missing URL in request."}), 400
        
    if not bot_id:
        return jsonify({"error": "No Bot ID provided. Cannot link documents."}), 400

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    # --- PLAN LIMIT ---
    plan_scrape_limit = check_scrape_limit(session.get('org_id'))

    # If user selected specific URLs, use those (strictly capped by plan)
    if selected_urls and isinstance(selected_urls, list) and len(selected_urls) > 0:
        if len(selected_urls) > plan_scrape_limit:
            return jsonify({"error": f"You selected {len(selected_urls)} pages but your plan allows only {plan_scrape_limit}. Please upgrade or select fewer pages."}), 400
        max_urls = len(selected_urls)
    else:
        # Fallback: cap to plan limit
        if max_urls > plan_scrape_limit:
            max_urls = plan_scrape_limit
        selected_urls = None

    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    new_job = ScrapeJob(bot_id=bot_id, url=url, status='pending', limit=max_urls)
    db.session.add(new_job)
    db.session.commit()

    # Queue the scrape in Celery
    async_scrape_task.delay(new_job.id, url, bot_id, use_spider, find_max_links, selected_urls)

    est_seconds = max_urls * SECONDS_PER_PAGE

    return jsonify({
        "success": True,
        "job_id": new_job.id,
        "pages": max_urls,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,
        "estimated_seconds": est_seconds,
        "message": f"Scraping {max_urls} pages.",
    })


@admin_bp.route('/api/scrape/status/<int:job_id>', methods=['GET'])
@limiter.exempt
def check_scrape_status(job_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    job = ScrapeJob.query.get_or_404(job_id)
    
    bot = Bot.query.get(job.bot_id)
    if not bot or (bot.org_id != session.get('org_id') and bot.bot_type != 'platform'):
        return jsonify({"error": "Not found"}), 404
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "error": job.error_message,
        "logs": job.logs or ""
    })
