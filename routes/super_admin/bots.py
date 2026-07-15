"""Super Admin — Bot management."""
from flask import render_template, request, jsonify
from models.models import db, Bot, User, Document, ScrapeJob, Lead
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
