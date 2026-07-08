from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from models.models import User, Bot, Organization, db
from utils.plan_limits import PLAN_LIMITS, check_message_limit, get_usage_summary

profile_bp = Blueprint('profile_bp', __name__)

@profile_bp.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    user = User.query.get(session['user_id'])
    bot_count = Bot.query.filter_by(created_by=session['user_id']).count()
    org = Organization.query.get(session.get('org_id'))
    
    # Get comprehensive usage summary
    usage = get_usage_summary(session.get('org_id'))
    
    # Plan & usage info (fallback for template compatibility)
    plan = usage['plan'] if usage else 'free'
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS['free'])
    messages_used = usage['messages_used'] if usage else 0
    messages_limit = usage['messages_limit'] if usage else 200
    bots_limit = usage['bots_limit'] if usage else 1
    messages_reset_at = org.messages_reset_at if org else None
    usage_percent = usage['messages_percent'] if usage else 0
    
    org_members = []
    if session.get('role') == 'admin':
        org_members = User.query.filter(
            User.org_id == session['org_id'],
            User.id != session['user_id']
        ).all()
    
    return render_template('profile.html', 
        user=user, 
        bot_count=bot_count, 
        org_members=org_members,
        org=org,
        plan=plan,
        limits=limits,
        messages_used=messages_used,
        messages_limit=messages_limit,
        bots_limit=bots_limit,
        usage_percent=usage_percent,
        messages_reset_at=messages_reset_at,
        usage=usage,
    )

@profile_bp.route('/remove_member/<int:member_id>', methods=['POST'])
def remove_member(member_id):
    if session.get('role') != 'admin':
        flash("Unauthorized action. Only admins can remove members.", "error")
        return redirect(url_for('profile_bp.profile'))
        
    member_to_remove = User.query.get(member_id)
    
    if member_to_remove and member_to_remove.org_id == session['org_id']:
        db.session.delete(member_to_remove)
        db.session.commit()
        flash(f"{member_to_remove.name} has been removed from the organization.", "success")
    else:
        flash("Member not found or access denied.", "error")
        
    return redirect(url_for('profile_bp.profile'))