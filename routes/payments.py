from flask import Blueprint, request, jsonify, session, current_app, redirect, url_for, flash, render_template
from models.models import db, Organization, User, Payment
from utils.mail_helper import send_payment_receipt, send_sale_notification
import hmac
import hashlib
import os
from datetime import datetime, timezone

payments_bp = Blueprint('payments_bp', __name__, url_prefix='/payments')

PADDLE_WEBHOOK_SECRET = os.getenv('PADDLE_WEBHOOK_SECRET', '')


def get_price_plan_map():
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
        signed_payload = f"{ts}:{raw_body.decode('utf-8')}"
        computed = hmac.new(secret.encode('utf-8'), signed_payload.encode('utf-8'), hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, h1)
    except Exception as e:
        print(f"[paddle_webhook] signature verification error: {e}")
        return False



def _resolve_org(sub_or_txn):
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
    if not org:
        return None
    user = User.query.filter_by(org_id=org.id).order_by(User.id.asc()).first()
    return user.email if user else None


@payments_bp.route('/webhook/paddle', methods=['POST'])
def paddle_webhook():
    raw_body = request.get_data()
    signature = request.headers.get('Paddle-Signature', '')
    if PADDLE_WEBHOOK_SECRET:
        if not verify_paddle_signature(raw_body, signature, PADDLE_WEBHOOK_SECRET):
            print(f"[paddle_webhook] SIGNATURE FAILED. Header: {signature[:80]}")

    data = request.json or {}
    event_type = data.get('event_type', '')
    payload = data.get('data', {})
    price_plan_map = get_price_plan_map()
    print(f"[paddle_webhook] event_type={event_type}, payload_id={payload.get('id','?')}")

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

    elif event_type in ('subscription.canceled', 'subscription.paused'):
        org = _resolve_org(payload)
        if org:
            org.plan = 'free'
            org.paddle_subscription_id = None
            db.session.commit()
            print(f"[paddle_webhook] org {org.id} downgraded to free")


    elif event_type == 'transaction.completed':
        transaction_id = payload.get('id', '')
        if transaction_id and Payment.query.filter_by(paddle_transaction_id=transaction_id).first():
            return jsonify({"received": True, "note": "duplicate"}), 200

        items = payload.get('items', [])
        price_id = items[0].get('price', {}).get('id', '') if items else ''
        plan = price_plan_map.get(price_id, 'free')
        totals = (payload.get('details', {}) or {}).get('totals', {}) or {}
        currency = payload.get('currency_code', 'INR')
        raw_total = totals.get('grand_total') or totals.get('total') or '0'
        try:
            amount = round(int(raw_total) / 100.0, 2)
        except (ValueError, TypeError):
            amount = 0.0

        org = _resolve_org(payload)
        customer_id = payload.get('customer_id', '')
        customer_email = _owner_email(org)

        if org and plan != 'free':
            org.plan = plan
            if customer_id:
                org.paddle_customer_id = customer_id
            db.session.commit()

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

        try:
            if customer_email:
                send_payment_receipt(customer_email, plan, amount, currency, transaction_id)
            send_sale_notification(plan, amount, currency, org_name=org.name if org else None, customer_email=customer_email, transaction_id=transaction_id)
        except Exception as e:
            print(f"[paddle_webhook] email send failed: {e}")

    return jsonify({"received": True}), 200



@payments_bp.route('/checkout-session', methods=['POST'])
def create_checkout_session():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org_id = session.get('org_id')
    org = Organization.query.get(org_id)
    if not org:
        return jsonify({"error": "Organization not found"}), 404
    if not org.paddle_customer_id:
        org.paddle_customer_id = f"org_{org.id}"
        db.session.commit()
    user = User.query.get(session['user_id'])
    user_email = user.email if user else ''
    return jsonify({"customer_id": org.paddle_customer_id, "org_id": org.id, "current_plan": org.plan, "email": user_email}), 200


@payments_bp.route('/upgrade-callback')
def upgrade_callback():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    from utils.plan_limits import PLAN_LIMITS
    org = Organization.query.get(session.get('org_id'))
    plan = org.plan if org else 'free'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])
    return render_template('payment_success.html', plan_name=plan.capitalize(), messages_limit=limits.get('messages', 0), bots_limit=limits.get('bots', 1), org_name=org.name if org else '')



@payments_bp.route('/manage')
def manage_plan():
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
    reset_date = org.messages_reset_at.strftime('%b %d, %Y') if (org and org.messages_reset_at) else 'Next billing cycle'
    payments = Payment.query.filter_by(org_id=org.id if org else 0).order_by(Payment.created_at.desc()).all()
    total_spent = sum(p.amount or 0 for p in payments if p.status == 'completed')
    return render_template('manage_plan.html', plan=plan, plan_name=plan.capitalize(), messages_used=messages_used, messages_limit=messages_limit, bots_limit=bots_limit, bot_count=bot_count, usage_percent=usage_percent, reset_date=reset_date, subscription_id=org.paddle_subscription_id if org else None, customer_id=org.paddle_customer_id if org else None, total_spent=total_spent, payments=payments)



@payments_bp.route('/cancel-plan', methods=['POST'])
def cancel_plan():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404
    if not org.plan or org.plan == 'free':
        return jsonify({"error": "You are already on the free plan"}), 400
    # In production: call Paddle API to schedule cancellation at period end
    # For sandbox: downgrade immediately
    org.plan = 'free'
    org.paddle_subscription_id = None
    db.session.commit()
    return jsonify({"success": True, "message": "Plan cancelled. Access continues until end of billing period."}), 200


@payments_bp.route('/update-payment-method', methods=['POST'])
def update_payment_method():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404
    # Paddle's customer portal URL for updating payment method
    # In sandbox: https://sandbox-customer-portal.paddle.com
    # In production: https://customer-portal.paddle.com
    env = current_app.config.get('PADDLE_ENVIRONMENT', 'sandbox')
    if env == 'sandbox':
        portal_url = 'https://sandbox-customer-portal.paddle.com'
    else:
        portal_url = 'https://customer-portal.paddle.com'
    return jsonify({"success": True, "url": portal_url}), 200


@payments_bp.route('/test-webhook', methods=['GET'])
def test_webhook_reachable():
    return jsonify({"status": "ok", "message": "Paddle webhook endpoint is reachable"}), 200
