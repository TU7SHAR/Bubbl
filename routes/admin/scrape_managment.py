import os
from flask import request, jsonify, session

from models.models import db, Bot, ScrapeJob, Organization
from tasks.scrape_tasks import async_discover_links_task, async_scrape_task
from utils.scraper import is_safe_url
from utils.plan_limits import check_scrape_limit
from extensions import limiter
from . import admin_bp

# Scrape duration varies by the target site and Firecrawl response time. Return a
# range instead of presenting a single exact-looking number to users.
MIN_SECONDS_PER_PAGE = 3
MAX_SECONDS_PER_PAGE = 7


def _parse_page_limit(value, default=20):
    """Return a positive page limit for untrusted request data."""
    try:
        return max(1, int(value or default))
    except (ValueError, TypeError):
        return default


def _discovery_limit(find_max_links, requested_limit, plan_limit):
    """Resolve how many real URLs the finder may return for this request."""
    if find_max_links:
        return plan_limit
    return min(requested_limit, plan_limit)


def _time_estimate(page_count):
    """Return a realistic scrape-time range based on URLs actually selectable."""
    return {
        "estimated_seconds_min": page_count * MIN_SECONDS_PER_PAGE,
        "estimated_seconds_max": page_count * MAX_SECONDS_PER_PAGE,
    }


@admin_bp.route('/api/scrape/discover', methods=['POST'])
def discover_links():
    """
    Quick link discovery — finds URLs on a site WITHOUT scraping content.
    
    The finder returns real, selectable URLs up to the user's plan allowance.
    When Find Max Links is off, the user's page limit is honored as a smaller cap.
    If the crawl hits that cap, remaining queued links are used only to provide
    an approximate site-size hint; estimates never inflate the scrape count.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)

    user_limit = _parse_page_limit(data.get('max_urls'))

    if not url:
        return jsonify({"error": "URL is required."}), 400

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    # --- PLAN LIMIT ---
    plan_limit = check_scrape_limit(session.get('org_id'))
    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    discovery_limit = _discovery_limit(find_max_links, user_limit, plan_limit)
    task = async_discover_links_task.delay(
        url, use_spider, discovery_limit, plan_limit, plan_name
    )
    session['link_discovery_task_id'] = task.id
    return jsonify({
        "success": True,
        "pending": True,
        "discovery_id": task.id,
    }), 202


@admin_bp.route('/api/scrape/discover/<task_id>', methods=['GET'])
@limiter.exempt
def discovery_status(task_id):
    """Return the current user's background link-discovery result."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if task_id != session.get('link_discovery_task_id'):
        return jsonify({"error": "Discovery not found"}), 404

    task = async_discover_links_task.AsyncResult(task_id)
    if task.successful():
        result = task.result or {"error": "Discovery returned no result."}
        session.pop('link_discovery_task_id', None)
        return jsonify(result)
    if task.failed():
        session.pop('link_discovery_task_id', None)
        return jsonify({"error": "Link discovery failed. Please try again."}), 500

    return jsonify({
        "success": True,
        "pending": True,
        "status": task.state.lower(),
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
    
    max_urls = _parse_page_limit(data.get('max_urls'))

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

    estimate = _time_estimate(max_urls)

    return jsonify({
        "success": True,
        "job_id": new_job.id,
        "pages": max_urls,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,
        **estimate,
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