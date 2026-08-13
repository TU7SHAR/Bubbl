"""
TRANSCRIPT SERVICE — one way to read a conversation.

Before this, the same transcript existed in four shapes:
  1. ChatMessage rows read by a filter block in share_conversation()
  2. the SAME filter block copy-pasted verbatim into get_conversation_history()
  3. SharedConversation.messages_snapshot (JSONB)
  4. a {role, text} shape invented client-side purely to satisfy the PDF builder
plus _getVisibleChatHistory() scraping the DOM as a fifth fallback.

The platform-bot `or_(bot_id == x, bot_id IS NULL)` filter was also written out
four separate times across views.py and bot_management.py.

Everything now goes through here.
"""

from sqlalchemy import or_

from models.models import ChatMessage


def bot_message_filter(bot=None, bot_id=None):
    """
    SQLAlchemy filter selecting the messages that belong to a bot.

    The platform bot also owns legacy rows written before bot_id was recorded
    (bot_id IS NULL), so it needs a wider filter than a normal bot. That
    special case was duplicated in four places; this is the only copy.
    """
    if bot is not None:
        if getattr(bot, 'bot_type', None) == 'platform':
            return or_(ChatMessage.bot_id == bot.id, ChatMessage.bot_id.is_(None))
        return ChatMessage.bot_id == bot.id
    if bot_id is not None:
        return ChatMessage.bot_id == bot_id
    # No bot scope — caller is filtering by session alone.
    return None


def get_transcript(session_id, bot=None, bot_id=None):
    """
    Read one conversation, oldest message first.

    Returns a list of plain dicts so every consumer (share snapshot, print
    view, transcript pages) works off an identical shape:
        {role, content, created_at, tokens_used, rating}

    created_at is an ISO string (or None) so the value is JSON-serialisable
    and can be written straight into a snapshot.
    """
    if not session_id:
        return []

    q = ChatMessage.query.filter(ChatMessage.session_id == session_id)
    f = bot_message_filter(bot=bot, bot_id=bot_id)
    if f is not None:
        q = q.filter(f)

    rows = q.order_by(ChatMessage.created_at.asc()).all()
    return [
        {
            'role': r.role,
            'content': r.content or '',
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'tokens_used': r.tokens_used or 0,
            'rating': getattr(r, 'rating', None),
        }
        for r in rows
    ]


def normalize_messages(raw):
    """
    Coerce a stored snapshot into the canonical shape.

    Snapshots are JSONB and have been written by more than one code path over
    time, so they can arrive as a JSON string, as a list of dicts with missing
    keys, or (defensively) as a list of bare strings. The template must never
    crash on a public URL because of a legacy row.
    """
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []

    out = []
    for m in raw:
        if isinstance(m, dict):
            out.append({
                'role': m.get('role') or 'bot',
                'content': m.get('content') or '',
                'created_at': m.get('created_at'),
                'tokens_used': m.get('tokens_used') or 0,
                'rating': m.get('rating'),
            })
        else:
            out.append({
                'role': 'bot',
                'content': str(m),
                'created_at': None,
                'tokens_used': 0,
                'rating': None,
            })
    return out


def snapshot_payload(messages):
    """Trim a transcript to just the fields worth freezing into a share snapshot."""
    return [
        {
            'role': m['role'],
            'content': m['content'],
            'created_at': m.get('created_at'),
        }
        for m in messages
    ]
