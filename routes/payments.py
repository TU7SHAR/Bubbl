from flask import Blueprint, request, jsonify, session, current_app, redirect, url_for, flash, render_template
from models.models import db, Organization, User, Payment
from utils.mail_helper import send_payment_receipt, send_sale_notification
import hmac
import hashlib
import os
import requests as http_requests
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


def _paddle_api_base():
    env = current_app.config.get('PADDLE_ENVIRONMENT', 'sandbox')
    if env == 'sandbox':
        return 'https://sandbox-api.paddle.com'
    return 'https://api.paddle.com'


def _paddle_headers():
    api_key = current_app.config.get('PADDLE_API_KEY', '')
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }


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


# ═══════════════════════════════════════════
# WEBHOOK
# ═══════════════════════════════════════════

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
            plan=plan, amount=amount, currency=currency,
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


# ═══════════════════════════════════════════
# CHECKOUT + SUCCESS
# ═══════════════════════════════════════════

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
    # Store the plan being purchased in session for the success page
    plan_being_bought = request.json.get('plan', '') if request.json else ''
    if plan_being_bought:
        session['checkout_plan'] = plan_being_bought
    return jsonify({"customer_id": org.paddle_customer_id, "org_id": org.id, "current_plan": org.plan, "email": user_email}), 200


@payments_bp.route('/upgrade-callback')
def upgrade_callback():
    """Success page after Paddle checkout. Shows the plan they just bought."""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    from utils.plan_limits import PLAN_LIMITS

    org = Organization.query.get(session.get('org_id'))

    # The webhook might not have arrived yet, so org.plan could still be 'free'.
    # Try to get the plan from:
    # 1. The org (webhook already fired)
    # 2. The session checkout_plan (set during checkout-session)
    # 3. Query params (fallback)
    plan = org.plan if (org and org.plan and org.plan != 'free') else None
    if not plan:
        plan = session.pop('checkout_plan', None)
    if not plan:
        plan = request.args.get('plan', '')
    if not plan:
        plan = 'free'

    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])

    return render_template('payment_success.html',
        plan_name=plan.capitalize(),
        messages_limit=limits.get('messages', 0),
        bots_limit=limits.get('bots', 1),
        org_name=org.name if org else ''
    )


# ═══════════════════════════════════════════
# MANAGE PLAN
# ═══════════════════════════════════════════

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

    return render_template('manage_plan.html',
        plan=plan, plan_name=plan.capitalize(),
        messages_used=messages_used, messages_limit=messages_limit,
        bots_limit=bots_limit, bot_count=bot_count,
        usage_percent=usage_percent, reset_date=reset_date,
        subscription_id=org.paddle_subscription_id if org else None,
        customer_id=org.paddle_customer_id if org else None,
        total_spent=total_spent, payments=payments)


# ═══════════════════════════════════════════
# CANCEL / PAYMENT METHOD / PORTAL
# ═══════════════════════════════════════════

@payments_bp.route('/cancel-plan', methods=['POST'])
def cancel_plan():
    """Cancel subscription via Paddle API (effective at period end), fallback to local."""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404
    if not org.plan or org.plan == 'free':
        return jsonify({"error": "You are already on the free plan"}), 400

    # Try to cancel via Paddle API (effective_from = next_billing_period)
    if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
        try:
            url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}/cancel"
            resp = http_requests.post(url, headers=_paddle_headers(), json={"effective_from": "next_billing_period"})
            if resp.status_code in (200, 201):
                print(f"[cancel_plan] Paddle API cancelled sub {org.paddle_subscription_id}")
                # Don't downgrade immediately — Paddle will send subscription.canceled webhook at period end
                return jsonify({"success": True, "message": "Plan will be cancelled at end of billing period. You retain full access until then."}), 200
            else:
                print(f"[cancel_plan] Paddle API error: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[cancel_plan] Paddle API exception: {e}")

    # Fallback: downgrade locally (sandbox / no real sub)
    org.plan = 'free'
    org.paddle_subscription_id = None
    db.session.commit()
    return jsonify({"success": True, "message": "Plan cancelled. Access continues until end of billing period."}), 200


@payments_bp.route('/customer-portal', methods=['POST'])
def customer_portal():
    """
    Generate a Paddle customer portal session URL.
    This gives the user a link to update payment method, cancel, or reactivate subscriptions.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    customer_id = org.paddle_customer_id
    if not customer_id or not customer_id.startswith('ctm_'):
        return jsonify({"error": "No Paddle customer linked to your account yet. Complete a purchase first."}), 400

    # Call Paddle API: POST /customers/{customer_id}/portal-sessions
    try:
        url = f"{_paddle_api_base()}/customers/{customer_id}/portal-sessions"
        # You can pass subscription_ids to deep-link to a specific subscription
        body = {}
        if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
            body['subscription_ids'] = [org.paddle_subscription_id]

        resp = http_requests.post(url, headers=_paddle_headers(), json=body)
        if resp.status_code in (200, 201):
            data = resp.json().get('data', {})
            portal_url = data.get('urls', {}).get('general', {}).get('overview', '')
            if not portal_url:
                # Try top-level url field
                portal_url = data.get('url', '')
            if portal_url:
                return jsonify({"success": True, "url": portal_url}), 200
            else:
                return jsonify({"error": "Portal URL not returned by Paddle."}), 500
        else:
            error_msg = resp.json().get('error', {}).get('detail', resp.text[:200])
            print(f"[customer_portal] Paddle API error: {resp.status_code} {error_msg}")
            return jsonify({"error": f"Paddle error: {error_msg}"}), 500
    except Exception as e:
        print(f"[customer_portal] exception: {e}")
        return jsonify({"error": "Failed to reach Paddle. Please try again."}), 500


@payments_bp.route('/update-payment-method', methods=['POST'])
def update_payment_method():
    """Alias — redirects to customer portal."""
    return customer_portal()


@payments_bp.route('/test-webhook', methods=['GET'])
def test_webhook_reachable():
    return jsonify({"status": "ok", "message": "Paddle webhook endpoint is reachable"}), 200
