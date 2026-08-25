from flask import Blueprint, request, jsonify, session, current_app, redirect, url_for, flash, render_template
from models.models import db, Organization, User, Payment
from utils.mail_helper import send_payment_receipt, send_sale_notification
import hmac
import hashlib
import os
import logging
import requests as http_requests
from datetime import datetime, timezone, timedelta

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


def _parse_paddle_dt(value):
    """Parse a Paddle ISO-8601 datetime string into a timezone-aware datetime."""
    if not value:
        return None
    try:
        # Paddle uses e.g. "2026-07-08T12:36:04.864538Z"
        cleaned = value.replace('Z', '+00:00')
        return datetime.fromisoformat(cleaned)
    except (ValueError, AttributeError):
        return None


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
        logging.error(f"[paddle_webhook] signature verification error: {e}")
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


def _extract_payment_method(payload):
    """
    Pull payment method details out of a Paddle transaction/subscription payload.

    Paddle exposes this under data.payments[].method_details for transactions.
    Returns (method_type, card_brand, card_last4) — any of which may be None.
    """
    method_type = None
    card_brand = None
    card_last4 = None
    try:
        payments = payload.get('payments') or []
        if payments:
            # Use the most recent captured payment
            md = payments[-1].get('method_details') or {}
            method_type = payments[-1].get('type') or md.get('type')
            card = md.get('card') or {}
            if card:
                card_brand = card.get('type') or card.get('brand')
                card_last4 = card.get('last4')
        # Fallback: some payloads store it under payment_method_details
        if not method_type:
            pmd = payload.get('payment_method_details') or {}
            method_type = pmd.get('type')
    except Exception as e:
        logging.warning(f"[paddle_webhook] payment method extract error: {e}")
    return method_type, card_brand, card_last4


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
            logging.error(f"[paddle_webhook] SIGNATURE FAILED. Header: {signature[:80]}")
            return jsonify({"error": "Invalid signature"}), 403

    data = request.json or {}
    event_type = data.get('event_type', '')
    payload = data.get('data', {})
    price_plan_map = get_price_plan_map()
    logging.info(f"[paddle_webhook] event_type={event_type}, payload_id={payload.get('id','?')}")

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
            org.subscription_status = 'active'
            org.paddle_subscription_id = subscription_id
            if customer_id:
                org.paddle_customer_id = customer_id
            # Subscription period dates
            started = _parse_paddle_dt(payload.get('current_billing_period', {}).get('starts_at') or payload.get('started_at'))
            ends = _parse_paddle_dt(payload.get('current_billing_period', {}).get('ends_at') or payload.get('next_billed_at'))
            if started:
                org.subscription_started_at = started
            if ends:
                org.subscription_ends_at = ends
            db.session.commit()
            logging.info(f"[paddle_webhook] org {org.id} upgraded to plan={plan}")

    elif event_type in ('subscription.canceled', 'subscription.paused'):
        org = _resolve_org(payload)
        if org:
            org.plan = 'free'
            org.subscription_status = 'free'
            org.paddle_subscription_id = None
            org.subscription_ends_at = datetime.now(timezone.utc)
            db.session.commit()
            logging.info(f"[paddle_webhook] org {org.id} downgraded to free")

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
            org.subscription_status = 'active'
            org.paddle_subscription_id = subscription_id
            if customer_id:
                org.paddle_customer_id = customer_id
            ends = _parse_paddle_dt(payload.get('current_billing_period', {}).get('ends_at') or payload.get('next_billed_at'))
            if ends:
                org.subscription_ends_at = ends
            db.session.commit()
            logging.info(f"[paddle_webhook] org {org.id} reactivated to plan={plan}")

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

        raw_tax = totals.get('tax') or '0'
        try:
            tax_amount = round(int(raw_tax) / 100.0, 2)
        except (ValueError, TypeError):
            tax_amount = 0.0

        org = _resolve_org(payload)
        customer_id = payload.get('customer_id', '')
        subscription_id = payload.get('subscription_id', '')
        customer_email = _owner_email(org)

        # Payment method snapshot (card brand / last4 / method type)
        method_type, card_brand, card_last4 = _extract_payment_method(payload)

        if org and plan != 'free':
            org.plan = plan
            org.subscription_status = 'active'
            if customer_id:
                org.paddle_customer_id = customer_id
            if subscription_id:
                org.paddle_subscription_id = subscription_id
            if not org.subscription_started_at:
                org.subscription_started_at = datetime.now(timezone.utc)
            # Payment method stored on the Payment record (normalized)
            # No longer duplicated on Organization
            db.session.commit()

        payment = Payment(
            org_id=org.id if org else None,
            plan=plan, amount=amount, currency=currency,
            customer_email=customer_email,
            paddle_transaction_id=transaction_id,
            paddle_customer_id=customer_id,
            paddle_subscription_id=subscription_id or None,
            product_id=price_id or None,
            payment_method=method_type,
            card_brand=card_brand,
            card_last4=card_last4,
            tax_amount=tax_amount,
            status='completed',
        )
        db.session.add(payment)
        db.session.commit()

        try:
            if customer_email:
                send_payment_receipt(customer_email, plan, amount, currency, transaction_id)
            send_sale_notification(plan, amount, currency, org_name=org.name if org else None, customer_email=customer_email, transaction_id=transaction_id)
        except Exception as e:
            logging.error(f"[paddle_webhook] email send failed: {e}")

    elif event_type in ('adjustment.created', 'adjustment.updated'):
        # A refund (or credit) was issued via Paddle — mark the payment refunded.
        action = payload.get('action', '')
        txn_id = payload.get('transaction_id', '')
        if action == 'refund' and txn_id:
            pm = Payment.query.filter_by(paddle_transaction_id=txn_id).first()
            if pm:
                totals = (payload.get('totals', {}) or {})
                raw = totals.get('total') or '0'
                try:
                    refunded = round(int(raw) / 100.0, 2)
                except (ValueError, TypeError):
                    refunded = pm.amount or 0.0
                pm.refund_amount = refunded
                pm.refunded_at = datetime.now(timezone.utc)
                pm.status = 'refunded' if refunded >= (pm.amount or 0) else 'partially_refunded'
                db.session.commit()
                logging.info(f"[paddle_webhook] payment {pm.id} marked refunded ({refunded})")

    return jsonify({"received": True}), 200


# ═══════════════════════════════════════════
# CHECKOUT + SUCCESS
# ═══════════════════════════════════════════

@payments_bp.route('/checkout-session', methods=['POST'])
def create_checkout_session():
    try:
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
    except Exception as e:
        logging.error(f"[create_checkout_session] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


@payments_bp.route('/upgrade-callback')
def upgrade_callback():
    """
    Success page after Paddle checkout.
    
    TIMING: The user lands here BEFORE the transaction.completed webhook fires.
    So we can't rely on having a Payment record in DB yet.
    
    Strategy:
    1. Check Paddle's redirect URL params (_ptxn, customer_id from session)
    2. If webhook already fired → pull from Payment table (fast path)
    3. If not → fetch transaction details directly from Paddle API (slow path)
    4. Fallback → show what we know from session + org
    """
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    from utils.plan_limits import PLAN_LIMITS
    import time

    org = Organization.query.get(session.get('org_id'))

    # --- Determine the plan ---
    # Session checkout_plan takes PRIORITY — it's what the user JUST selected.
    # org.plan may still reflect an old/cancelled plan if webhook hasn't fired yet.
    plan = session.pop('checkout_plan', None)
    if not plan:
        plan = request.args.get('plan', '')
    if not plan:
        plan = org.plan if (org and org.plan and org.plan != 'free') else 'free'

    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])

    # --- Get transaction ID from Paddle redirect URL ---
    # Paddle appends ?_ptxn=txn_xxx to the callback URL
    paddle_txn_id = request.args.get('_ptxn') or request.args.get('transaction_id') or None

    # --- Wait for webhook to populate data (usually arrives within 2-4 seconds) ---
    latest_payment = None
    if org and paddle_txn_id:
        # Poll up to 5 seconds for the Payment record to appear (webhook creates it)
        for _ in range(10):
            latest_payment = Payment.query.filter_by(paddle_transaction_id=paddle_txn_id).first()
            if latest_payment:
                break
            time.sleep(0.5)
            db.session.expire_all()  # Clear SQLAlchemy cache to see new rows

        # Also refresh org to pick up webhook-set fields (customer_id, subscription_id)
        if not org.paddle_subscription_id or not org.paddle_subscription_id.startswith('sub_'):
            for _ in range(6):
                db.session.refresh(org)
                if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
                    break
                time.sleep(0.5)
    elif org:
        latest_payment = (Payment.query
                          .filter_by(org_id=org.id)
                          .order_by(Payment.created_at.desc())
                          .first())

    # --- Build display values ---
    transaction_id = paddle_txn_id or (latest_payment.paddle_transaction_id if latest_payment else None) or '—'
    
    # Customer ID: from org (webhook sets this), or session checkout data
    customer_id = '—'
    if org and org.paddle_customer_id and org.paddle_customer_id.startswith('ctm_'):
        customer_id = org.paddle_customer_id
    elif request.args.get('customer_id'):
        customer_id = request.args.get('customer_id')

    # Subscription ID: from org (set by subscription.created webhook)
    subscription_id = '—'
    if org and org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
        subscription_id = org.paddle_subscription_id

    # Product/Price ID
    product_id = (latest_payment.product_id if latest_payment else None) \
        or current_app.config.get(f'PADDLE_PRICE_{plan.upper()}') or '—'

    # Amount
    amount_paid = latest_payment.amount if latest_payment else None
    currency = latest_payment.currency if latest_payment else 'INR'

    # --- Fetch from Paddle API when we have _ptxn (always, for accurate data) ---
    if paddle_txn_id and paddle_txn_id.startswith('txn_'):
        try:
            url = f"{_paddle_api_base()}/transactions/{paddle_txn_id}"
            resp = http_requests.get(url, headers=_paddle_headers(), timeout=5)
            if resp.status_code in (200, 201):
                txn_data = resp.json().get('data', {})
                transaction_id = txn_data.get('id', transaction_id)
                if txn_data.get('subscription_id'):
                    subscription_id = txn_data.get('subscription_id')
                if txn_data.get('customer_id'):
                    customer_id = txn_data.get('customer_id')
                # Amount from Paddle (most accurate — reflects the actual charge)
                totals = (txn_data.get('details', {}) or {}).get('totals', {}) or {}
                raw = totals.get('grand_total') or totals.get('total') or '0'
                try:
                    amount_paid = round(int(raw) / 100.0, 2)
                except (ValueError, TypeError):
                    pass
                # Detect plan from price_id (most accurate source of truth)
                items = txn_data.get('items', [])
                if items:
                    fetched_price_id = items[0].get('price', {}).get('id', '')
                    if fetched_price_id:
                        product_id = fetched_price_id
                        price_plan_map = get_price_plan_map()
                        detected_plan = price_plan_map.get(fetched_price_id)
                        if detected_plan:
                            plan = detected_plan
                            limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])
        except Exception as e:
            logging.warning(f"[upgrade_callback] Paddle API fetch failed: {e}")

    return render_template('payment_success.html',
        plan_name=plan.capitalize(),
        messages_limit=limits.get('messages', 0),
        bots_limit=limits.get('bots', 1),
        org_name=org.name if org else '',
        transaction_id=transaction_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
        product_id=product_id,
        amount_paid=amount_paid,
        currency=currency,
    )


# ═══════════════════════════════════════════
# MANAGE PLAN
# ═══════════════════════════════════════════

@payments_bp.route('/manage')
def manage_plan():
    """Comprehensive subscription management page."""
    try:
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        from utils.plan_limits import PLAN_LIMITS, get_usage_summary

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
        total_spent = sum((p.amount or 0) - (p.refund_amount or 0) for p in payments if p.status in ('completed', 'partially_refunded'))

        # Subscription status
        has_active_subscription = bool(org and org.paddle_subscription_id)
        is_paddle_customer = bool(org and org.paddle_customer_id and org.paddle_customer_id.startswith('ctm_'))

        # Subscription lifecycle for display
        sub_status = (org.subscription_status if org and org.subscription_status else ('active' if plan != 'free' else 'free'))
        sub_started = org.subscription_started_at if org else None
        sub_ends = org.subscription_ends_at if org else None

        # Human-friendly payment method label
        payment_method_label = 'Not on file'
        if org:
            # Read from latest completed payment (normalized — not stored on org)
            latest_pm = Payment.query.filter_by(org_id=org.id, status='completed')\
                .order_by(Payment.created_at.desc()).first()
            if latest_pm and latest_pm.payment_method:
                if latest_pm.card_brand and latest_pm.card_last4:
                    payment_method_label = f"{latest_pm.card_brand.title()} ···· {latest_pm.card_last4}"
                else:
                    payment_method_label = latest_pm.payment_method.replace('_', ' ').title()

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
            usage=usage,
            sub_status=sub_status,
            sub_started=sub_started,
            sub_ends=sub_ends,
            payment_method_label=payment_method_label,
            card_brand=None,
            card_last4=None)
    except Exception as e:
        logging.error(f"[manage_plan] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))


# ═══════════════════════════════════════════
# CANCEL / PAYMENT METHOD / PORTAL
# ═══════════════════════════════════════════

def _latest_completed_payment(org):
    """Most recent non-refunded completed payment for an org (the one to refund against)."""
    if not org:
        return None
    return (Payment.query
            .filter_by(org_id=org.id, status='completed')
            .order_by(Payment.created_at.desc())
            .first())


@payments_bp.route('/refund-preview', methods=['GET'])
def refund_preview():
    """
    Return the proportionate refund calculation for the org's latest payment,
    so the UI can show the exact maths BEFORE the user confirms cancellation.
    """
    try:
        if 'user_id' not in session:
            return jsonify({"error": "Not logged in"}), 401

        from utils.plan_limits import calculate_proportionate_refund, PLAN_PRICE_INR

        org = Organization.query.get(session.get('org_id'))
        if not org:
            return jsonify({"error": "Organization not found"}), 404
        if not org.plan or org.plan == 'free':
            return jsonify({"error": "You are on the free plan — nothing to cancel."}), 400

        payment = _latest_completed_payment(org)
        if not payment:
            # No recorded payment — cancel with no refund (period-end)
            return jsonify({
                "success": True,
                "has_payment": False,
                "message": "No recent payment found. Cancelling will stop future billing; access continues until the period ends.",
            }), 200

        calc = calculate_proportionate_refund(payment, plan_price=PLAN_PRICE_INR.get(payment.plan, 0))

        # Determine when access ends:
        # - Within 14-day window: access till 23:59 today (refund day)
        # - After 14 days: access till original billing period end (subscription_ends_at)
        if calc['eligible']:
            access_until_str = calc['access_until'].strftime('%b %d, %Y, 11:59 PM')
        else:
            # Use original subscription end date, or fallback to messages_reset_at, or 30 days from purchase
            from utils.plan_limits import _aware
            original_end = _aware(org.subscription_ends_at) if org.subscription_ends_at else None
            if not original_end and org.messages_reset_at:
                original_end = _aware(org.messages_reset_at)
            if not original_end:
                original_end = calc['purchase_date'] + timedelta(days=30)
            access_until_str = original_end.strftime('%b %d, %Y, 11:59 PM')

        return jsonify({
            "success": True,
            "has_payment": True,
            "currency": calc['currency'],
            "plan": (payment.plan or '').capitalize(),
            "plan_price": calc['plan_price'],
            "daily_rate": calc['daily_rate'],
            "billing_days": calc['billing_days'],
            "days_used": calc['days_used'],
            "amount_consumed": calc['amount_consumed'],
            "refund_amount": calc['refund_amount'],
            "eligible": calc['eligible'],
            "within_window": calc['within_window'],
            "refund_window_days": calc['refund_window_days'],
            "purchase_date": calc['purchase_date'].strftime('%b %d, %Y'),
            "access_until": access_until_str,
        }), 200
    except Exception as e:
        logging.error(f"[refund_preview] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


@payments_bp.route('/cancel-plan', methods=['POST'])
def cancel_plan():
    """
    Cancel the subscription with a PROPORTIONATE refund (14-day window).

    - Computes the fractional refund for the current billing period.
    - Keeps the plan active until 23:59 of the cancellation day.
    - Issues the refund via Paddle (best-effort) and records it locally.
    - After the day ends, enforce_subscription_expiry() downgrades to free.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    from utils.plan_limits import calculate_proportionate_refund, PLAN_PRICE_INR, end_of_day

    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404
    if not org.plan or org.plan == 'free':
        return jsonify({"error": "You are already on the free plan"}), 400

    now = datetime.now(timezone.utc)
    payment = _latest_completed_payment(org)

    calc = None
    refund_issued = 0.0
    if payment:
        calc = calculate_proportionate_refund(payment, plan_price=PLAN_PRICE_INR.get(payment.plan, 0))

        # Attempt the refund via Paddle (best-effort — works with real transactions)
        if calc['eligible'] and payment.paddle_transaction_id and payment.paddle_transaction_id.startswith('txn_'):
            try:
                url = f"{_paddle_api_base()}/adjustments"
                body = {
                    "action": "refund",
                    "transaction_id": payment.paddle_transaction_id,
                    "reason": "Customer requested proportionate refund (14-day policy)",
                    "type": "partial",
                    "items": [],
                }
                resp = http_requests.post(url, headers=_paddle_headers(), json=body)
                if resp.status_code in (200, 201):
                    logging.info(f"[cancel_plan] Paddle refund created for {payment.paddle_transaction_id}")
                else:
                    logging.error(f"[cancel_plan] Paddle refund error: {resp.status_code} {resp.text[:200]}")
            except Exception as e:
                logging.error(f"[cancel_plan] Paddle refund exception: {e}")

        # Record the refund locally (source of truth for our reporting)
        if calc['eligible']:
            refund_issued = calc['refund_amount']
            payment.refund_amount = refund_issued
            payment.refunded_at = now
            payment.status = 'refunded' if refund_issued >= (payment.amount or 0) else 'partially_refunded'

    # Determine access end date:
    # - Within 14 days (refund eligible): plan ends at 23:59 today
    # - After 14 days (no refund): plan stays till original billing period end
    from utils.plan_limits import _aware
    if calc and calc['eligible']:
        access_until = end_of_day(now)
    else:
        # Use the existing subscription end date (original billing period)
        original_end = _aware(org.subscription_ends_at) if org.subscription_ends_at else None
        if not original_end and org.messages_reset_at:
            original_end = _aware(org.messages_reset_at)
        if not original_end and payment:
            original_end = _aware(payment.created_at) + timedelta(days=30) if payment.created_at else end_of_day(now)
        if not original_end:
            original_end = end_of_day(now)
        access_until = original_end

    # Cancel the Paddle subscription (stops future billing, NOT immediate access removal)
    if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
        try:
            url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}/cancel"
            # If within window (refund): cancel immediately. If not: cancel at period end.
            effective = "immediately" if (calc and calc['eligible']) else "next_billing_period"
            http_requests.post(url, headers=_paddle_headers(), json={"effective_from": effective})
        except Exception as e:
            logging.error(f"[cancel_plan] Paddle sub cancel exception: {e}")

    # Mark canceled + set the access end date
    org.subscription_status = 'canceled'
    org.subscription_ends_at = access_until
    db.session.commit()

    response = {
        "success": True,
        "access_until": access_until.strftime('%b %d, %Y, 11:59 PM'),
        "message": f"Your plan is cancelled. You keep full access until {access_until.strftime('%b %d, %Y')} (11:59 PM).",
    }
    if calc:
        response["refund"] = {
            "eligible": calc['eligible'],
            "currency": calc['currency'],
            "plan_price": calc['plan_price'],
            "daily_rate": calc['daily_rate'],
            "billing_days": calc['billing_days'],
            "days_used": calc['days_used'],
            "amount_consumed": calc['amount_consumed'],
            "refund_amount": refund_issued,
            "within_window": calc['within_window'],
            "refund_window_days": calc['refund_window_days'],
        }
    return jsonify(response), 200


@payments_bp.route('/customer-portal', methods=['POST'])
def customer_portal():
    """
    Generate a Paddle customer portal session URL.
    Falls back gracefully if customer isn't a real Paddle customer yet.
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    customer_id = org.paddle_customer_id
    
    # If we don't have a real Paddle customer ID, can't open portal
    if not customer_id or not customer_id.startswith('ctm_'):
        # Check if there's a subscription ID we can use
        if not org.paddle_subscription_id or not org.paddle_subscription_id.startswith('sub_'):
            return jsonify({
                "error": "Payment method management is handled by Paddle. Since your subscription was created in sandbox mode, the customer portal is not available. Your payment method will be managed automatically on your next billing cycle."
            }), 400

    # Call Paddle API: POST /customers/{customer_id}/portal-sessions
    try:
        url = f"{_paddle_api_base()}/customers/{customer_id}/portal-sessions"
        body = {}
        if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
            body['subscription_ids'] = [org.paddle_subscription_id]

        resp = http_requests.post(url, headers=_paddle_headers(), json=body, timeout=10)
        if resp.status_code in (200, 201):
            data = resp.json().get('data', {})
            portal_url = data.get('urls', {}).get('general', {}).get('overview', '')
            if not portal_url:
                portal_url = data.get('url', '')
            if portal_url:
                return jsonify({"success": True, "url": portal_url}), 200
            else:
                return jsonify({"error": "Portal URL not returned by Paddle. Try again later."}), 400
        else:
            error_msg = resp.json().get('error', {}).get('detail', resp.text[:200])
            logging.error(f"[customer_portal] Paddle API error: {resp.status_code} {error_msg}")
            return jsonify({"error": "Payment method is managed by Paddle. This feature requires production Paddle keys. In sandbox mode, use Paddle's test dashboard to manage payment methods."}), 400
    except Exception as e:
        logging.error(f"[customer_portal] exception: {e}")
        return jsonify({"error": "Could not connect to Paddle. Please try again later."}), 400


@payments_bp.route('/update-payment-method', methods=['POST'])
def update_payment_method():
    """Update payment method via Paddle customer portal."""
    return customer_portal()


@payments_bp.route('/upgrade-preview', methods=['POST'])
def upgrade_preview():
    """
    Show the prorated cost of upgrading from current plan to a new plan.
    Formula: upgrade_cost = new_plan_price - credit_remaining
    Where: credit_remaining = current_plan_price - (daily_rate × days_used)
    """
    try:
        if 'user_id' not in session:
            return jsonify({"error": "Not logged in"}), 401

        from utils.plan_limits import PLAN_PRICE_INR, BILLING_DAYS, _aware

        org = Organization.query.get(session.get('org_id'))
        if not org:
            return jsonify({"error": "Organization not found"}), 404

        data = request.json or {}
        target_plan = data.get('plan', '').lower()

        if target_plan not in ('starter', 'growth', 'pro'):
            return jsonify({"error": "Invalid target plan."}), 400

        current_plan = org.plan or 'free'
        current_price = PLAN_PRICE_INR.get(current_plan, 0)
        target_price = PLAN_PRICE_INR.get(target_plan, 0)

        if target_price <= current_price:
            return jsonify({"error": "You can only upgrade to a higher plan."}), 400

        # Calculate days used on current plan
        now = datetime.now(timezone.utc)
        payment = _latest_completed_payment(org)
    
        if payment and payment.created_at:
            purchase_date = _aware(payment.created_at)
            days_elapsed = (now.date() - purchase_date.date()).days
            days_used = days_elapsed + 1
        elif org.subscription_started_at:
            started = _aware(org.subscription_started_at)
            days_elapsed = (now.date() - started.date()).days
            days_used = days_elapsed + 1
        else:
            days_used = 1

        if days_used < 1:
            days_used = 1
        if days_used > BILLING_DAYS:
            days_used = BILLING_DAYS

        # Calculate credit remaining from current plan
        daily_rate_current = round(current_price / BILLING_DAYS, 2)
        amount_consumed = round(daily_rate_current * days_used, 2)
        credit_remaining = round(current_price - amount_consumed, 2)
        if credit_remaining < 0:
            credit_remaining = 0

        # Calculate what user pays for upgrade
        upgrade_cost = round(target_price - credit_remaining, 2)
        if upgrade_cost < 0:
            upgrade_cost = 0

        return jsonify({
            "success": True,
            "current_plan": current_plan.capitalize(),
            "current_price": current_price,
            "target_plan": target_plan.capitalize(),
            "target_price": target_price,
            "days_used": days_used,
            "billing_days": BILLING_DAYS,
            "daily_rate_current": daily_rate_current,
            "amount_consumed": amount_consumed,
            "credit_remaining": credit_remaining,
            "upgrade_cost": upgrade_cost,
            "currency": "INR",
        }), 200
    except Exception as e:
        logging.error(f"[upgrade_preview] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


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
                logging.error(f"[upgrade_plan] Paddle API error: {resp.status_code} {error_detail}")
                return jsonify({"error": f"Paddle error: {error_detail}"}), 500
        except Exception as e:
            logging.error(f"[upgrade_plan] exception: {e}")
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
    Reactivate a cancelled subscription.
    - If Paddle sub exists and is still active (scheduled cancel): remove the scheduled cancel.
    - If Paddle API fails or sub is fully gone: reactivate locally (restore plan + clear canceled status).
    """
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    org = Organization.query.get(session.get('org_id'))
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    if not org.subscription_status or org.subscription_status not in ('canceled', 'free'):
        # If subscription_status is None (column new/not set), check org.plan
        if org.plan and org.plan != 'free':
            return jsonify({"error": "Your subscription is already active. No reactivation needed."}), 400
        else:
            return jsonify({"error": "No active subscription to reactivate. Please subscribe to a plan."}), 400

    # Try Paddle API if we have a real sub ID
    paddle_success = False
    if org.paddle_subscription_id and org.paddle_subscription_id.startswith('sub_'):
        try:
            get_url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}"
            get_resp = http_requests.get(get_url, headers=_paddle_headers(), timeout=10)
            
            if get_resp.status_code in (200, 201):
                sub_data = get_resp.json().get('data', {})
                sub_status = sub_data.get('status', '')
                scheduled_change = sub_data.get('scheduled_change', None)
                
                if sub_status == 'active' and scheduled_change and scheduled_change.get('action') == 'cancel':
                    # Remove the scheduled cancellation
                    url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}"
                    resp = http_requests.patch(url, headers=_paddle_headers(), json={"scheduled_change": None}, timeout=10)
                    if resp.status_code in (200, 201):
                        paddle_success = True
                elif sub_status == 'paused':
                    url = f"{_paddle_api_base()}/subscriptions/{org.paddle_subscription_id}/resume"
                    resp = http_requests.post(url, headers=_paddle_headers(), json={"effective_from": "immediately"}, timeout=10)
                    if resp.status_code in (200, 201):
                        paddle_success = True
                elif sub_status == 'canceled':
                    # Fully expired on Paddle side — just reactivate locally, user needs new checkout for next cycle
                    pass
        except Exception as e:
            logging.warning(f"[reactivate_plan] Paddle API error (falling back to local): {e}")

    # Local reactivation: restore the plan regardless of Paddle API result
    # (The user already paid for this period — let them use it)
    from utils.plan_limits import _aware
    
    # Determine what plan to restore (use the last payment's plan)
    last_payment = _latest_completed_payment(org)
    restore_plan = last_payment.plan if last_payment and last_payment.plan else 'starter'
    
    org.plan = restore_plan
    org.subscription_status = 'active'
    # Extend access to 30 days from now if no end date, or keep existing if it's in the future
    now = datetime.now(timezone.utc)
    if org.subscription_ends_at:
        current_end = _aware(org.subscription_ends_at)
        if current_end < now:
            org.subscription_ends_at = now + timedelta(days=30)
    else:
        org.subscription_ends_at = now + timedelta(days=30)
    
    db.session.commit()

    return jsonify({
        "success": True, 
        "message": f"Plan reactivated to {restore_plan.capitalize()}! You have full access.",
        "paddle_synced": paddle_success
    }), 200


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
            logging.warning(f"[subscription_status] Paddle API error: {e}")

    return jsonify(result), 200


@payments_bp.route('/invoice/<int:payment_id>')
def invoice(payment_id):
    """
    Render a printable invoice for a single payment.
    The user can print-to-PDF from the browser (Ctrl+P / Save as PDF).
    Access is restricted to the payment's own organization.
    """
    try:
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        payment = Payment.query.get_or_404(payment_id)

        # Ownership check — a user can only see their own org's invoices
        if payment.org_id != session.get('org_id'):
            flash("You are not authorized to view this invoice.", "error")
            return redirect(url_for('payments_bp.manage_plan'))

        org = Organization.query.get(payment.org_id)
        user = User.query.get(session['user_id'])

        company_first = current_app.config.get('COMPANY_NAME_FIRST', 'Bubbl')
        company_last = current_app.config.get('COMPANY_LAST_NAME', 'ooo')
        support_email = current_app.config.get('SUPPORT_EMAIL', 'support@bubbl.ooo')

        # Amount breakdown (Paddle prices are tax-inclusive; show a simple summary)
        gross = payment.amount or 0.0
        is_refunded = payment.status in ('refunded', 'partially_refunded')

        # Build a card/method label
        method_label = 'Managed via Paddle'
        if payment.payment_method:
            if payment.card_brand and payment.card_last4:
                method_label = f"{payment.card_brand.title()} ···· {payment.card_last4}"
            else:
                method_label = payment.payment_method.replace('_', ' ').title()

        invoice_number = f"BUBBL-{payment.created_at.strftime('%Y%m%d')}-{payment.id:05d}" if payment.created_at else f"BUBBL-{payment.id:05d}"

        return render_template('invoice.html',
            payment=payment,
            org=org,
            user=user,
            company_name=f"{company_first}.{company_last}",
            support_email=support_email,
            gross=gross,
            is_refunded=is_refunded,
            method_label=method_label,
            invoice_number=invoice_number,
        )
    except Exception as e:
        logging.error(f"[invoice] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))


@payments_bp.route('/test-webhook', methods=['GET'])
def test_webhook_reachable():
    return jsonify({"status": "ok", "message": "Paddle webhook endpoint is reachable"}), 200

