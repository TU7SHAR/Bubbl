from flask import Blueprint, request, jsonify, session
from models.models import db, Organization
import hmac
import hashlib
import os

payments_bp = Blueprint('payments_bp', __name__, url_prefix='/payments')

PADDLE_WEBHOOK_SECRET = os.getenv('PADDLE_WEBHOOK_SECRET', '')

PLAN_MAP = {
    # Map Paddle price IDs to plan names (placeholder IDs for now)
    'pri_starter_monthly': 'starter',
    'pri_growth_monthly': 'growth',
    'pri_pro_monthly': 'pro',
}

def verify_paddle_signature(request_body, signature, secret):
    """Verify Paddle webhook signature"""
    if not secret:
        return True  # Skip verification in dev if no secret set
    computed = hmac.new(secret.encode(), request_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)

@payments_bp.route('/webhook/paddle', methods=['POST'])
def paddle_webhook():
    """Receives webhooks from Paddle when subscription is created/updated/cancelled"""
    # In production, verify the signature
    # signature = request.headers.get('Paddle-Signature', '')
    # if not verify_paddle_signature(request.get_data(), signature, PADDLE_WEBHOOK_SECRET):
    #     return jsonify({"error": "Invalid signature"}), 401

    data = request.json
    event_type = data.get('event_type', '')

    if event_type == 'subscription.created' or event_type == 'subscription.updated':
        # Extract subscription details
        sub_data = data.get('data', {})
        customer_id = sub_data.get('customer_id', '')
        subscription_id = sub_data.get('id', '')
        status = sub_data.get('status', '')

        # Get the price ID to determine the plan
        items = sub_data.get('items', [])
        price_id = items[0].get('price', {}).get('id', '') if items else ''
        plan = PLAN_MAP.get(price_id, 'free')

        # Find the org by paddle_customer_id
        org = Organization.query.filter_by(paddle_customer_id=customer_id).first()
        if org and status == 'active':
            org.plan = plan
            org.paddle_subscription_id = subscription_id
            db.session.commit()

    elif event_type == 'subscription.canceled':
        sub_data = data.get('data', {})
        customer_id = sub_data.get('customer_id', '')

        org = Organization.query.filter_by(paddle_customer_id=customer_id).first()
        if org:
            org.plan = 'free'
            org.paddle_subscription_id = None
            db.session.commit()

    return jsonify({"received": True}), 200

@payments_bp.route('/checkout-session', methods=['POST'])
def create_checkout_session():
    """Frontend calls this to get checkout data before opening Paddle"""
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    org_id = session.get('org_id')
    org = Organization.query.get(org_id)

    if not org:
        return jsonify({"error": "Organization not found"}), 404

    # Store paddle_customer_id if not already set
    # In real implementation, you'd create a Paddle customer first
    # For now, use org_id as identifier
    if not org.paddle_customer_id:
        org.paddle_customer_id = f"org_{org.id}"
        db.session.commit()

    return jsonify({
        "customer_id": org.paddle_customer_id,
        "org_id": org.id,
        "current_plan": org.plan,
        "email": session.get('user_email', '')
    }), 200
