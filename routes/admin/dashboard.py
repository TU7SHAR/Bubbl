import bcrypt
from flask import render_template, session, redirect, url_for, flash, request
from models.models import db, Bot, Document, User
from routes.auth.decorators import admin_required
from utils.mail_helper import send_invite_email
from . import admin_bp

@admin_bp.route('/')
@admin_required
def admin_dashboard():
    all_bots = Bot.query.filter_by(org_id=session['org_id']).all()
    
    visible_bots = []
    for bot in all_bots:
        if bot.visibility == 'public' or bot.created_by == session['user_id']:
            visible_bots.append(bot)

    active_bot_id = session.get('active_bot_id')
    active_bot = None
    
    if active_bot_id:
        active_bot = Bot.query.get(active_bot_id)
        if active_bot:
            is_unauthorized = active_bot.visibility == 'private' and active_bot.created_by != session['user_id']
            is_wrong_org = active_bot.org_id != session['org_id']
            
            if is_unauthorized or is_wrong_org:
                active_bot = None
                session.pop('active_bot_id', None)
                session.pop('active_bot_name', None)

    if not active_bot and visible_bots:
        active_bot = visible_bots[0]
        session['active_bot_id'] = active_bot.id
        session['active_bot_name'] = active_bot.bot_name

    files = []
    if active_bot:
        files = [doc.filename for doc in Document.query.filter_by(bot_id=active_bot.id).all()]
        
    return render_template('admin.html', files=files, bots=visible_bots, active_bot=active_bot)

@admin_bp.route('/how-to-embed', methods=['GET'])
def embed_guide():
    # Render the guide template. No specific bot ID needed since this is general documentation!
    return render_template('embed_guide.html')

@admin_bp.route('/select_bot/<int:bot_id>')
@admin_required
def select_bot(bot_id):
    target_bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
    
    if target_bot:
        if target_bot.visibility == 'private' and target_bot.created_by != session['user_id']:
            flash("Security Error: Access Denied to Private Bot.", "error")
            return redirect(url_for('admin_bp.admin_dashboard'))

        session['active_bot_id'] = target_bot.id
        session['active_bot_name'] = target_bot.bot_name 
        flash(f"Context Switched: Now managing '{target_bot.bot_name}'", "success")
    else:
        flash("Security Error: Bot not found.", "error")
        
    return redirect(url_for('admin_bp.admin_dashboard'))


@admin_bp.route('/invite_member', methods=['POST'])
@admin_required
def invite_member():
    if session.get('role') != 'admin':
        flash("Unauthorized action.", "error")
        return redirect(url_for('views_bp.dashboard'))

    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("That email is already associated with an account.", "warning")
        return redirect(url_for('views_bp.dashboard'))
        
    hashed_pwd = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    new_user = User(
        org_id=session.get('org_id'),
        name=name,
        email=email,
        password_hash=hashed_pwd,
        role=role,
        is_verified=True,
        otp=None
    )
    
    db.session.add(new_user)
    db.session.flush()
    
    email_sent = send_invite_email(email, name, password)
    
    if not email_sent:
        db.session.rollback()
        flash("Could not deliver the invite email. User creation aborted.", "warning")
        return redirect(url_for('views_bp.dashboard'))
        
    db.session.commit()
    flash(f"Team member {name} added and invited successfully!", "success")
    return redirect(url_for('views_bp.dashboard'))