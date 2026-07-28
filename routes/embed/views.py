import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import request, jsonify
from flask import Blueprint, app, render_template, request, session, redirect, url_for, flash, make_response, jsonify
from models.models import db, Bot, User, Document, Lead, ScrapeJob, BotUI, Feedback, Organization, Payment
from utils.mail_helper import is_valid_email, send_contact_email, send_auto_reply
from extensions import cache
import csv
from datetime import datetime, timedelta, timezone
import io
from sqlalchemy import func
import psutil
from flask import send_from_directory, current_app
views_bp = Blueprint('views_bp', __name__)

# =========================================
# MARKETING SITE REDIRECT — app.bubbl.ooo is app-only.
# All marketing/public content lives on bubbl.ooo (separate frontend).
# =========================================
MARKETING_SITE = "https://bubbl.ooo"

@views_bp.route('/coming-soon')
def coming_soon():
    return redirect(f"{MARKETING_SITE}/pricing.html")

@views_bp.route('/roadmap')
def roadmap():
    return redirect(f"{MARKETING_SITE}/roadmap.html")

@views_bp.route('/how-to')
def how_to():
    return redirect(f"{MARKETING_SITE}/how-to.html")

@views_bp.route('/legal/privacy')
def privacy():
    return render_template('legal/privacy.html')

@views_bp.route('/legal/terms')
def terms():
    return render_template('legal/terms.html')

@views_bp.route('/legal/refunds')
def refunds():
    return render_template('legal/refunds.html')

@views_bp.app_errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@views_bp.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

@views_bp.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@views_bp.route('/api/waitlist', methods=['POST'])
def join_waitlist():
    data = request.get_json()
    user_email = data.get('email')
    user_name = data.get('name', '').strip()
    source_url = data.get('source', 'Unknown')
    
    if not user_email:
        return jsonify({"success": False, "error": "Email is required"}), 400

    # Load from your .env file
    my_email = os.environ.get('EMAIL_ADDRESS')
    my_password = os.environ.get('EMAIL_PASSWORD') # MUST BE AN APP PASSWORD
    
    if not my_email or not my_password:
        return jsonify({"success": False, "error": "Server email config missing"}), 500

    try:
        # --- 1. EMAIL TO THE CUSTOMER ---
        msg_customer = MIMEMultipart()
        msg_customer['From'] = f"Bubbl.ooo <{my_email}>"
        msg_customer['To'] = user_email
        msg_customer['Subject'] = "You're on the list! 🎉"
        
        greeting = f"Hi {user_name}," if user_name else "Hi there,"
        customer_body = f"""{greeting}
        
Thank you for joining the Bubbl.ooo waitlist! We're thrilled to have you on board.

We are working hard to finalize the best AI chatbot platform for your business, and you will be the first to know the moment we launch.

Best regards,
The Bubbl.ooo Team
https://bubbl.ooo
"""
        msg_customer.attach(MIMEText(customer_body, 'plain'))

        # --- 2. NOTIFICATION EMAIL TO YOURSELF ---
        msg_admin = MIMEMultipart()
        msg_admin['From'] = f"Waitlist Bot <{my_email}>"
        msg_admin['To'] = my_email
        msg_admin['Subject'] = f"New Waitlist Signup: {user_email}"
        
        admin_body = f"""New waitlist signup received!
        
Name: {user_name if user_name else 'N/A'}
Email: {user_email}
Source Page: {source_url}
"""
        msg_admin.attach(MIMEText(admin_body, 'plain'))

        # --- SEND EMAILS VIA GOOGLE SMTP ---
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(my_email, my_password)
        
        # Send both
        server.send_message(msg_customer)
        server.send_message(msg_admin)
        
        server.quit()

        return jsonify({"success": True})

    except Exception as e:
        print(f"SMTP Error: {e}")
        return jsonify({"success": False, "error": "Failed to send email."}), 500
    
@views_bp.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('views_bp.dashboard'))
    return redirect(url_for('auth.login'))

@views_bp.route('/features')
def features():
    return redirect(f"{MARKETING_SITE}/features.html")

@views_bp.route('/pricing')
def pricing():
    current_plan = 'free'
    if session.get('user_id') and session.get('org_id'):
        org = Organization.query.get(session['org_id'])
        if org and org.plan:
            current_plan = org.plan
    return render_template('pricing.html', current_plan=current_plan)

@views_bp.route('/export_leads')
def export_leads():
    if not session.get('user_id'): 
        return redirect(url_for('auth.login'))
        
    # Find all bots belonging to the user's organization + the shared platform bot
    org_bots = Bot.query.filter_by(org_id=session.get('org_id')).all()
    bot_ids = [bot.id for bot in org_bots]
    platform_bot = Bot.query.filter_by(bot_type='platform').first()
    if platform_bot and platform_bot.id not in bot_ids:
        bot_ids.append(platform_bot.id)
    
    # Fetch all leads
    leads = Lead.query.filter(Lead.bot_id.in_(bot_ids)).order_by(Lead.captured_at.desc()).all()

    # Generate the CSV in memory
    si = io.StringIO()
    cw = csv.writer(si)
    
    # Write the Header Row
    cw.writerow(['Name', 'Email', 'Phone', 'Source Bot', 'Captured At'])
    
    # Write the Data Rows
    for lead in leads:
        captured_time = lead.captured_at.strftime('%Y-%m-%d %H:%M:%S') if lead.captured_at else 'Unknown'
        bot_name = lead.bot_ref.bot_name if lead.bot_ref else 'Unknown'
        cw.writerow([
            lead.name, 
            lead.email, 
            lead.phone or 'N/A', 
            bot_name, 
            captured_time
        ])

    # Create the response and tell the browser it's a file download
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=bubbl_leads_export.csv"
    output.headers["Content-type"] = "text/csv"
    
    return output

@views_bp.route('/leads')
def leads_dashboard():
    if not session.get('user_id'): 
        return redirect(url_for('auth.login'))
        
    # Find all bots belonging to the user's organization + the shared platform bot
    org_bots = Bot.query.filter_by(org_id=session.get('org_id')).all()
    bot_ids = [bot.id for bot in org_bots]
    platform_bot = Bot.query.filter_by(bot_type='platform').first()
    if platform_bot and platform_bot.id not in bot_ids:
        bot_ids.append(platform_bot.id)
    
    # Fetch all leads captured by these bots, newest first
    leads = Lead.query.filter(Lead.bot_id.in_(bot_ids)).order_by(Lead.captured_at.desc()).all()

    return render_template('leads.html', leads=leads)

# ═══════════════════════════════════════════
# CONVERSATIONS HUB — Full chat history for bot owners
# ═══════════════════════════════════════════

@views_bp.route('/conversations')
def conversations_hub():
    """Show all bots the user owns with conversation stats."""
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))

    from models.models import ChatMessage, Lead

    # Get all bots in the org + the shared platform bot
    org_bots = Bot.query.filter_by(org_id=session.get('org_id')).all()
    platform_bot = Bot.query.filter_by(bot_type='platform').first()
    if platform_bot and platform_bot.id not in [b.id for b in org_bots]:
        org_bots = list(org_bots) + [platform_bot]

    bots_with_stats = []
    for bot in org_bots:
        # Count unique sessions
        total_sessions = db.session.query(
            func.count(func.distinct(ChatMessage.session_id))
        ).filter_by(bot_id=bot.id).scalar() or 0

        # Count total messages
        total_messages = ChatMessage.query.filter_by(bot_id=bot.id).count()

        # Count leads captured
        total_leads = Lead.query.filter_by(bot_id=bot.id).count()

        # Last conversation time
        last_activity = db.session.query(
            func.max(ChatMessage.created_at)
        ).filter_by(bot_id=bot.id).scalar()

        # Average session duration — simple Python approach (no complex SQL)
        avg_duration_mins = 0
        if total_sessions > 0:
            sessions_data = db.session.query(
                func.min(ChatMessage.created_at).label('first_msg'),
                func.max(ChatMessage.created_at).label('last_msg'),
            ).filter_by(bot_id=bot.id).group_by(ChatMessage.session_id).all()

            total_secs = 0
            for s in sessions_data:
                if s.first_msg and s.last_msg:
                    total_secs += (s.last_msg - s.first_msg).total_seconds()
            avg_duration_mins = round((total_secs / len(sessions_data)) / 60, 1) if sessions_data else 0

        bots_with_stats.append({
            'bot': bot,
            'total_sessions': total_sessions,
            'total_messages': total_messages,
            'total_leads': total_leads,
            'last_activity': last_activity,
            'avg_duration_mins': avg_duration_mins,
        })

    return render_template('conversations_bots.html', bots_with_stats=bots_with_stats)


@views_bp.route('/conversations/<int:bot_id>')
def conversations_list(bot_id):
    """Show all conversation sessions for a specific bot with rich stats."""
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))

    from models.models import ChatMessage, Lead

    bot = Bot.query.filter_by(id=bot_id, org_id=session.get('org_id')).first()
    if not bot:
        bot = Bot.query.filter_by(id=bot_id, bot_type='platform').first()
    if not bot:
        flash("Bot not found.", "error")
        return redirect(url_for('views_bp.conversations_hub'))

    from sqlalchemy import or_
    if bot.bot_type == 'platform':
        bot_filter = or_(ChatMessage.bot_id == bot.id, ChatMessage.bot_id.is_(None))
    else:
        bot_filter = (ChatMessage.bot_id == bot.id)

    # Get all sessions with aggregated stats
    sessions_query = db.session.query(
        ChatMessage.session_id,
        func.count(ChatMessage.id).label('message_count'),
        func.min(ChatMessage.created_at).label('started_at'),
        func.max(ChatMessage.created_at).label('last_message_at'),
        func.sum(ChatMessage.tokens_used).label('total_tokens'),
    ).filter(bot_filter).group_by(
        ChatMessage.session_id
    ).order_by(func.max(ChatMessage.created_at).desc()).all()

    conversations = []
    for sess in sessions_query:
        # Duration in minutes
        duration_secs = 0
        if sess.started_at and sess.last_message_at:
            duration_secs = (sess.last_message_at - sess.started_at).total_seconds()
        duration_mins = round(duration_secs / 60, 1) if duration_secs > 0 else 0

        # First user message as preview
        first_msg = ChatMessage.query.filter(
            bot_filter, ChatMessage.session_id == sess.session_id, ChatMessage.role == 'user'
        ).order_by(ChatMessage.created_at.asc()).first()

        # Check if a lead was captured in this session
        lead = Lead.query.join(ChatMessage, ChatMessage.lead_id == Lead.id).filter(
            ChatMessage.session_id == sess.session_id,
            bot_filter
        ).first()

        # If no lead found via ChatMessage.lead_id, check by session's captured leads
        if not lead:
            # Check if any message in this session has a lead_id
            msg_with_lead = ChatMessage.query.filter(
                ChatMessage.session_id == sess.session_id,
                bot_filter,
                ChatMessage.lead_id.isnot(None)
            ).first()
            if msg_with_lead:
                lead = Lead.query.get(msg_with_lead.lead_id)

        # Count user messages and bot messages separately for response time calc
        user_msg_count = ChatMessage.query.filter(
            bot_filter, ChatMessage.session_id == sess.session_id, ChatMessage.role == 'user'
        ).count()
        bot_msg_count = ChatMessage.query.filter(
            bot_filter, ChatMessage.session_id == sess.session_id, ChatMessage.role == 'bot'
        ).count()

        # Average response time: total latency tracked on bot / interaction count
        # Or approximate from message timestamps
        avg_response_ms = 0
        if bot.interaction_count and bot.total_latency:
            avg_response_ms = int((bot.total_latency / bot.interaction_count) * 1000)

        # Visitor IP — first recorded IP in this session
        ip_row = ChatMessage.query.filter(
            ChatMessage.bot_id == bot_id,
            ChatMessage.session_id == sess.session_id,
            ChatMessage.ip_address.isnot(None)
        ).first()
        visitor_ip = ip_row.ip_address if ip_row else None

        conversations.append({
            'session_id': sess.session_id,
            'message_count': sess.message_count,
            'user_messages': user_msg_count,
            'bot_messages': bot_msg_count,
            'started_at': sess.started_at,
            'last_message_at': sess.last_message_at,
            'duration_mins': duration_mins,
            'total_tokens': sess.total_tokens or 0,
            'lead': lead,
            'ip_address': visitor_ip,
            'preview': (first_msg.content[:100] + '...') if first_msg and len(first_msg.content) > 100 else (first_msg.content if first_msg else 'No messages'),
            'avg_response_ms': avg_response_ms,
        })

    # Aggregate stats for the header
    total_conversations = len(conversations)
    total_messages = sum(c['message_count'] for c in conversations)
    total_leads = sum(1 for c in conversations if c['lead'])
    avg_duration = round(sum(c['duration_mins'] for c in conversations) / max(total_conversations, 1), 1)

    return render_template('conversations_list.html',
        bot=bot,
        conversations=conversations,
        total_conversations=total_conversations,
        total_messages=total_messages,
        total_leads=total_leads,
        avg_duration=avg_duration,
    )


@views_bp.route('/conversations/<int:bot_id>/<session_id>')
def conversation_detail(bot_id, session_id):
    """View a full conversation transcript with metadata."""
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))

    from models.models import ChatMessage, Lead

    bot = Bot.query.filter_by(id=bot_id, org_id=session.get('org_id')).first()
    if not bot:
        flash("Bot not found.", "error")
        return redirect(url_for('views_bp.conversations_hub'))

    messages = ChatMessage.query.filter_by(
        bot_id=bot_id, session_id=session_id
    ).order_by(ChatMessage.created_at.asc()).all()

    if not messages:
        flash("Conversation not found.", "error")
        return redirect(url_for('views_bp.conversations_list', bot_id=bot_id))

    # Session metadata
    started_at = messages[0].created_at if messages else None
    ended_at = messages[-1].created_at if messages else None
    duration_secs = (ended_at - started_at).total_seconds() if started_at and ended_at else 0
    duration_mins = round(duration_secs / 60, 1)

    total_tokens = sum(m.tokens_used or 0 for m in messages)
    user_msg_count = sum(1 for m in messages if m.role == 'user')
    bot_msg_count = sum(1 for m in messages if m.role == 'bot')

    # Lead info
    lead = None
    msg_with_lead = next((m for m in messages if m.lead_id), None)
    if msg_with_lead:
        lead = Lead.query.get(msg_with_lead.lead_id)

    # Calculate per-message response times (time between user msg and next bot msg)
    response_times = []
    for i, msg in enumerate(messages):
        if msg.role == 'user' and i + 1 < len(messages) and messages[i + 1].role == 'bot':
            if msg.created_at and messages[i + 1].created_at:
                rt = (messages[i + 1].created_at - msg.created_at).total_seconds()
                response_times.append(rt)

    avg_response_sec = round(sum(response_times) / len(response_times), 1) if response_times else 0

    return render_template('conversation_detail.html',
        bot=bot,
        messages=messages,
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        duration_mins=duration_mins,
        total_tokens=total_tokens,
        user_msg_count=user_msg_count,
        bot_msg_count=bot_msg_count,
        lead=lead,
        avg_response_sec=avg_response_sec,
    )


@views_bp.route('/compare')
@views_bp.route('/compare/<competitor>')
def compare(competitor=None):
    if competitor:
        clean_name = competitor.replace('.html', '')
        return redirect(f"{MARKETING_SITE}/compare/{clean_name}.html")
    return redirect(f"{MARKETING_SITE}/compare/")

@views_bp.route('/contact')
def contact():
    return redirect(f"{MARKETING_SITE}/contact.html")

@views_bp.route('/dashboard')
def dashboard():
    if not session.get('user_id'): return redirect(url_for('auth.login'))
        
    my_bots = Bot.query.filter_by(created_by=session['user_id']).all()
    all_org_bots = Bot.query.filter(Bot.org_id == session['org_id'], Bot.created_by != session['user_id']).all()
    member_count = User.query.filter_by(org_id=session.get('org_id')).count()

    # Include the platform bot (Bubbl's public support bot) so users can interact with it
    platform_bot = Bot.query.filter_by(bot_type='platform').first()

    org_bots = []
    for bot in all_org_bots:
        if bot.visibility == 'public':
            org_bots.append(bot)
        elif bot.visibility == 'private' and session.get('role') == 'admin':
            org_bots.append(bot)

    return render_template('dashboard.html', 
                           my_bots=my_bots, 
                           org_bots=org_bots, 
                           member_count=member_count,
                           platform_bot=platform_bot)

@views_bp.route('/set_active_bot/<int:bot_id>')
def set_active_bot(bot_id):
    if not session.get('user_id'): return redirect(url_for('auth.login'))
        
    target_bot = Bot.query.get(bot_id)
    if target_bot and target_bot.org_id == session.get('org_id'):
        is_creator = target_bot.created_by == session.get('user_id')
        is_unlocked = target_bot.id in session.get('unlocked_bots', [])
        
        if target_bot.visibility == 'public' or is_creator or is_unlocked:
            session['active_bot_id'] = target_bot.id
            session['active_bot_name'] = target_bot.bot_name
            session['lead_capture_timing'] = target_bot.lead_capture_timing
            session['custom_form_fields'] = json.dumps(getattr(target_bot, 'custom_form_fields', []) or [])
            
            if hasattr(target_bot, 'ui_settings') and target_bot.ui_settings:
                session['theme_color'] = target_bot.ui_settings.theme_color
                session['header_color'] = target_bot.ui_settings.header_color
                session['theme_mode'] = target_bot.ui_settings.theme_mode
                session['glass_opacity'] = target_bot.ui_settings.glass_opacity
                session['glass_blur'] = target_bot.ui_settings.glass_blur
            else:
                session['theme_color'] = getattr(target_bot, 'theme_color', '#E8722A')
                session['header_color'] = getattr(target_bot, 'header_color', '#FFFFFF')
                session['theme_mode'] = getattr(target_bot, 'theme_mode', 'light')
                session['glass_opacity'] = 35
                session['glass_blur'] = 25
        else:
            flash("Security Error: This Bot is classified. Decryption key required.", "error")
            
    return redirect(url_for('views_bp.dashboard'))


@views_bp.route('/connect_support')
def connect_support():
    """Switch the chat widget to the Bubbl platform support bot."""
    if not session.get('user_id'):
        return redirect(url_for('auth.login'))

    platform_bot = Bot.query.filter_by(bot_type='platform').first()
    if platform_bot:
        session['active_bot_id'] = platform_bot.id
        session['active_bot_name'] = platform_bot.bot_name
        session['lead_capture_timing'] = platform_bot.lead_capture_timing or 'disabled'
        session['custom_form_fields'] = '[]'

        # Reset UI settings to platform defaults
        if hasattr(platform_bot, 'ui_settings') and platform_bot.ui_settings:
            session['theme_color'] = platform_bot.ui_settings.theme_color
            session['header_color'] = platform_bot.ui_settings.header_color
            session['theme_mode'] = platform_bot.ui_settings.theme_mode
        else:
            session['theme_color'] = '#E8722A'
            session['header_color'] = '#FFFFFF'
            session['theme_mode'] = 'light'
    else:
        # No platform bot exists — just clear active bot so widget uses platform fallback
        session.pop('active_bot_id', None)
        session.pop('active_bot_name', None)

    return redirect(url_for('views_bp.dashboard'))


@views_bp.route('/unlock_bot/<int:bot_id>', methods=['POST'])
def unlock_bot(bot_id):
    if session.get('role') != 'admin':
        flash("Clearance Error: Administrator privileges required.", "error")
        return redirect(url_for('views_bp.dashboard'))
    
    submitted_key = request.form.get('access_key', '').upper()
    target_bot = Bot.query.get(bot_id)
    
    
    if target_bot and target_bot.access_key == submitted_key:
        unlocked = session.get('unlocked_bots', [])
        if bot_id not in unlocked:
            unlocked.append(bot_id)
        session['unlocked_bots'] = unlocked
        
        session['active_bot_id'] = target_bot.id
        session['active_bot_name'] = target_bot.bot_name
        session['lead_capture_timing'] = target_bot.lead_capture_timing
        session['custom_form_fields'] = getattr(target_bot, 'custom_form_fields', '')
        
        if hasattr(target_bot, 'ui_settings') and target_bot.ui_settings:
            session['theme_color'] = target_bot.ui_settings.theme_color
            session['header_color'] = target_bot.ui_settings.header_color
            session['theme_mode'] = target_bot.ui_settings.theme_mode
            session['glass_opacity'] = target_bot.ui_settings.glass_opacity
            session['glass_blur'] = target_bot.ui_settings.glass_blur
        else:
            session['theme_color'] = getattr(target_bot, 'theme_color', '#E8722A')
            session['header_color'] = getattr(target_bot, 'header_color', '#FFFFFF')
            session['theme_mode'] = getattr(target_bot, 'theme_mode', 'light')
            session['glass_opacity'] = 35
            session['glass_blur'] = 25
            
        flash(f"Decrypted: Access granted to {target_bot.bot_name}", "success")
    else:
        flash("Encryption Error: Invalid Access Key.", "error")
    
    return redirect(url_for('views_bp.dashboard'))

@views_bp.route('/embed/<int:bot_id>')
def embed_bot(bot_id):
    target_bot = Bot.query.get_or_404(bot_id)
    response = make_response(render_template('embed_chat.html', bot=target_bot))
    
    # 1. Strip the legacy X-Frame-Options
    response.headers.pop('X-Frame-Options', None)
    
    # 2. Enforce the Domain Lock via CSP frame-ancestors
    allowed = (target_bot.allowed_domains or '').strip()
    
    if allowed:
        # Parse allowed domains — normalize to proper origins for frame-ancestors
        # Users might enter: "github.io/path", "https://example.com", "example.com" etc.
        # frame-ancestors needs: "https://example.com" (scheme + host, no path)
        from urllib.parse import urlparse
        origins = []
        for domain in allowed.replace(',', ' ').split():
            domain = domain.strip()
            if not domain:
                continue
            # If it's just a wildcard, allow all
            if domain == '*':
                origins = ['*']
                break
            # Add scheme if missing
            if not domain.startswith('http://') and not domain.startswith('https://'):
                domain = 'https://' + domain
            parsed = urlparse(domain)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin and parsed.netloc:
                origins.append(origin)
        
        if origins:
            origins_str = ' '.join(origins)
            response.headers['Content-Security-Policy'] = f"frame-ancestors 'self' {origins_str}"
        else:
            response.headers['Content-Security-Policy'] = "frame-ancestors *"
    else:
        # No domains specified = allow embedding anywhere (standard SaaS behavior)
        response.headers['Content-Security-Policy'] = "frame-ancestors *"
        
    return response

@views_bp.route('/bot/<int:bot_id>/integrate')
def integrate_bot(bot_id):
    if not session.get('user_id'): 
        return redirect(url_for('auth.login'))
    target_bot = Bot.query.get_or_404(bot_id)
    if target_bot.created_by != session.get('user_id') and session.get('role') != 'admin':
        flash("Access Denied.", "error")
        return redirect(url_for('views_bp.dashboard'))
    return render_template('integrate.html', bot=target_bot)

@views_bp.route('/bot/<int:bot_id>/update_security', methods=['POST'])
def update_bot_security(bot_id):
    if not session.get('user_id'): 
        return redirect(url_for('auth.login'))
    target_bot = Bot.query.get_or_404(bot_id)
    if target_bot.created_by != session.get('user_id') and session.get('role') != 'admin':
        flash("Access Denied.", "error")
        return redirect(url_for('views_bp.dashboard'))
    allowed_domains = request.form.get('allowed_domains', '').strip()
    target_bot.allowed_domains = allowed_domains
    db.session.commit()
    flash("Security settings updated.", "success")
    return redirect(url_for('views_bp.integrate_bot', bot_id=bot_id))

@views_bp.route('/bot/<int:bot_id>/widget/feedback', methods=['POST'])
def submit_feedback(bot_id):  
    # Feedback can come from:
    # 1. Logged-in admin/user testing their bot (has session)
    # 2. End-user in the embed widget (no session, but has lead_id)
    # Both are allowed — no login required for widget feedback.

    data = request.json or {}
    
    rating = data.get('rating')
    comment = data.get('comment', '')
    lead_id = data.get('lead_id') 

    if not rating:
        return jsonify({"error": "Missing rating"}), 400

    try:
        new_feedback = Feedback(
            bot_id=bot_id,
            rating=int(rating),
            comment=comment,
            lead_id=lead_id
        )
        
        db.session.add(new_feedback)
        db.session.commit()

        return jsonify({"success": True, "message": "Feedback saved."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@views_bp.route('/api/platform-feedback', methods=['POST'])
def submit_platform_feedback():
    """
    Feedback for the public/marketing Bubbl assistant (no specific bot attached).
    No login required, no bot_id needed. Stored with bot_id = NULL.
    """
    data = request.json or {}
    rating = data.get('rating')
    comment = data.get('comment', '')

    if not rating:
        return jsonify({"error": "Missing rating"}), 400

    try:
        new_feedback = Feedback(
            bot_id=None,   # Platform-level feedback
            rating=int(rating),
            comment=comment,
            lead_id=None,
        )
        db.session.add(new_feedback)
        db.session.commit()
        return jsonify({"success": True, "message": "Feedback saved."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@views_bp.route('/api/bot_avatar/<int:bot_id>')
def api_bot_avatar(bot_id):
    # Cached for 5 min — this endpoint is hit on every page load.
    # We store "" to represent "no avatar" so misses are cached too
    # (avoids re-querying the DB for bots that have no avatar).
    cache_key = f"bot_avatar_{bot_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        if cached == "":
            return jsonify({"error": "No avatar"}), 404
        return jsonify({"avatar": cached})

    bot = Bot.query.get(bot_id)
    avatar = None
    if bot and hasattr(bot, 'ui_settings') and bot.ui_settings and bot.ui_settings.avatar_base64:
        avatar = bot.ui_settings.avatar_base64

    cache.set(cache_key, avatar or "", timeout=300)
    if avatar:
        return jsonify({"avatar": avatar})
    return jsonify({"error": "No avatar"}), 404