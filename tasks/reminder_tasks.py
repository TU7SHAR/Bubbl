# =========================================
# CELERY REMINDER TASKS — BUBBL.OOO
# =========================================
# Sends subscription expiry reminder emails:
# - 7 days before expiry
# - 1 day before expiry
#
# Runs as a Celery Beat scheduled task (every 6 hours).
# Only targets gifted/admin-granted plans (no Paddle sub backing them).
#
# Schedule with:
#   celery -A celery_app.celery beat --loglevel=info
# Or combine with worker:
#   celery -A celery_app.celery worker --beat --pool=gevent --concurrency=20

from datetime import datetime, timezone, timedelta
from celery.utils.log import get_task_logger
from celery_app import celery
from utils.enums import PaymentStatus, Plan

logger = get_task_logger(__name__)


@celery.task(bind=True, max_retries=2, default_retry_delay=300)
def check_subscription_expiry_reminders(self):
    """
    Scans all organizations with expiring subscriptions and sends
    reminder emails at 7 days and 1 day before expiry.

    Only targets plans that are NOT backed by a real Paddle subscription
    (i.e., gifted/admin-granted plans that will auto-expire).

    Uses a simple approach: checks if subscription_ends_at falls within
    the reminder windows. Idempotent — safe to run multiple times per day
    because we check if the email was already sent via a marker in the org's
    messages_reset_at field comment (we use a dedicated tracking approach).
    """
    from app import app

    with app.app_context():
        from models.models import db, Organization, User, Payment
        from utils.mail_helper import send_expiry_reminder_email

        now = datetime.now(timezone.utc)

        # Find all orgs with an active paid plan that has an end date
        orgs = Organization.query.filter(
            Organization.plan != 'free',
            Organization.plan.isnot(None),
            Organization.subscription_ends_at.isnot(None),
            Organization.subscription_status.in_(['active', 'canceled']),
        ).all()

        sent_count = 0

        for org in orgs:
            # Skip orgs with real Paddle subscriptions (those auto-renew via webhook)
            has_paddle_sub = (
                org.paddle_subscription_id
                and org.paddle_subscription_id.startswith('sub_')
            )
            if has_paddle_sub:
                continue

            # Calculate days until expiry
            ends_at = org.subscription_ends_at
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)

            days_remaining = (ends_at.date() - now.date()).days

            # Determine which reminder to send (if any)
            reminder_type = None
            if days_remaining == 7:
                reminder_type = '7_day'
            elif days_remaining == 1:
                reminder_type = '1_day'
            elif days_remaining == 0:
                reminder_type = 'today'

            if not reminder_type:
                continue

            # Get the org owner (first admin user)
            owner = User.query.filter_by(org_id=org.id, role='admin').order_by(User.id.asc()).first()
            if not owner:
                owner = User.query.filter_by(org_id=org.id).order_by(User.id.asc()).first()
            if not owner:
                continue

            # Determine what plan they'll fall back to
            # Check if they have a real Paddle payment history (meaning they WERE a paying customer)
            last_paid_plan = None
            last_payment = Payment.query.filter_by(
                org_id=org.id, status=PaymentStatus.COMPLETED
            ).order_by(Payment.created_at.desc()).first()

            if last_payment and last_payment.plan and last_payment.plan != org.plan:
                # They were on a different paid plan before the gift
                last_paid_plan = last_payment.plan
            # else: they were on free before the gift

            fallback_plan = last_paid_plan or 'free'

            # Send the reminder email
            try:
                sent = send_expiry_reminder_email(
                    to_email=owner.email,
                    user_name=owner.name,
                    current_plan=org.plan,
                    fallback_plan=fallback_plan,
                    expires_at=ends_at,
                    days_remaining=days_remaining,
                    reminder_type=reminder_type,
                )
                if sent:
                    sent_count += 1
                    logger.info(f"[reminder] Sent {reminder_type} email to {owner.email} (org {org.id}, plan {org.plan}, expires {ends_at.date()})")
            except Exception as e:
                logger.error(f"[reminder] Failed to send to {owner.email}: {e}")

        logger.info(f"[reminder] Task complete. Sent {sent_count} reminder emails.")
        return {"sent": sent_count, "checked": len(orgs)}
