import os
import uuid
import json
from flask import request, jsonify, session

from models.models import db, Bot, ScrapeJob, Organization
from tasks.scrape_tasks import async_scrape_task, async_discover_task
from utils.scraper import is_safe_url
from utils.plan_limits import check_scrape_limit, check_discover_limit
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

    Discovery limit and scrape limit are separate:
      - Discovery limit: how many links can be surfaced for selection (plan-based)
      - Scrape limit: how many of those links can actually have content fetched

    Find Max ON  → use the full plan discovery limit
    Find Max OFF → use the user's entered page limit (capped by the discovery limit)
    Deep Crawl   → never overrides the page limit; uses it as its own max_pages cap
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    from utils.scraper import crawl_website_links, extract_sitemap_urls

    data = request.json or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)

    # Separate plan limits
    plan_discover_limit = check_discover_limit(session.get('org_id'))
    plan_scrape_limit   = check_scrape_limit(session.get('org_id'))

    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    # Determine how many links to surface during discovery:
    #   Find Max ON  → full plan discovery limit (let user see everything available)
    #   Find Max OFF → respect the user's page limit input, capped by discovery limit
    if find_max_links:
        DISCOVERY_LIMIT = plan_discover_limit
    else:
        try:
            user_limit = int(data.get('max_urls') or 20)
        except (ValueError, TypeError):
            user_limit = 20
        # Cap user's input by the plan discovery limit (not scrape limit)
        DISCOVERY_LIMIT = min(user_limit, plan_discover_limit)

    if not url:
        return jsonify({"error": "URL is required."}), 400

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    urls_found = []
    method_used = 'single'
    estimated_total = 0  # Estimated total pages on the site (may be > urls_found)

    try:
        # Sitemap URLs always use XML parsing regardless of Deep Crawl toggle —
        # running the spider on an XML file just finds 1 link (the XML itself).
        if url.endswith('.xml'):
            method_used = 'sitemap'
            sitemap_data = extract_sitemap_urls(url, max_urls=DISCOVERY_LIMIT)
            if sitemap_data['success']:
                urls_found = sitemap_data['urls_to_scrape']
                estimated_total = len(urls_found)
        elif use_spider:
            method_used = 'deep_crawl'
            # Deep Crawl respects DISCOVERY_LIMIT — it does NOT override the page limit
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
                        sitemap_data = extract_sitemap_urls(sitemap_url, max_urls=DISCOVERY_LIMIT)
                        if sitemap_data['success'] and len(sitemap_data['urls_to_scrape']) > len(urls_found):
                            urls_found = sitemap_data['urls_to_scrape']
                            estimated_total = len(urls_found)
                            method_used = 'sitemap_fallback'
                except Exception:
                    pass
        else:
            urls_found = [url]
            estimated_total = 1
            method_used = 'single_page'
    except Exception as e:
        return jsonify({"error": f"Discovery failed: {str(e)[:200]}"}), 500

    if estimated_total < len(urls_found):
        estimated_total = len(urls_found)

    # How many of the discovered links the user is allowed to actually scrape
    # (based on scrape limit, NOT discovery limit)
    scrape_count = min(len(urls_found), plan_scrape_limit)

    return jsonify({
        "success": True,
        "total_found": len(urls_found),
        "estimated_total": estimated_total,
        "scrape_count": scrape_count,          # pre-selected count (up to scrape limit)
        "capped": len(urls_found) > plan_scrape_limit,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,       # actual scrape limit (for checkbox enforcement)
        "discover_limit": plan_discover_limit, # discovery limit (informational)
        "method": method_used,
        "urls": urls_found,
        # Estimated scrape time based on pre-selected count only
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

    # --- PLAN LIMIT: Cap actual scrape count to the plan's scrape limit ---
    # Discovery limit is irrelevant here — only the scrape limit matters.
    plan_scrape_limit = check_scrape_limit(session.get('org_id'))
    
    # If user selected specific URLs, use those (capped by scrape limit)
    if selected_urls and isinstance(selected_urls, list):
        if len(selected_urls) > plan_scrape_limit:
            return jsonify({
                "error": f"You selected {len(selected_urls)} pages but your plan allows scraping up to {plan_scrape_limit}. Please deselect some pages or upgrade your plan."
            }), 400
        max_urls = len(selected_urls)
        selected_urls = selected_urls[:plan_scrape_limit]
    else:
        if max_urls > plan_scrape_limit:
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

    # Time estimate based on the number of pages that will actually be scraped
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


@admin_bp.route('/api/scrape/discover/async', methods=['POST'])
def start_async_discover():
    """
    Kicks off a background discovery task and returns a discover_id.
    The frontend polls /api/scrape/discover/status/<id> to get live progress.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)

    if not url:
        return jsonify({"error": "URL is required."}), 400

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    plan_discover_limit = check_discover_limit(session.get('org_id'))
    plan_scrape_limit   = check_scrape_limit(session.get('org_id'))
    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    if find_max_links:
        discovery_limit = plan_discover_limit
    else:
        try:
            user_limit = int(data.get('max_urls') or 20)
        except (ValueError, TypeError):
            user_limit = 20
        discovery_limit = min(user_limit, plan_discover_limit)

    discover_id = uuid.uuid4().hex

    async_discover_task.delay(
        discover_id, url, use_spider, find_max_links,
        discovery_limit, plan_scrape_limit
    )

    return jsonify({
        "success": True,
        "discover_id": discover_id,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,
        "discover_limit": plan_discover_limit,
    })


@admin_bp.route('/api/scrape/discover/status/<discover_id>', methods=['GET'])
@limiter.exempt
def poll_discover_status(discover_id):
    """
    Returns current discovery progress from Redis.
    Called by frontend every 500ms during live discovery.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from celery_app import REDIS_URL
        import redis as redis_lib
        r = redis_lib.from_url(REDIS_URL, decode_responses=True)
        raw = r.get(f"discover:{discover_id}")
    except Exception as e:
        return jsonify({"error": f"Redis unavailable: {str(e)[:100]}"}), 500

    if not raw:
        return jsonify({"error": "Discovery job not found or expired."}), 404

    data = json.loads(raw)
    return jsonify(data)