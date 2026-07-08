from datetime import datetime, timezone, timedelta
from models.models import db, Organization, Bot, Document, ScrapeJob

# =========================================
# PLAN LIMITS — BUBBL.OOO
# =========================================
# Defines and enforces subscription tier capabilities.
# All limit checks return a consistent (allowed, current, limit) tuple.

PLAN_LIMITS = {
    'free': {
        'bots': 1,
        'messages': 200,
        'documents_per_bot': 3,
        'scrape_pages': 5,
        'file_size_mb': 5,
        'team_members': 1,
    },
    'starter': {
        'bots': 2,
        'messages': 2000,
        'documents_per_bot': 10,
        'scrape_pages': 20,
        'file_size_mb': 10,
        'team_members': 3,
    },
    'growth': {
        'bots': 5,
        'messages': 10000,
        'documents_per_bot': 50,
        'scrape_pages': 100,
        'file_size_mb': 10,
        'team_members': 10,
    },
    'pro': {
        'bots': 999,         # Effectively unlimited
        'messages': 50000,
        'documents_per_bot': 200,
        'scrape_pages': 500,
        'file_size_mb': 10,
        'team_members': 50,
    },
}


def get_org_plan(org_id):
    """Get the organization's current plan name (defaults to 'free')."""
    org = Organization.query.get(org_id)
    if not org:
        return 'free'
    return org.plan or 'free'


def get_org_limits(org_id):
    """Get the current plan limits dict for an organization."""
    plan = get_org_plan(org_id)
    return PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])


def check_message_limit(org_id):
    """
    Check if org has messages remaining. Returns (allowed, remaining, limit).
    Also handles monthly reset automatically.
    """
    org = Organization.query.get(org_id)
    if not org:
        return False, 0, 0

    limits = PLAN_LIMITS.get(org.plan or 'free', PLAN_LIMITS['free'])

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
    """Increment the message counter for an org."""
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

    limits = PLAN_LIMITS.get(org.plan or 'free', PLAN_LIMITS['free'])
    current_bots = Bot.query.filter_by(org_id=org_id).count()
    allowed = current_bots < limits['bots']

    return allowed, current_bots, limits['bots']


def check_document_limit(org_id, bot_id):
    """
    Check if a bot can accept more documents. Returns (allowed, current_count, limit).
    """
    org = Organization.query.get(org_id)
    if not org:
        return False, 0, 0

    limits = PLAN_LIMITS.get(org.plan or 'free', PLAN_LIMITS['free'])
    current_docs = Document.query.filter_by(bot_id=bot_id).count()
    doc_limit = limits['documents_per_bot']
    allowed = current_docs < doc_limit

    return allowed, current_docs, doc_limit


def check_scrape_limit(org_id):
    """
    Check the max pages allowed per scrape job for this org's plan.
    Returns the max_pages cap for the plan.
    """
    org = Organization.query.get(org_id)
    if not org:
        return PLAN_LIMITS['free']['scrape_pages']

    limits = PLAN_LIMITS.get(org.plan or 'free', PLAN_LIMITS['free'])
    return limits['scrape_pages']


def check_team_member_limit(org_id):
    """
    Check if org can add more team members. Returns (allowed, current_count, limit).
    """
    from models.models import User
    
    org = Organization.query.get(org_id)
    if not org:
        return False, 0, 0

    limits = PLAN_LIMITS.get(org.plan or 'free', PLAN_LIMITS['free'])
    current_members = User.query.filter_by(org_id=org_id).count()
    member_limit = limits['team_members']
    allowed = current_members < member_limit

    return allowed, current_members, member_limit


def get_usage_summary(org_id):
    """
    Returns a comprehensive usage summary for the organization.
    Useful for profile/dashboard display.
    """
    org = Organization.query.get(org_id)
    if not org:
        return None

    from models.models import User

    plan = org.plan or 'free'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])

    # Messages
    messages_used = org.messages_used or 0
    messages_limit = limits['messages']
    messages_percent = min(int((messages_used / messages_limit) * 100), 100) if messages_limit > 0 else 0

    # Bots
    bots_used = Bot.query.filter_by(org_id=org_id).count()
    bots_limit = limits['bots']

    # Team members
    members_used = User.query.filter_by(org_id=org_id).count()
    members_limit = limits['team_members']

    # Reset date
    reset_date = org.messages_reset_at.strftime('%b %d, %Y') if org.messages_reset_at else 'Next billing cycle'

    return {
        'plan': plan,
        'plan_name': plan.capitalize(),
        'messages_used': messages_used,
        'messages_limit': messages_limit,
        'messages_percent': messages_percent,
        'bots_used': bots_used,
        'bots_limit': bots_limit,
        'members_used': members_used,
        'members_limit': members_limit,
        'documents_per_bot_limit': limits['documents_per_bot'],
        'scrape_pages_limit': limits['scrape_pages'],
        'file_size_mb': limits['file_size_mb'],
        'reset_date': reset_date,
    }
