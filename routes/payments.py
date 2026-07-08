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
    """Verify Paddle webhook signature using HMAC-SHA256."""
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
        computed = hmac.HMAC(secret.encode('utf-8'), signed_payload.encode('utf-8'), hashlib.sha256).hexdigest()
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
    
    # --- SECURITY: Reject invalid signatures in production ---
    if PADDLE_WEBHOOK_SECRET:
        if not verify_paddle_signature(raw_body, signature, PADDLE_WEBHOOK_SECRET):
            print(f"[paddle_webhook] SIGNATURE FAILED. Header: {signature[:80]}")
            return jsonify({"error": "Invalid signature"}), 403

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

    elif event_type == 'subscription.resumed':
        # Reactivation — restore the plan from the subscription items
        subscription_id = payload.get('id', '')
        customer_id = payload.get('customer_id', '')
        items = payload.get('items', [])
        price_id = items[0].get('price', {}).get('id', '') if items else ''
        plan = price_plan_map.get(price_id, 'free')
        org = _resolve_org(payload)
        if org:
            org.plan = plan
            org.paddle_subscription_id = subscription_id
            if customer_id:
                org.paddle_customer_id = customer_id
            db.session.commit()
            print(f"[paddle_webhook] org {org.id} reactivated to plan={plan}")

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
    """Comprehensive subscription management page."""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    from utils.plan_limits import PLAN_LIMITS, get_usage_summary
    from models.models import Bot

    org = Organization.query.get(session.get('org_id'))
    plan = (org.plan if org else 'free') or 'free'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])
    
    # Usage metrics
    usage = get_usage_summary(session.get('org_id'))
    
    messages_used = usage['messages_used'] if usage else 0
    messages_limit = usage['messages_limit'] if usage else 200
    bots_used = usage['bots_used'] if usage else 0
    bots_limit = usage['bots_limit'] if usage else 1
    members_used = usage['members_used'] if usage else 1
    members_limit = usage['members_limit'] if usage else 1
    usage_percent = usage['messages_percent'] if usage else 0
    reset_date = usage['reset_date'] if usage else 'Next billing cycle'
    
    # Payment history
    payments = Payment.query.filter_by(org_id=org.id if org else 0).order_by(Payment.created_at.desc()).all()
    total_spent = sum(p.amount or 0 for p in payments if p.status == 'completed')

    # Subscription status
    has_active_subscription = bool(org and org.paddle_subscription_id)
    is_paddle_customer = bool(org and org.paddle_customer_id and org.paddle_customer_id.startswith('ctm_'))

    return render_template('manage_plan.html',
        plan=plan, plan_name=plan.capitalize(),
        messages_used=messages_used, messages_limit=messages_limit,
        bots_used=bots_used, bots_limit=bots_limit,
        members_used=members_used, members_limit=members_limit,
        usage_percent=usage_percent, reset_date=reset_date,
        subscription_id=org.paddle_subscription_id if org else None,
        customer_id=org.paddle_customer_id if org else None,
        has_active_subscription=has_active_subscription,
        is_paddle_customer=is_paddle_customer,
        total_spent=total_spent, payments=payments,
        all_plans=PLAN_LIMITS,
        usage=usage)


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
    """
    Generate a Paddle transaction for updating payment method,
    or redirect to customer portal for payment management.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    customer_id = org.paddle_customer_id
    if not customer_id or not customer_id.startswith('ctm_'):
        return jsonify({"error": "No Paddle customer linked. Complete a purchase first."}), 400

    # Use customer portal for payment method update (most reliable approach)
    try:
        url = f"{_paddle_api_base()}/customers/{customer_id}/portal-sessions"
        body = {}
        if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
            body['subscription_ids'] = [org.paddle_subscription_id]

        resp = http_requests.post(url, headers=_paddle_headers(), json=body)
        if resp.status_code in (200, 201):
            data = resp.json().get('data', {})
            # Try to get the update payment method URL specifically
            portal_url = data.get('urls', {}).get('subscription', {}).get('update_payment_method', '')
            if not portal_url:
                portal_url = data.get('urls', {}).get('general', {}).get('overview', '')
            if not portal_url:
                portal_url = data.get('url', '')
            if portal_url:
                return jsonify({"success": True, "url": portal_url}), 200
            else:
                return jsonify({"error": "Payment update URL not returned by Paddle."}), 500
        else:
            error_msg = resp.json().get('error', {}).get('detail', resp.text[:200])
            return jsonify({"error": f"Paddle error: {error_msg}"}), 500
    except Exception as e:
        print(f"[update_payment_method] exception: {e}")
        return jsonify({"error": "Failed to reach Paddle. Please try again."}), 500


@payments_bp.route('/upgrade-plan', methods=['POST'])
def upgrade_plan():
    """
    Upgrade or downgrade an existing subscription via Paddle API.
    Changes the price_id on the subscription to the new plan's price.
    For new subscribers (no existing sub), returns info for frontend checkout.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    data = request.json or {}
    target_plan = data.get('plan', '').lower()
    
    if target_plan not in ('starter', 'growth', 'pro'):
        return jsonify({"error": "Invalid plan. Choose starter, growth, or pro."}), 400

    # Get the price ID for the target plan
    cfg = current_app.config
    price_map = {
        'starter': cfg.get('PADDLE_PRICE_STARTER'),
        'growth': cfg.get('PADDLE_PRICE_GROWTH'),
        'pro': cfg.get('PADDLE_PRICE_PRO'),
    }
    target_price_id = price_map.get(target_plan)
    if not target_price_id:
        return jsonify({"error": f"Price ID not configured for {target_plan} plan."}), 500

    # If org already has an active subscription, update it via Paddle API
    if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
        try:
            url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}"
            body = {
                "items": [{"price_id": target_price_id, "quantity": 1}],
                "proration_billing_mode": "prorated_immediately"
            }
            resp = http_requests.patch(url, headers=_paddle_headers(), json=body)
            
            if resp.status_code in (200, 201):
                # Paddle will fire subscription.updated webhook to confirm
                # Optimistically update locally for immediate UI feedback
                org.plan = target_plan
                db.session.commit()
                return jsonify({
                    "success": True, 
                    "message": f"Plan upgraded to {target_plan.capitalize()}! Changes take effect immediately.",
                    "method": "subscription_update"
                }), 200
            else:
                error_detail = resp.json().get('error', {}).get('detail', resp.text[:300])
                print(f"[upgrade_plan] Paddle API error: {resp.status_code} {error_detail}")
                return jsonify({"error": f"Paddle error: {error_detail}"}), 500
        except Exception as e:
            print(f"[upgrade_plan] exception: {e}")
            return jsonify({"error": "Failed to reach Paddle. Please try again."}), 500
    else:
        # No existing subscription — frontend should initiate a new checkout
        # Return the info needed for Paddle.js checkout
        user = User.query.get(session['user_id'])
        if not org.paddle_customer_id:
            org.paddle_customer_id = f"org_{org.id}"
            db.session.commit()
        
        session['checkout_plan'] = target_plan
        return jsonify({
            "success": True,
            "method": "new_checkout",
            "customer_id": org.paddle_customer_id,
            "org_id": org.id,
            "email": user.email if user else '',
            "price_id": target_price_id,
            "plan": target_plan
        }), 200


@payments_bp.route('/reactivate-plan', methods=['POST'])
def reactivate_plan():
    """
    Reactivate a cancelled (but not yet expired) subscription via Paddle API.
    This reverses a scheduled cancellation.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    # Must have a subscription ID to reactivate
    if not org.paddle_subscription_id or not org.paddle_subscription_id.startswith('sub_'):
        return jsonify({"error": "No subscription found to reactivate. Please subscribe to a new plan."}), 400

    try:
        # First, get current subscription status from Paddle
        get_url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}"
        get_resp = http_requests.get(get_url, headers=_paddle_headers())
        
        if get_resp.status_code not in (200, 201):
            return jsonify({"error": "Could not retrieve subscription details from Paddle."}), 500
        
        sub_data = get_resp.json().get('data', {})
        sub_status = sub_data.get('status', '')
        scheduled_change = sub_data.get('scheduled_change', None)
        
        # If subscription is cancelled but still active (scheduled to cancel at period end)
        if sub_status == 'active' and scheduled_change and scheduled_change.get('action') == 'cancel':
            # Remove the scheduled cancellation
            url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}"
            body = {"scheduled_change": None}
            resp = http_requests.patch(url, headers=_paddle_headers(), json=body)
            
            if resp.status_code in (200, 201):
                # Restore plan locally
                items = sub_data.get('items', [])
                if items:
                    price_id = items[0].get('price', {}).get('id', '')
                    price_plan_map = get_price_plan_map()
                    plan = price_plan_map.get(price_id, org.plan or 'free')
                    org.plan = plan
                    db.session.commit()
                
                return jsonify({
                    "success": True, 
                    "message": "Subscription reactivated! Your plan will continue as normal."
                }), 200
            else:
                error_detail = resp.json().get('error', {}).get('detail', resp.text[:200])
                return jsonify({"error": f"Paddle error: {error_detail}"}), 500
        
        elif sub_status == 'canceled':
            # Fully cancelled — they need a new checkout
            return jsonify({
                "error": "This subscription has already expired. Please subscribe to a new plan.",
                "action_required": "new_checkout"
            }), 400
        
        elif sub_status == 'paused':
            # Resume a paused subscription
            url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}/resume"
            body = {"effective_from": "immediately"}
            resp = http_requests.post(url, headers=_paddle_headers(), json=body)
            
            if resp.status_code in (200, 201):
                items = sub_data.get('items', [])
                if items:
                    price_id = items[0].get('price', {}).get('id', '')
                    price_plan_map = get_price_plan_map()
                    plan = price_plan_map.get(price_id, org.plan or 'free')
                    org.plan = plan
                    db.session.commit()
                
                return jsonify({
                    "success": True, 
                    "message": "Subscription resumed! Your plan is active again."
                }), 200
            else:
                error_detail = resp.json().get('error', {}).get('detail', resp.text[:200])
                return jsonify({"error": f"Paddle error: {error_detail}"}), 500
        
        else:
            # Already active with no scheduled cancellation
            return jsonify({"error": "Your subscription is already active. No reactivation needed."}), 400

    except Exception as e:
        print(f"[reactivate_plan] exception: {e}")
        return jsonify({"error": "Failed to reach Paddle. Please try again."}), 500


@payments_bp.route('/subscription-status', methods=['GET'])
def subscription_status():
    """
    Returns current subscription status from Paddle (live data).
    Used by frontend to show real-time subscription state.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    result = {
        "plan": org.plan or 'free',
        "plan_name": (org.plan or 'free').capitalize(),
        "subscription_id": org.paddle_subscription_id,
        "customer_id": org.paddle_customer_id,
        "has_subscription": bool(org.paddle_subscription_id),
        "paddle_status": None,
        "next_billing": None,
        "scheduled_change": None,
    }

    # If there's a real Paddle subscription, fetch live details
    if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
        try:
            url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}"
            resp = http_requests.get(url, headers=_paddle_headers())
            if resp.status_code in (200, 201):
                sub_data = resp.json().get('data', {})
                result['paddle_status'] = sub_data.get('status', 'unknown')
                result['next_billing'] = sub_data.get('next_billed_at', None)
                result['scheduled_change'] = sub_data.get('scheduled_change', None)
        except Exception as e:
            print(f"[subscription_status] Paddle API error: {e}")

    return jsonify(result), 200


@payments_bp.route('/test-webhook', methods=['GET'])
def test_webhook_reachable():
    return jsonify({"status": "ok", "message": "Paddle webhook endpoint is reachable"}), 200
