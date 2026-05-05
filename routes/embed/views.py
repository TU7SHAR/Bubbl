from flask import Blueprint, render_template, request, session, redirect, url_for, flash, make_response, jsonify
from models.models import Bot, User, Lead, db
from utils.mail_helper import is_valid_email, send_contact_email, send_auto_reply
import csv
import io

views_bp = Blueprint('views_bp', __name__)

@views_bp.route('/')
def index():
    return render_template('index.html')

@views_bp.route('/pricing')
def pricing():
    return render_template('pricing.html')

@views_bp.route('/export_leads')
def export_leads():
    if not session.get('user_id'): 
        return redirect(url_for('auth.login'))
        
    # Find all bots belonging to the user's organization
    org_bots = Bot.query.filter_by(org_id=session.get('org_id')).all()
    bot_ids = [bot.id for bot in org_bots]
    
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
        
    # Find all bots belonging to the user's organization
    org_bots = Bot.query.filter_by(org_id=session.get('org_id')).all()
    bot_ids = [bot.id for bot in org_bots]
    
    # Fetch all leads captured by these bots, newest first
    leads = Lead.query.filter(Lead.bot_id.in_(bot_ids)).order_by(Lead.captured_at.desc()).all()

    return render_template('leads.html', leads=leads)

@views_bp.route('/compare')
@views_bp.route('/compare/<competitor>')
def compare(competitor=None):
    valid_competitors = ['chatbase', 'tidio', 'intercom', 'gupshup']
    if competitor:
        clean_name = competitor.replace('.html', '')
        if clean_name in valid_competitors:
            return render_template(f'compare_{clean_name}.html')
        else:
            return redirect(url_for('views_bp.compare'))
    return render_template('compare.html')

@views_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        raw_email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()

        # 1. Advanced Validation Check
        is_valid, validation_result = is_valid_email(raw_email)
        
        if not is_valid:
            flash(f"Invalid email: {validation_result}", "error")
            return redirect(url_for('views_bp.contact'))
            
        safe_email = validation_result 

        if not name or not message:
            flash("Name and message fields are required.", "error")
            return redirect(url_for('views_bp.contact'))

        # 2. Send the alert to YOUR support team
        admin_notified = send_contact_email(name, safe_email, subject, message)
        
        # 3. If your team got the alert, send the auto-reply to the USER
        if admin_notified:
            # We trigger the auto-reply silently (no need to crash if it fails)
            send_auto_reply(name, safe_email)
            flash("Your message has been sent successfully! Check your inbox for a confirmation.", "success")
        else:
            flash("An internal error occurred while sending your message. Please try again later.", "error")
            
        return redirect(url_for('views_bp.contact'))

    return render_template('contact.html')

@views_bp.route('/dashboard')
def dashboard():
    if not session.get('user_id'): return redirect(url_for('auth.login'))
        
    my_bots = Bot.query.filter_by(created_by=session['user_id']).all()
    all_org_bots = Bot.query.filter(Bot.org_id == session['org_id'], Bot.created_by != session['user_id']).all()
    member_count = User.query.filter_by(org_id=session.get('org_id')).count()

    org_bots = []
    for bot in all_org_bots:
        if bot.visibility == 'public':
            org_bots.append(bot)
        elif bot.visibility == 'private' and session.get('role') == 'admin':
            org_bots.append(bot)

    return render_template('dashboard.html', 
                           my_bots=my_bots, 
                           org_bots=org_bots, 
                           member_count=member_count)

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
        else:
            flash("Security Error: This Bot is classified. Decryption key required.", "error")
            
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
    if getattr(target_bot, 'allowed_domains', None):
        response.headers['Content-Security-Policy'] = f"frame-ancestors 'self' {target_bot.allowed_domains}"
    else:
        response.headers.pop('X-Frame-Options', None)
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

@views_bp.route('/api/bot_avatar/<int:bot_id>')
def api_bot_avatar(bot_id):
    bot = Bot.query.get(bot_id)
    if bot and hasattr(bot, 'ui_settings') and bot.ui_settings and bot.ui_settings.avatar_base64:
        return jsonify({"avatar": bot.ui_settings.avatar_base64})
    return jsonify({"error": "No avatar"}), 404