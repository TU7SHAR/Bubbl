"""Super Admin — Chat conversation viewer."""
from flask import render_template, request, jsonify
from models.models import db, ChatMessage, Bot
from sqlalchemy import func
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/conversations')
@super_admin_required
def conversations_page():
    """List all chat sessions grouped by session_id."""
    page = request.args.get('page', 1, type=int)
    per_page = 30

    # Get distinct sessions with their message count and last activity
    sessions_query = db.session.query(
        ChatMessage.session_id,
        ChatMessage.bot_id,
        func.count(ChatMessage.id).label('msg_count'),
        func.max(ChatMessage.created_at).label('last_activity'),
        func.min(ChatMessage.created_at).label('started_at'),
    ).group_by(ChatMessage.session_id, ChatMessage.bot_id)\
     .order_by(func.max(ChatMessage.created_at).desc())

    # Manual pagination
    total = sessions_query.count()
    total_pages = max((total + per_page - 1) // per_page, 1)
    sessions = sessions_query.offset((page - 1) * per_page).limit(per_page).all()

    enriched = []
    for s in sessions:
        bot = Bot.query.get(s.bot_id) if s.bot_id else None
        enriched.append({
            'session_id': s.session_id,
            'bot_name': bot.bot_name if bot else 'Bubbl (Public)',
            'msg_count': s.msg_count,
            'last_activity': s.last_activity,
            'started_at': s.started_at,
        })

    return render_template('super_admin/conversations.html',
        sessions=enriched, page=page, total_pages=total_pages, total_conversations=total,
    )


@super_admin_bp.route('/conversations/<session_id>')
@super_admin_required
def conversation_detail(session_id):
    """View a single chat transcript."""
    messages = ChatMessage.query.filter_by(session_id=session_id)\
        .order_by(ChatMessage.created_at.asc()).all()

    if not messages:
        return render_template('super_admin/conversation_detail.html', messages=[], session_id=session_id, bot_name='Unknown')

    bot = Bot.query.get(messages[0].bot_id) if messages[0].bot_id else None
    bot_name = bot.bot_name if bot else 'Bubbl (Public)'

    return render_template('super_admin/conversation_detail.html',
        messages=messages, session_id=session_id, bot_name=bot_name,
    )
