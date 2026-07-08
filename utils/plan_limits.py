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


# Monthly plan price in INR (used for proportionate refund maths)
PLAN_PRICE_INR = {
    'free': 0,
    'starter': 499,
    'growth': 1499,
    'pro': 4999,
}

# Standard billing period length used for daily proration
BILLING_DAYS = 30

# Refund eligibility window (days from purchase)
REFUND_WINDOW_DAYS = 14


def _aware(dt):
    """Return a timezone-aware (UTC) datetime, treating naive DB values as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def end_of_day(dt):
    """Return 23:59:59 (UTC) of the given datetime's calendar day."""
    dt = _aware(dt)
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def enforce_subscription_expiry(org):
    """
    Lazily downgrade a canceled subscription once its access window has ended.

    When a user cancels with a proportionate refund, we keep their plan active
    until 23:59 of the cancellation day (stored in subscription_ends_at). This
    function is called by the limit checks so that access is cut off correctly
    without needing a cron job.
    """
    if not org:
        return
    if org.subscription_status == 'canceled' and org.subscription_ends_at:
        now = datetime.now(timezone.utc)
        ends = _aware(org.subscription_ends_at)
        if now >= ends and (org.plan or 'free') != 'free':
            org.plan = 'free'
            org.subscription_status = 'free'
            org.paddle_subscription_id = None
            db.session.commit()


def calculate_proportionate_refund(payment, plan_price=None, cancel_dt=None):
    """
    Compute a proportionate (fractional) refund for a cancellation.

    Formula:
        daily_rate      = plan_price / BILLING_DAYS
        days_used       = (cancel_day - purchase_day) + 1   (current day counts)
        amount_consumed = daily_rate * days_used
        refund          = plan_price - amount_consumed      (floored at 0)

    Returns a dict with the full breakdown so the UI can show the maths.
    """
    if cancel_dt is None:
        cancel_dt = datetime.now(timezone.utc)
    cancel_dt = _aware(cancel_dt)

    purchase_dt = _aware(payment.created_at) if payment else cancel_dt
    if plan_price is None:
        plan_price = PLAN_PRICE_INR.get((payment.plan if payment else 'free'), 0)

    # Whole calendar days between purchase day and cancel day, inclusive of today
    days_elapsed = (cancel_dt.date() - purchase_dt.date()).days
    days_used = days_elapsed + 1  # the current day is consumed
    if days_used < 1:
        days_used = 1

    daily_rate = round(plan_price / BILLING_DAYS, 2)
    amount_consumed = round(daily_rate * days_used, 2)
    refund = round(plan_price - amount_consumed, 2)
    if refund < 0:
        refund = 0.0

    within_window = days_elapsed < REFUND_WINDOW_DAYS
    eligible = within_window and refund > 0

    return {
        'plan_price': round(plan_price, 2),
        'daily_rate': daily_rate,
        'billing_days': BILLING_DAYS,
        'days_used': days_used,
        'days_elapsed': days_elapsed,
        'amount_consumed': amount_consumed,
        'refund_amount': refund,
        'within_window': within_window,
        'refund_window_days': REFUND_WINDOW_DAYS,
        'eligible': eligible,
        'purchase_date': purchase_dt,
        'cancel_date': cancel_dt,
        'access_until': end_of_day(cancel_dt),
        'currency': (payment.currency if payment else 'INR') or 'INR',
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

    # Downgrade if a canceled subscription's access window has ended
    enforce_subscription_expiry(org)

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

    enforce_subscription_expiry(org)

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

    enforce_subscription_expiry(org)

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
        # Subscription lifecycle
        'subscription_status': org.subscription_status or ('active' if plan != 'free' else 'free'),
        'subscription_started_at': org.subscription_started_at,
        'subscription_ends_at': org.subscription_ends_at,
        'payment_method': org.payment_method,
        'card_brand': org.card_brand,
        'card_last4': org.card_last4,
    }
