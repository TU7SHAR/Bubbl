import os
from urllib.parse import urlparse
from flask import request, jsonify, session

from models.models import db, Bot, ScrapeJob, Organization
from tasks.scrape_tasks import async_discover_links_task, async_scrape_task
from utils.scraper import is_safe_url
from utils.plan_limits import check_discovery_limit, check_scrape_limit
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
    if plan_limit is None:
        return requested_limit
    return min(requested_limit, plan_limit)


def _cap_to_plan(requested_count, plan_limit):
    """Cap a positive page count while treating ``None`` as unlimited."""
    if plan_limit is None:
        return requested_count
    return min(requested_count, plan_limit)


def _origin(url):
    """Return a normalized HTTP origin tuple for strict same-origin checks."""
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == 'https' else 80
    return parsed.scheme, parsed.hostname.lower(), port


def _validate_selected_urls(selected_urls, scrape_limit, allowed_urls, base_url):
    """Validate a discovery-bound selection without silently truncating it."""
    if not isinstance(selected_urls, list):
        raise ValueError("Selected URLs must be a list.")
    if not selected_urls:
        raise ValueError("Select at least one URL to scrape.")
    if any(not isinstance(item, str) or not item.strip() for item in selected_urls):
        raise ValueError("Every selected URL must be a non-empty string.")

    cleaned = [item.strip() for item in selected_urls]
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("Duplicate selected URLs are not allowed.")
    if scrape_limit is not None and len(cleaned) > scrape_limit:
        raise ValueError(f"Your plan allows up to {scrape_limit} pages per scrape.")

    allowed = set(allowed_urls or [])
    if any(item not in allowed for item in cleaned):
        raise ValueError("One or more selected URLs were not in this discovery result.")

    base_origin = _origin(base_url)
    if base_origin is None or any(_origin(item) != base_origin for item in cleaned):
        raise ValueError("Selected URLs must have the same origin as the discovered site.")
    return cleaned


def _discovery_records():
    """Return this session's bounded discovery metadata mapping."""
    records = session.get('link_discoveries')
    return records if isinstance(records, dict) else {}


def _discovery_record(task_id):
    """Return a discovery only when it belongs to the current session identity."""
    record = _discovery_records().get(task_id)
    if not isinstance(record, dict):
        return None
    if (
        record.get('user_id') != session.get('user_id')
        or record.get('org_id') != session.get('org_id')
    ):
        return None
    return record


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
    bot_id = data.get('bot_id')
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', False)
    user_limit = _parse_page_limit(data.get('max_urls'))

    if not url:
        return jsonify({"error": "URL is required."}), 400
    if not bot_id:
        return jsonify({"error": "Bot ID is required for discovery."}), 400

    target_bot = Bot.query.filter_by(
        id=bot_id, org_id=session.get('org_id')
    ).first()
    if not target_bot or target_bot.bot_type == 'platform':
        return jsonify({"error": "Bot not found."}), 404

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    discovery_plan_limit = check_discovery_limit(session.get('org_id'))
    scrape_plan_limit = check_scrape_limit(session.get('org_id'))
    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    discovery_limit = _discovery_limit(
        find_max_links, user_limit, discovery_plan_limit
    )
    task = async_discover_links_task.delay(
        url, use_spider, discovery_limit, scrape_plan_limit, plan_name
    )

    records = dict(_discovery_records())
    records[task.id] = {
        'user_id': session.get('user_id'),
        'org_id': session.get('org_id'),
        'bot_id': target_bot.id,
        'url': url,
    }
    while len(records) > 8:
        records.pop(next(iter(records)))
    session['link_discoveries'] = records

    return jsonify({
        "success": True,
        "pending": True,
        "discovery_id": task.id,
        "bot_id": target_bot.id,
    }), 202


@admin_bp.route('/api/scrape/discover/<task_id>', methods=['GET'])
@limiter.exempt
def discovery_status(task_id):
    """Return the current user's background link-discovery result."""
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    record = _discovery_record(task_id)
    if not record:
        return jsonify({"error": "Discovery not found"}), 404

    bot = Bot.query.filter_by(
        id=record.get('bot_id'), org_id=session.get('org_id')
    ).first()
    if not bot:
        return jsonify({"error": "Discovery not found"}), 404

    task = async_discover_links_task.AsyncResult(task_id)
    if task.successful():
        result = dict(task.result or {"error": "Discovery returned no result."})
        result['discovery_id'] = task_id
        result['bot_id'] = bot.id
        return jsonify(result)
    if task.failed():
        records = dict(_discovery_records())
        records.pop(task_id, None)
        session['link_discoveries'] = records
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
    
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    find_max_links = data.get('find_max_links', True)
    selected_urls = data.get('selected_urls')
    discovery_id = data.get('discovery_id')
    max_urls = _parse_page_limit(data.get('max_urls'))

    bot_id = data.get('bot_id') or session.get('active_bot_id')
    if not url:
        return jsonify({"error": "Missing URL in request."}), 400
    if not bot_id:
        return jsonify({"error": "No Bot ID provided. Cannot link documents."}), 400

    target_bot = Bot.query.filter_by(
        id=bot_id, org_id=session.get('org_id')
    ).first()
    if not target_bot or target_bot.bot_type == 'platform':
        return jsonify({"error": "Bot not found."}), 404

    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    plan_scrape_limit = check_scrape_limit(session.get('org_id'))
    if selected_urls is not None:
        if not discovery_id:
            return jsonify({"error": "Discovery ID is required for selected URLs."}), 400

        record = _discovery_record(discovery_id)
        if (
            not record
            or record.get('bot_id') != target_bot.id
            or record.get('url') != url
        ):
            return jsonify({"error": "Discovery not found."}), 404

        discovery_task = async_discover_links_task.AsyncResult(discovery_id)
        if not discovery_task.successful():
            return jsonify({"error": "Discovery is not ready."}), 409
        discovery_result = discovery_task.result
        if not isinstance(discovery_result, dict) or not discovery_result.get('success'):
            return jsonify({"error": "Discovery did not complete successfully."}), 400

        try:
            selected_urls = _validate_selected_urls(
                selected_urls,
                plan_scrape_limit,
                discovery_result.get('urls'),
                record['url'],
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        for selected_url in selected_urls:
            selected_safe, selected_error = is_safe_url(selected_url)
            if not selected_safe:
                return jsonify({
                    "error": f"Invalid selected URL: {selected_error}"
                }), 400
        max_urls = len(selected_urls)
    else:
        max_urls = _cap_to_plan(max_urls, plan_scrape_limit)

    org = Organization.query.get(session.get('org_id'))
    plan_name = (org.plan if org else 'free') or 'free'

    new_job = ScrapeJob(
        bot_id=target_bot.id, url=url, status='pending', limit=max_urls
    )
    db.session.add(new_job)
    db.session.commit()

    async_scrape_task.delay(
        new_job.id,
        url,
        target_bot.id,
        use_spider,
        find_max_links,
        selected_urls,
    )

    if discovery_id:
        records = dict(_discovery_records())
        records.pop(discovery_id, None)
        session['link_discoveries'] = records

    estimate = _time_estimate(max_urls)
    return jsonify({
        "success": True,
        "job_id": new_job.id,
        "pages": max_urls,
        "plan": plan_name,
        "plan_limit": plan_scrape_limit,
        "scrape_limit": plan_scrape_limit,
        "scrape_unlimited": plan_scrape_limit is None,
        **estimate,
        "message": f"Scraping started ({max_urls} pages selected).",
    })

@admin_bp.route('/api/scrape/status/<int:job_id>', methods=['GET'])
@limiter.exempt
def check_scrape_status(job_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    job = ScrapeJob.query.join(Bot).filter(
        ScrapeJob.id == job_id, Bot.org_id == session.get('org_id'), Bot.bot_type != 'platform'
    ).first_or_404()
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "error": job.error_message,
        "logs": job.logs or ""
    })