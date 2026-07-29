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
    Quick link discovery — finds URLs on a site WITHOUT scraping content.
    
    IMPORTANT: This runs SYNCHRONOUSLY in the gunicorn worker. It MUST be fast
    (< 30 seconds) or it blocks all other requests on this single-worker server.
    
    Strategy: Crawl up to 50 pages for discovery preview. If the site has more,
    we report the estimated total based on the link queue size at cutoff.
    The actual full crawl (up to plan limit) happens in Celery when user confirms.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    from utils.scraper import crawl_website_links, extract_sitemap_urls

    data = request.json or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)

    # Discovery preview limit — kept LOW because this blocks the web worker.
    # For deep crawl: scan up to 50 pages (takes ~30-60s max), extrapolate the rest.
    # The actual scrape (in Celery) will crawl the full amount.
    DISCOVERY_LIMIT = 50

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
    estimated_total = 0  # Estimated total pages on the site (may be > urls_found)

    try:
        if use_spider:
            method_used = 'deep_crawl'
            # Only crawl up to DISCOVERY_LIMIT pages for the preview
            result = crawl_website_links(url, max_pages=DISCOVERY_LIMIT)
            if result['success']:
                urls_found = result['urls']
                # Estimate total: if the queue still had pending links at cutoff,
                # the site likely has more pages. Report found + remaining queue.
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
                        sitemap_data = extract_sitemap_urls(sitemap_url, max_urls=500)
                        if sitemap_data['success'] and len(sitemap_data['urls_to_scrape']) > len(urls_found):
                            urls_found = sitemap_data['urls_to_scrape']
                            estimated_total = len(urls_found)
                            method_used = 'sitemap_fallback'
                except Exception:
                    pass
        elif url.endswith('.xml'):
            method_used = 'sitemap'
            sitemap_data = extract_sitemap_urls(url, max_urls=500)
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

    # Show ALL found URLs, but note how many will actually be scraped
    capped = estimated_total > plan_limit
    scrape_count = min(estimated_total, plan_limit)

    return jsonify({
        "success": True,
        "total_found": len(urls_found),
        "estimated_total": estimated_total,
        "scrape_count": scrape_count,
        "capped": capped,
        "plan": plan_name,
        "plan_limit": plan_limit,
        "method": method_used,
        "urls": urls_found,  # The URLs we actually discovered (up to 50)
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
    selected_urls = data.get('selected_urls', None)  # List of user-selected URLs to scrape
    
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
    
    # If user selected specific URLs, use those (capped by plan)
    if selected_urls and isinstance(selected_urls, list):
        max_urls = min(len(selected_urls), plan_scrape_limit)
        selected_urls = selected_urls[:plan_scrape_limit]
    else:
        requested = max_urls
        capped = requested > plan_scrape_limit
        if capped:
            max_urls = plan_scrape_limit
        selected_urls = None

    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    new_job = ScrapeJob(bot_id=bot_id, url=url, status='pending', limit=max_urls)
    db.session.add(new_job)
    db.session.commit()

    # Queue the scrape in Celery (runs in separate worker process)
    # Pass selected_urls so Celery only scrapes those specific pages
    async_scrape_task.delay(new_job.id, url, bot_id, use_spider, find_max_links, selected_urls)

    # Time estimate (single page scrapes are quick; deep crawl scales with pages)
    est_seconds = max_urls * SECONDS_PER_PAGE

    return jsonify({
        "success": True,
        "job_id": new_job.id,
        "pages": max_urls,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,
        "estimated_seconds": est_seconds,
        "message": f"Scraping started ({max_urls} pages selected).",
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