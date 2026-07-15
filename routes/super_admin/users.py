"""Super Admin — User management (list, upgrade, suspend, email, delete, impersonate, export)."""
import csv
import io
import string
import secrets

import bcrypt
from flask import render_template, request, jsonify, session, redirect, url_for, make_response
from datetime import datetime, timezone, timedelta
from models.models import db, User, Bot, Lead, Organization, Payment, Document, ScrapeJob, ChatMessage, Feedback, BotUI
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


# ═══════════════════════════════════════════
# NEW ROUTES
# ═══════════════════════════════════════════


@super_admin_bp.route('/users/delete', methods=['POST'])
@super_admin_required
def delete_user():
    """Delete a user and cascade-delete their bots + all associated data."""
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid user ID."}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    user_name = user.name

    # Delete all bots owned by this user (cascade handles docs, scrapes, leads, messages, feedback, ui)
    bots = Bot.query.filter_by(created_by=user.id).all()
    for bot in bots:
        db.session.delete(bot)

    # Delete the user itself
    db.session.delete(user)
    db.session.commit()

    return jsonify({"success": True, "name": user_name})


@super_admin_bp.route('/users/reset_password', methods=['POST'])
@super_admin_required
def reset_password():
    """Generate a random password, hash it, update user, and email the new password."""
    from utils.mail_helper import send_custom_email

    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid user ID."}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    # Generate random 12-char password
    alphabet = string.ascii_letters + string.digits
    new_password = ''.join(secrets.choice(alphabet) for _ in range(12))

    # Hash with bcrypt
    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    user.password_hash = password_hash
    db.session.commit()

    # Email the user
    subject = "Your password has been reset"
    message = f"Your password has been reset by an administrator.\n\nYour new password is: {new_password}\n\nPlease log in and change it immediately."
    try:
        send_custom_email(user.email, subject, message, user.name)
    except Exception:
        pass

    return jsonify({"success": True, "email": user.email})


@super_admin_bp.route('/users/impersonate/<int:user_id>')
@super_admin_required
def impersonate_user(user_id):
    """Impersonate a user by switching session context."""
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    org = Organization.query.get(user.org_id) if user.org_id else None

    # Store current super admin session for later restoration
    session['impersonating_from'] = {
        'user_id': session.get('user_id'),
        'user_name': session.get('user_name'),
        'org_id': session.get('org_id'),
        'org_name': session.get('org_name'),
        'role': session.get('role'),
    }

    # Set session to the target user's data
    session['user_id'] = user.id
    session['user_name'] = user.name
    session['org_id'] = user.org_id
    session['org_name'] = org.name if org else ''
    session['role'] = user.role

    return redirect(url_for('views_bp.dashboard'))


@super_admin_bp.route('/users/stop_impersonate')
def stop_impersonate():
    """Restore original super admin session (no decorator — role is impersonated)."""
    original = session.pop('impersonating_from', None)
    if not original:
        return redirect(url_for('super_admin_bp.users_page'))

    session['user_id'] = original.get('user_id')
    session['user_name'] = original.get('user_name')
    session['org_id'] = original.get('org_id')
    session['org_name'] = original.get('org_name')
    session['role'] = original.get('role')

    return redirect(url_for('super_admin_bp.users_page'))


@super_admin_bp.route('/users/<int:user_id>')
@super_admin_required
def user_detail(user_id):
    """Detailed view of a single user."""
    user = User.query.get(user_id)
    if not user:
        return redirect(url_for('super_admin_bp.users_page'))

    org = Organization.query.get(user.org_id) if user.org_id else None
    bots = Bot.query.filter_by(created_by=user.id).all()
    payments = Payment.query.filter_by(user_id=user.id).order_by(Payment.created_at.desc()).all()

    bot_ids = [b.id for b in bots]
    leads = Lead.query.filter(Lead.bot_id.in_(bot_ids)).order_by(Lead.captured_at.desc()).all() if bot_ids else []

    return render_template('super_admin/user_detail.html',
        user=user, org=org, bots=bots, payments=payments, leads=leads)


@super_admin_bp.route('/users/bulk_email', methods=['POST'])
@super_admin_required
def bulk_email():
    """Send an email to all users matching a filter."""
    from utils.mail_helper import send_custom_email

    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or '').strip()
    message = (data.get('message') or '').strip()
    user_filter = (data.get('filter') or 'all').strip().lower()

    if not subject or not message:
        return jsonify({"error": "Subject and message required."}), 400

    if user_filter == 'all':
        users = User.query.all()
    elif user_filter == 'free':
        users = User.query.join(Organization, User.org_id == Organization.id).filter(
            (Organization.plan == 'free') | (Organization.plan.is_(None))
        ).all()
    elif user_filter == 'paid':
        users = User.query.join(Organization, User.org_id == Organization.id).filter(
            Organization.plan.notin_(['free', None])
        ).all()
    else:
        users = User.query.all()

    count = 0
    for user in users:
        try:
            send_custom_email(user.email, subject, message, user.name)
            count += 1
        except Exception:
            pass

    return jsonify({"success": True, "count": count})


@super_admin_bp.route('/users/export')
@super_admin_required
def export_users_csv():
    """Export all users as a CSV download."""
    all_users = User.query.order_by(User.id.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'email', 'role', 'plan', 'bots', 'leads', 'created_at'])

    for u in all_users:
        org = Organization.query.get(u.org_id) if u.org_id else None
        plan = (org.plan if org else 'free') or 'free'
        bot_count = Bot.query.filter_by(created_by=u.id).count()
        bot_ids = [b.id for b in Bot.query.filter_by(created_by=u.id).all()]
        lead_count = Lead.query.filter(Lead.bot_id.in_(bot_ids)).count() if bot_ids else 0
        created_at = getattr(u, 'created_at', '') or ''

        writer.writerow([u.name, u.email, u.role, plan, bot_count, lead_count, str(created_at)])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=users_export.csv'
    return response
