from flask import Blueprint, request, jsonify, session, current_app
from models.models import db, Organization, User, Payment
from utils.mail_helper import send_payment_receipt, send_sale_notification
import hmac
import hashlib
import os

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


def verify_paddle_signature(request_body, signature, secret):
    """Verify Paddle webhook signature (HMAC-SHA256)."""
    if not secret:
        return True  # Skip verification in dev if no secret set
    computed = hmac.new(secret.encode(), request_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


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
    # Verify signature in production (only enforced when a secret is set)
    signature = request.headers.get('Paddle-Signature', '')
    if PADDLE_WEBHOOK_SECRET and not verify_paddle_signature(request.get_data(), signature, PADDLE_WEBHOOK_SECRET):
        return jsonify({"error": "Invalid signature"}), 401

    data = request.json or {}
    event_type = data.get('event_type', '')
    payload = data.get('data', {})
    price_plan_map = get_price_plan_map()

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

    elif event_type in ('subscription.canceled', 'subscription.paused'):
        org = _resolve_org(payload)
        if org:
            org.plan = 'free'
            org.paddle_subscription_id = None
            db.session.commit()

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

        # Fire off notification emails (failures are logged, never block the webhook)
        try:
            if customer_email:
                send_payment_receipt(customer_email, plan, amount, currency, transaction_id)
            send_sale_notification(
                plan, amount, currency,
                org_name=org.name if org else None,
                customer_email=customer_email,
                transaction_id=transaction_id,
            )
        except Exception as e:
            print(f"[paddle_webhook] email send failed: {e}")

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
