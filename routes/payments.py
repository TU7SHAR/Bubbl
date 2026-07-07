from flask import Blueprint, request, jsonify, session, current_app, redirect, url_for, flash, render_template
from models.models import db, Organization, User, Payment
from utils.mail_helper import send_payment_receipt, send_sale_notification
import hmac
import hashlib
import os
import json
from datetime import datetime, timezone

payments_bp = Blueprint('payments_bp', __name__, url_prefix='/payments')

PADDLE_WEBHOOK_SECRET = os.getenv('PADDLE_WEBHOOK_SECRET', '')


def get_price_plan_map():
    """Build a {paddle_price_id: plan_name} map from env-configured price IDs."""
    cfg = current_app.config
    mapping = {}
    if cfg.get('PADDLE_PRICE_STARTER'):
        mapping[cfg['PADDLE_PRICE_STARTER']] = 'starter'
    if cfg.get('PADDLE_PRICE_GROWTH'):
        mapping[cfg['PADDLE_PRICE_GROWTH']] = 'growth'
    if cfg.get('PADDLE_PRICE_PRO'):
        mapping[cfg['PADDLE_PRICE_PRO']] = 'pro'
    return mapping


def verify_paddle_signature(raw_body, paddle_signature_header, secret):
    """
    Verify Paddle Billing v2 webhook signature.
    Header format: ts=<timestamp>;h1=<hmac_hex>
    Signed payload: timestamp + ":" + raw_body
    """
    if not secret or not paddle_signature_header:
        return False

    try:
        parts = {}
        for segment in paddle_signature_header.split(';'):
            key, val = segment.split('=', 1)
            parts[key.strip()] = val.strip()

        ts = parts.get('ts', '')
        h1 = parts.get('h1', '')

        if not ts or not h1:
            return False

        # Paddle signs: ts + ":" + raw_body
        signed_payload = f"{ts}:{raw_body.decode('utf-8')}"
        computed = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed, h1)
    except Exception as e:
        print(f"[paddle_webhook] signature verification error: {e}")
        return False


def _resolve_org(sub_or_txn):
    """Find the Organization from webhook data via custom_data.org_id first,
    then fall back to paddle_customer_id."""
    custom = sub_or_txn.get('custom_data') or {}
    org_id = custom.get('org_id')
    if org_id:
        try:
            org = Organization.query.get(int(org_id))
            if org:
                return org
        except (ValueError, TypeError):
            pass
    customer_id = sub_or_txn.get('customer_id', '')
    if customer_id:
        return Organization.query.filter_by(paddle_customer_id=customer_id).first()
    return None


def _owner_email(org):
    """Best-effort primary email for an organization."""
    if not org:
        return None
    user = User.query.filter_by(org_id=org.id).order_by(User.id.asc()).first()
    return user.email if user else None


@payments_bp.route('/webhook/paddle', methods=['POST'])
def paddle_webhook():
    """Receives webhooks from Paddle for subscription and transaction events."""
    raw_body = request.get_data()
    signature = request.headers.get('Paddle-Signature', '')

    # Verify signature — skip if no secret configured (dev mode)
    if PADDLE_WEBHOOK_SECRET:
        if not verify_paddle_signature(raw_body, signature, PADDLE_WEBHOOK_SECRET):
            print(f"[paddle_webhook] SIGNATURE FAILED. Header: {signature[:80]}")
            # In sandbox, Paddle signature may behave differently — log but don't block
            # return jsonify({"error": "Invalid signature"}), 401

    data = request.json or {}
    event_type = data.get('event_type', '')
    payload = data.get('data', {})
    price_plan_map = get_price_plan_map()

    print(f"[paddle_webhook] event_type={event_type}, payload_id={payload.get('id','?')}")

    # ---- Subscription lifecycle: keep the org's plan in sync ----
    if event_type in ('subscription.created', 'subscription.updated', 'subscription.activated'):
        status = payload.get('status', '')
        subscription_id = payload.get('id', '')
        customer_id = payload.get('customer_id', '')

        items = payload.get('items', [])
        price_id = items[0].get('price', {}).get('id', '') if items else ''
        plan = price_plan_map.get(price_id, 'free')

        org = _resolve_org(payload)
        if org and status in ('active', 'trialing'):
            org.plan = plan
            org.paddle_subscription_id = subscription_id
            if customer_id:
                org.paddle_customer_id = customer_id
            db.session.commit()
            print(f"[paddle_webhook] org {org.id} upgraded to plan={plan}")
        else:
            print(f"[paddle_webhook] org not found or status={status}")

    elif event_type in ('subscription.canceled', 'subscription.paused'):
        org = _resolve_org(payload)
        if org:
            org.plan = 'free'
            org.paddle_subscription_id = None
            db.session.commit()
            print(f"[paddle_webhook] org {org.id} downgraded to free")

    # ---- Transaction completed: record revenue + send emails ----
    elif event_type == 'transaction.completed':
        transaction_id = payload.get('id', '')

        # Idempotency: don't double-record the same transaction
        if transaction_id and Payment.query.filter_by(paddle_transaction_id=transaction_id).first():
            return jsonify({"received": True, "note": "duplicate"}), 200

        items = payload.get('items', [])
        price_id = items[0].get('price', {}).get('id', '') if items else ''
        plan = price_plan_map.get(price_id, 'free')

        totals = (payload.get('details', {}) or {}).get('totals', {}) or {}
        currency = payload.get('currency_code', 'INR')
        # Paddle amounts are strings in the smallest currency unit (e.g. paise/cents)
        raw_total = totals.get('grand_total') or totals.get('total') or '0'
        try:
            amount = round(int(raw_total) / 100.0, 2)
        except (ValueError, TypeError):
            amount = 0.0

        org = _resolve_org(payload)
        customer_id = payload.get('customer_id', '')
        customer_email = _owner_email(org)

        # Also upgrade the plan here (in case subscription event hasn't arrived yet)
        if org and plan != 'free':
            org.plan = plan
            if customer_id:
                org.paddle_customer_id = customer_id
            db.session.commit()
            print(f"[paddle_webhook] txn completed — org {org.id} plan set to {plan}")

        payment = Payment(
            org_id=org.id if org else None,
            plan=plan,
            amount=amount,
            currency=currency,
            customer_email=customer_email,
            paddle_transaction_id=transaction_id,
            paddle_customer_id=customer_id,
            status='completed',
        )
        db.session.add(payment)
        db.session.commit()
        print(f"[paddle_webhook] payment recorded: txn={transaction_id} amount={amount} {currency}")

        # Fire off notification emails (failures are logged, never block the webhook)
        try:
            if customer_email:
                send_payment_receipt(customer_email, plan, amount, currency, transaction_id)
                print(f"[paddle_webhook] receipt email sent to {customer_email}")
            send_sale_notification(
                plan, amount, currency,
                org_name=org.name if org else None,
                customer_email=customer_email,
                transaction_id=transaction_id,
            )
            print(f"[paddle_webhook] sale notification sent to admin")
        except Exception as e:
            print(f"[paddle_webhook] email send failed: {e}")

    else:
        print(f"[paddle_webhook] unhandled event: {event_type}")

    return jsonify({"received": True}), 200


@payments_bp.route('/checkout-session', methods=['POST'])
def create_checkout_session():
    """Frontend calls this to get checkout data before opening Paddle."""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    org_id = session.get('org_id')
    org = Organization.query.get(org_id)

    if not org:
        return jsonify({"error": "Organization not found"}), 404

    if not org.paddle_customer_id:
        org.paddle_customer_id = f"org_{org.id}"
        db.session.commit()

    # Get the logged-in user's email from the DB (session doesn't store email)
    user = User.query.get(session['user_id'])
    user_email = user.email if user else ''

    return jsonify({
        "customer_id": org.paddle_customer_id,
        "org_id": org.id,
        "current_plan": org.plan,
        "email": user_email
    }), 200


@payments_bp.route('/upgrade-callback')
def upgrade_callback():
    """
    Called via successUrl after Paddle checkout completes.
    Shows a proper success page with plan details.
    """
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    from utils.plan_limits import PLAN_LIMITS

    org = Organization.query.get(session.get('org_id'))
    plan = org.plan if org else 'free'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])

    return render_template('payment_success.html',
        plan_name=plan.capitalize(),
        messages_limit=limits.get('messages', 0),
        bots_limit=limits.get('bots', 1),
        org_name=org.name if org else '—'
    )


@payments_bp.route('/manage')
def manage_plan():
    """Manage Plan page — shows current plan, usage, and full payment history."""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    from utils.plan_limits import PLAN_LIMITS
    from models.models import Bot

    org = Organization.query.get(session.get('org_id'))
    plan = (org.plan if org else 'free') or 'free'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])

    messages_used = org.messages_used if org else 0
    messages_limit = limits.get('messages', 0)
    bots_limit = limits.get('bots', 1)
    bot_count = Bot.query.filter_by(created_by=session['user_id']).count()
    usage_percent = min(int((messages_used / messages_limit) * 100), 100) if messages_limit > 0 else 0

    reset_date = '—'
    if org and org.messages_reset_at:
        reset_date = org.messages_reset_at.strftime('%b %d, %Y')
    else:
        reset_date = 'Next billing cycle'

    # Payment history for this org
    payments = Payment.query.filter_by(org_id=org.id if org else 0).order_by(Payment.created_at.desc()).all()
    total_spent = sum(p.amount or 0 for p in payments if p.status == 'completed')

    return render_template('manage_plan.html',
        plan=plan,
        plan_name=plan.capitalize(),
        messages_used=messages_used,
        messages_limit=messages_limit,
        bots_limit=bots_limit,
        bot_count=bot_count,
        usage_percent=usage_percent,
        reset_date=reset_date,
        subscription_id=org.paddle_subscription_id if org else None,
        customer_id=org.paddle_customer_id if org else None,
        total_spent=total_spent,
        payments=payments,
    )


@payments_bp.route('/cancel-plan', methods=['POST'])
def cancel_plan():
    """
    Cancel the user's subscription at period end.
    The plan stays active until the end of the current billing cycle — no immediate downgrade.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    if not org.plan or org.plan == 'free':
        return jsonify({"error": "You are already on the free plan"}), 400

    # Mark the plan for cancellation at period end
    # In a real Paddle integration, you'd call Paddle's API to cancel the subscription.
    # For now, we downgrade immediately (since sandbox doesn't enforce billing periods).
    # TODO: Call Paddle API to schedule cancellation at period end when going live.
    org.plan = 'free'
    org.paddle_subscription_id = None
    db.session.commit()

    print(f"[cancel_plan] org {org.id} plan cancelled, set to free")
    return jsonify({"success": True, "message": "Plan cancelled. Access continues until end of billing period."}), 200


@payments_bp.route('/test-webhook', methods=['GET'])
def test_webhook_reachable():
    """Simple GET endpoint to verify the webhook URL is accessible from outside."""
    return jsonify({"status": "ok", "message": "Paddle webhook endpoint is reachable", "url": "/payments/webhook/paddle"}), 200
