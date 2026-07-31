"""Super Admin — Chat conversation viewer."""
from flask import render_template, request, make_response
from models.models import db, ChatMessage, Bot, User
from sqlalchemy import func
from . import super_admin_bp
from .decorators import super_admin_required
import csv, io


@super_admin_bp.route('/conversations')
@super_admin_required
def conversations_page():
    """List all chat sessions grouped by session_id."""
    page = request.args.get('page', 1, type=int)
    per_page = 30

    # Global rating analytics (all-time)
    total_liked    = ChatMessage.query.filter_by(rating=1).count()
    total_disliked = ChatMessage.query.filter_by(rating=-1).count()
    total_rated    = total_liked + total_disliked

    # Get distinct sessions with their message count and last activity
    sessions_query = db.session.query(
        ChatMessage.session_id,
        ChatMessage.bot_id,
        func.count(ChatMessage.id).label('msg_count'),
        func.max(ChatMessage.created_at).label('last_activity'),
        func.min(ChatMessage.created_at).label('started_at'),
    ).group_by(ChatMessage.session_id, ChatMessage.bot_id)\
     .order_by(func.max(ChatMessage.created_at).desc())

    total = sessions_query.count()
    total_pages = max((total + per_page - 1) // per_page, 1)
    sessions = sessions_query.offset((page - 1) * per_page).limit(per_page).all()

    enriched = []
    for s in sessions:
        bot = Bot.query.get(s.bot_id) if s.bot_id else None

        owner_name, owner_email = 'Bubbl Platform', '—'
        if bot and bot.created_by:
            owner = User.query.get(bot.created_by)
            if owner:
                owner_name = owner.name
                owner_email = owner.email

        ip_row = ChatMessage.query.filter(
            ChatMessage.session_id == s.session_id,
            ChatMessage.ip_address.isnot(None)
        ).first()
        visitor_ip = ip_row.ip_address if ip_row else '—'

        # Per-session rating counts
        liked    = ChatMessage.query.filter_by(session_id=s.session_id, rating=1).count()
        disliked = ChatMessage.query.filter_by(session_id=s.session_id, rating=-1).count()

        enriched.append({
            'session_id':   s.session_id,
            'bot_name':     bot.bot_name if bot else 'Bubbl (Public)',
            'owner_name':   owner_name,
            'owner_email':  owner_email,
            'ip_address':   visitor_ip,
            'msg_count':    s.msg_count,
            'last_activity': s.last_activity,
            'started_at':   s.started_at,
            'liked':        liked,
            'disliked':     disliked,
        })

    return render_template('super_admin/conversations.html',
        sessions=enriched,
        page=page,
        total_pages=total_pages,
        total_conversations=total,
        total_liked=total_liked,
        total_disliked=total_disliked,
        total_rated=total_rated,
    )


@super_admin_bp.route('/conversations/<session_id>')
@super_admin_required
def conversation_detail(session_id):
    """View a single chat transcript with rating highlights."""
    messages = ChatMessage.query.filter_by(session_id=session_id)\
        .order_by(ChatMessage.created_at.asc()).all()

    if not messages:
        return render_template('super_admin/conversation_detail.html',
            messages=[], session_id=session_id, bot_name='Unknown',
            liked=0, disliked=0)

    bot = Bot.query.get(messages[0].bot_id) if messages[0].bot_id else None
    bot_name = bot.bot_name if bot else 'Bubbl (Public)'

    liked    = sum(1 for m in messages if m.rating == 1)
    disliked = sum(1 for m in messages if m.rating == -1)

    return render_template('super_admin/conversation_detail.html',
        messages=messages,
        session_id=session_id,
        bot_name=bot_name,
        liked=liked,
        disliked=disliked,
    )


@super_admin_bp.route('/conversations/<session_id>/export')
@super_admin_required
def export_conversation(session_id):
    """Export a single conversation as CSV including ratings."""
    messages = ChatMessage.query.filter_by(session_id=session_id)\
        .order_by(ChatMessage.created_at.asc()).all()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['timestamp', 'role', 'content', 'rating', 'tokens', 'ip'])
    for m in messages:
        rating_label = '👍 Liked' if m.rating == 1 else ('👎 Disliked' if m.rating == -1 else '')
        cw.writerow([
            m.created_at.strftime('%Y-%m-%d %H:%M:%S') if m.created_at else '',
            m.role,
            (m.content or '')[:500],
            rating_label,
            m.tokens_used or 0,
            m.ip_address or '',
        ])

    output = make_response(si.getvalue())
    output.headers['Content-Type'] = 'text/csv'
    output.headers['Content-Disposition'] = f'attachment; filename=conversation_{session_id[:8]}.csv'
    return output
