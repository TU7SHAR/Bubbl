"""Super Admin — Public Bot Management (platform chatbot powered by scraped site content)."""
import uuid
from flask import render_template, request, jsonify
from models.models import db, Bot, Document, ScrapeJob, ChatMessage
from bot.cloud import create_dynamic_store, upload_to_gemini, delete_from_gemini
from tasks.scrape_tasks import async_scrape_task
from utils.scraper import is_safe_url
from . import super_admin_bp
from .decorators import super_admin_required


def _get_or_create_platform_bot():
    """
    Get the platform bot (bot_type='platform'). Creates one if it doesn't exist.
    This bot holds the scraped content for the public-facing Bubbl assistant.
    """
    bot = Bot.query.filter_by(bot_type='platform').first()
    if bot:
        return bot

    # Need real FK references — Bot.org_id -> organization.id, Bot.created_by -> user.id
    from models.models import Organization, User

    # Get or create a platform org
    platform_org = Organization.query.filter_by(name='Bubbl Platform').first()
    if not platform_org:
        platform_org = Organization(name='Bubbl Platform', plan='pro')
        db.session.add(platform_org)
        db.session.flush()

    # created_by must reference a real user (FK to user.id)
    first_user = User.query.order_by(User.id.asc()).first()
    if not first_user:
        # Edge case: no users exist yet — create the official platform user
        # Uses the super admin credentials from env so it's a real login-able account
        import bcrypt
        import os
        admin_email = os.getenv('SUPER_ADMIN_MAIL', 'bubblteams@gmail.com')
        admin_hash = os.getenv('SUPER_ADMIN_HASH')
        if not admin_hash:
            admin_hash = bcrypt.hashpw(b'platform_system', bcrypt.gensalt()).decode('utf-8')
        first_user = User(
            org_id=platform_org.id, name='Bubbl Team', email=admin_email,
            password_hash=admin_hash, role='admin', is_verified=True
        )
        db.session.add(first_user)
        db.session.flush()

    # Auto-create the platform bot
    store_id = create_dynamic_store("Bubbl Platform Bot")
    if not store_id:
        store_id = f"platform_{uuid.uuid4().hex[:12]}"

    bot = Bot(
        bot_name="Bubbl Platform Bot",
        bot_type='platform',
        visibility='public',
        system_prompt="",
        created_by=first_user.id,    # Real user ID (satisfies FK to user table)
        org_id=platform_org.id,      # Real org ID (satisfies FK to organization table)
        store_id=store_id,
        is_active=True,
    )
    db.session.add(bot)
    db.session.commit()
    return bot


@super_admin_bp.route('/public_bot')
@super_admin_required
def public_bot_page():
    """Public bot management dashboard."""
    bot = _get_or_create_platform_bot()
    docs = Document.query.filter_by(bot_id=bot.id).order_by(Document.created_at.desc()).all()
    scrape_jobs = ScrapeJob.query.filter_by(bot_id=bot.id).order_by(ScrapeJob.created_at.desc()).limit(10).all()

    # Stats
    total_conversations = ChatMessage.query.filter_by(bot_id=None).distinct(ChatMessage.session_id).count()
    total_messages = ChatMessage.query.filter_by(bot_id=None).count()

    return render_template('super_admin/public_bot.html',
        bot=bot,
        docs=docs,
        scrape_jobs=scrape_jobs,
        total_conversations=total_conversations,
        total_messages=total_messages,
    )


@super_admin_bp.route('/public_bot/scrape', methods=['POST'])
@super_admin_required
def public_bot_scrape():
    """Start a scrape job for the platform bot."""
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    use_spider = data.get('use_spider', False)
    max_urls = int(data.get('max_urls', 50))

    if not url:
        return jsonify({"error": "URL is required."}), 400

    # SSRF protection
    safe, error_msg = is_safe_url(url)
    if not safe:
        return jsonify({"error": f"Invalid URL: {error_msg}"}), 400

    bot = _get_or_create_platform_bot()

    # Cap at 100 pages for platform bot (generous limit)
    if max_urls > 100:
        max_urls = 100

    new_job = ScrapeJob(bot_id=bot.id, url=url, status='pending', limit=max_urls)
    db.session.add(new_job)
    db.session.commit()

    # Queue in Celery
    async_scrape_task.delay(new_job.id, url, bot.id, use_spider)

    return jsonify({"success": True, "job_id": new_job.id, "message": f"Scraping started (max {max_urls} pages)."})


@super_admin_bp.route('/public_bot/delete_doc/<int:doc_id>', methods=['POST'])
@super_admin_required
def public_bot_delete_doc(doc_id):
    """Delete a document from the platform bot's knowledge base."""
    bot = _get_or_create_platform_bot()
    doc = Document.query.filter_by(id=doc_id, bot_id=bot.id).first()

    if not doc:
        return jsonify({"error": "Document not found."}), 404

    try:
        delete_from_gemini(doc.filename)
    except Exception:
        pass

    db.session.delete(doc)
    db.session.commit()
    return jsonify({"success": True, "filename": doc.filename})


@super_admin_bp.route('/public_bot/clear_all', methods=['POST'])
@super_admin_required
def public_bot_clear_all():
    """Delete ALL documents from the platform bot (nuclear reset)."""
    bot = _get_or_create_platform_bot()
    docs = Document.query.filter_by(bot_id=bot.id).all()

    for doc in docs:
        try:
            delete_from_gemini(doc.filename)
        except Exception:
            pass
        db.session.delete(doc)

    db.session.commit()
    return jsonify({"success": True, "deleted": len(docs)})


@super_admin_bp.route('/public_bot/update_personality', methods=['POST'])
@super_admin_required
def public_bot_update_personality():
    """Update the platform bot's custom personality/system prompt override."""
    data = request.get_json(silent=True) or {}
    personality = (data.get('personality') or '').strip()

    bot = _get_or_create_platform_bot()
    bot.system_prompt = personality
    db.session.commit()

    return jsonify({"success": True, "message": "Personality updated."})


@super_admin_bp.route('/public_bot/scrape_status/<int:job_id>', methods=['GET'])
@super_admin_required
def public_bot_scrape_status(job_id):
    """Check status of a scrape job."""
    job = ScrapeJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "error": job.error_message,
        "logs": job.logs or "",
    })



@super_admin_bp.route('/public_bot/links', methods=['GET'])
@super_admin_required
def public_bot_get_links():
    """Get the current managed links for the platform bot."""
    bot = _get_or_create_platform_bot()
    links = bot.managed_links or []
    return jsonify({"success": True, "links": links})


@super_admin_bp.route('/public_bot/links', methods=['POST'])
@super_admin_required
def public_bot_save_links():
    """Save the managed links for the platform bot (replaces all)."""
    import json
    data = request.get_json(silent=True) or {}
    links = data.get('links', [])

    # Validate: each link must have label, url, category
    valid_categories = ['pricing', 'action', 'info', 'support', 'link', 'email', 'phone']
    cleaned = []
    for link in links:
        label = (link.get('label') or '').strip()
        url = (link.get('url') or '').strip()
        category = (link.get('category') or 'link').strip().lower()
        if label and url:
            if category not in valid_categories:
                category = 'link'
            cleaned.append({"label": label, "url": url, "category": category})

    bot = _get_or_create_platform_bot()
    bot.managed_links = cleaned
    db.session.commit()

    return jsonify({"success": True, "count": len(cleaned)})
