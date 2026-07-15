"""Super Admin — User management (list, upgrade, suspend, email)."""
from flask import render_template, request, jsonify
from datetime import datetime, timezone, timedelta
from models.models import db, User, Bot, Lead, Organization
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/users')
@super_admin_required
def users_page():
    """List all users with their plan, bots, leads."""
    all_users = User.query.order_by(User.id.desc()).all()
    enriched = []
    for u in all_users:
        org = Organization.query.get(u.org_id) if u.org_id else None
        bot_count = Bot.query.filter_by(created_by=u.id).count()
        bot_ids = [b.id for b in Bot.query.filter_by(created_by=u.id).all()]
        lead_count = Lead.query.filter(Lead.bot_id.in_(bot_ids)).count() if bot_ids else 0

        enriched.append({
            'id': u.id,
            'name': u.name,
            'email': u.email,
            'role': u.role,
            'is_verified': u.is_verified,
            'is_suspended': getattr(u, 'is_suspended', False),
            'plan': (org.plan if org else 'free') or 'free',
            'subscription_status': (org.subscription_status if org else 'free') or 'free',
            'bot_count': bot_count,
            'lead_count': lead_count,
            'created_at': getattr(u, 'created_at', None),
        })

    return render_template('super_admin/users.html', users=enriched)


@super_admin_bp.route('/users/upgrade', methods=['POST'])
@super_admin_required
def upgrade_user():
    """Change a user's plan (free <-> paid) and email them."""
    from utils.plan_limits import PLAN_LIMITS
    from utils.mail_helper import send_plan_upgrade_email

    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid user ID."}), 400

    new_plan = (data.get('plan') or '').strip().lower()
    if new_plan not in PLAN_LIMITS:
        return jsonify({"error": "Invalid plan."}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    org = Organization.query.get(user.org_id)
    if not org:
        return jsonify({"error": "Account not found."}), 404

    now = datetime.now(timezone.utc)
    org.plan = new_plan
    if new_plan == 'free':
        org.subscription_status = 'free'
        org.subscription_started_at = None
        org.subscription_ends_at = None
    else:
        org.subscription_status = 'active'
        org.subscription_started_at = now
        org.subscription_ends_at = now + timedelta(days=30)
    org.messages_used = 0
    org.messages_reset_at = now + timedelta(days=30)
    db.session.commit()

    emailed = False
    try:
        emailed = send_plan_upgrade_email(user.email, user.name, new_plan)
    except Exception:
        pass

    return jsonify({"success": True, "plan_label": new_plan.capitalize(), "emailed": emailed, "email": user.email})


@super_admin_bp.route('/users/suspend', methods=['POST'])
@super_admin_required
def suspend_user():
    """Toggle user suspension."""
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid user ID."}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    user.is_suspended = not getattr(user, 'is_suspended', False)
    db.session.commit()
    status = "suspended" if user.is_suspended else "active"
    return jsonify({"success": True, "status": status, "name": user.name})


@super_admin_bp.route('/users/email', methods=['POST'])
@super_admin_required
def send_email():
    """Send a custom email to a user."""
    from utils.mail_helper import send_custom_email

    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid user ID."}), 400

    subject = (data.get('subject') or '').strip()
    message = (data.get('message') or '').strip()

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404
    if not subject or not message:
        return jsonify({"error": "Subject and message required."}), 400

    try:
        ok = send_custom_email(user.email, subject, message, user.name)
    except Exception:
        return jsonify({"error": "SMTP error."}), 500

    if not ok:
        return jsonify({"error": "Email failed."}), 500
    return jsonify({"success": True, "email": user.email})
