from datetime import datetime, timezone, timedelta
from models.models import db, Organization, Bot

PLAN_LIMITS = {
    'free': {'bots': 1, 'messages': 200},
    'starter': {'bots': 2, 'messages': 2000},
    'growth': {'bots': 5, 'messages': 10000},
    'pro': {'bots': 999, 'messages': 50000},  # 999 = effectively unlimited
}

def get_org_limits(org_id):
    """Get the current plan limits for an organization"""
    org = Organization.query.get(org_id)
    if not org:
        return PLAN_LIMITS['free']
    return PLAN_LIMITS.get(org.plan, PLAN_LIMITS['free'])

def check_message_limit(org_id):
    """
    Check if org has messages remaining. Returns (allowed, remaining, limit).
    Also handles monthly reset.
    """
    org = Organization.query.get(org_id)
    if not org:
        return False, 0, 0

    limits = PLAN_LIMITS.get(org.plan, PLAN_LIMITS['free'])

    # Check if we need to reset the monthly counter
    now = datetime.now(timezone.utc)
    if org.messages_reset_at is None or now >= org.messages_reset_at:
        # Reset counter and set next reset date (1 month from now)
        org.messages_used = 0
        org.messages_reset_at = now + timedelta(days=30)
        db.session.commit()

    remaining = limits['messages'] - (org.messages_used or 0)
    allowed = remaining > 0

    return allowed, remaining, limits['messages']

def increment_message_count(org_id):
    """Increment the message counter for an org"""
    org = Organization.query.get(org_id)
    if org:
        org.messages_used = (org.messages_used or 0) + 1
        db.session.commit()

def check_bot_limit(org_id):
    """
    Check if org can create more bots. Returns (allowed, current_count, limit).
    """
    org = Organization.query.get(org_id)
    if not org:
        return False, 0, 0

    limits = PLAN_LIMITS.get(org.plan, PLAN_LIMITS['free'])
    current_bots = Bot.query.filter_by(org_id=org_id).count()
    allowed = current_bots < limits['bots']

    return allowed, current_bots, limits['bots']
