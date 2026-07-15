"""Super Admin — Bot management."""
from flask import render_template, request, jsonify, redirect
from models.models import db, Bot, BotUI, User, Document, ScrapeJob, Lead, Feedback, ChatMessage
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/bots')
@super_admin_required
def bots_page():
    """List all bots with metrics."""
    all_bots = Bot.query.order_by(Bot.id.desc()).all()
    enriched = []
    for b in all_bots:
        owner = User.query.get(b.created_by)
        enriched.append({
            'id': b.id,
            'name': b.bot_name,
            'owner': owner.name if owner else 'System',
            'owner_email': owner.email if owner else '',
            'type': b.bot_type or 'general',
            'docs': Document.query.filter_by(bot_id=b.id).count(),
            'scrapes': ScrapeJob.query.filter_by(bot_id=b.id).count(),
            'leads': Lead.query.filter_by(bot_id=b.id).count(),
            'interactions': b.interaction_count or 0,
            'tokens': b.tokens_used or 0,
            'is_active': getattr(b, 'is_active', True),
            'store_id': b.store_id,
            'created_at': getattr(b, 'created_at', None),
        })
    return render_template('super_admin/bots.html', bots=enriched)


@super_admin_bp.route('/bots/toggle', methods=['POST'])
@super_admin_required
def toggle_bot():
    """Enable/disable a bot."""
    data = request.get_json(silent=True) or {}
    try:
        bot_id = int(data.get('bot_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid bot ID."}), 400

    bot = Bot.query.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found."}), 404

    bot.is_active = not getattr(bot, 'is_active', True)
    db.session.commit()
    return jsonify({"success": True, "is_active": bot.is_active, "name": bot.bot_name})


# ═══════════════════════════════════════════
# NEW ROUTES
# ═══════════════════════════════════════════


@super_admin_bp.route('/bots/delete', methods=['POST'])
@super_admin_required
def delete_bot():
    """Delete a bot and all cascade data (docs, scrapes, leads, messages, feedback, ui)."""
    data = request.get_json(silent=True) or {}
    try:
        bot_id = int(data.get('bot_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid bot ID."}), 400

    bot = Bot.query.get(bot_id)
    if not bot:
        return jsonify({"error": "Bot not found."}), 404

    bot_name = bot.bot_name

    # Cascade delete handled by SQLAlchemy relationships, but let's be explicit
    Document.query.filter_by(bot_id=bot.id).delete()
    ScrapeJob.query.filter_by(bot_id=bot.id).delete()
    Lead.query.filter_by(bot_id=bot.id).delete()
    ChatMessage.query.filter_by(bot_id=bot.id).delete()
    Feedback.query.filter_by(bot_id=bot.id).delete()
    BotUI.query.filter_by(bot_id=bot.id).delete()

    db.session.delete(bot)
    db.session.commit()

    return jsonify({"success": True, "name": bot_name})


@super_admin_bp.route('/bots/<int:bot_id>')
@super_admin_required
def bot_detail(bot_id):
    """Detailed view and analytics for a single bot."""
    bot = Bot.query.get(bot_id)
    if not bot:
        return redirect('/super_admin/bots')

    owner = User.query.get(bot.created_by)
    docs = Document.query.filter_by(bot_id=bot.id).all()
    scrapes = ScrapeJob.query.filter_by(bot_id=bot.id).all()
    leads = Lead.query.filter_by(bot_id=bot.id).order_by(Lead.captured_at.desc()).all()
    messages_count = ChatMessage.query.filter_by(bot_id=bot.id).count()
    feedback = Feedback.query.filter_by(bot_id=bot.id).all()

    return render_template('super_admin/bot_detail.html',
        bot=bot, owner=owner, docs=docs, scrapes=scrapes,
        leads=leads, messages_count=messages_count, feedback=feedback)
