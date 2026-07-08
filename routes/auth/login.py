import bcrypt
from flask import render_template, request, redirect, url_for, session, flash
from models.models import db, User
from utils.mail_helper import send_otp_email, generate_otp
from extensions import limiter
from . import auth_bp 
import os

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])  # Prevents brute force
def login():
    if request.method == 'POST':
        # Safely grab email and password, stripping invisible spaces
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        # --- 1. SUPER ADMIN CHECK (Bypasses Database entirely) ---
        super_admin_env_email = os.environ.get('SUPER_ADMIN_MAIL')
        super_admin_env_hash = os.environ.get('SUPER_ADMIN_HASH')
        
        if super_admin_env_email and email.lower() == super_admin_env_email.lower():
            if super_admin_env_hash and bcrypt.checkpw(password.encode('utf-8'), super_admin_env_hash.encode('utf-8')):
                # Super Admin Authenticated!
                session['user_id'] = 0 
                session['user_name'] = "Super Admin"
                session['org_name'] = "Platform Admin"
                session['org_id'] = 0 
                session['role'] = 'super_admin'
                flash("God Mode Activated.", "success")
                return redirect(url_for('views_bp.super_admin_dashboard'))
            else:
                flash("Incorrect Super Admin password.", "error")
                return redirect(url_for('auth.login'))
        # ---------------------------------------------------------
        
        # 2. Look up the normal user
        user = User.query.filter_by(email=email).first()
        
        # 3. CATCH: Wrong Email
        if not user:
            flash("No account found with that email address.", "warning")
            return redirect(url_for('auth.login'))
            
        # 4. CATCH: Wrong Password
        if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
            flash("Incorrect password. Please try again.", "error")
            return redirect(url_for('auth.login'))
            
        # 5. Enforce Verification
        if not user.is_verified:
            otp_code = generate_otp()
            user.set_otp(otp_code)
            db.session.commit()
            send_otp_email(user.email, otp_code)
            session['verify_email'] = user.email
            flash("Please verify your email first. A new code has been sent.", "info")
            return redirect(url_for('auth.verify_otp'))

        # 6. Proceed with normal login
        session['user_id'] = user.id
        session['user_name'] = user.name
        session['org_name'] = user.organization.name
        session['org_id'] = user.org_id
        session['role'] = user.role
        
        flash("Access granted.", "success")
        # Honor ?next= for post-login redirect (e.g. back to /pricing).
        # Only allow internal relative paths to prevent open-redirect attacks.
        next_url = request.args.get('next') or request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('views_bp.dashboard'))
            
    return render_template('login.html')

@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
@limiter.limit("3 per minute", methods=["POST"])  # Prevents email spam
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')

    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()
    
    if user:
        # Generate OTP, save it with timestamp, and email it
        otp_code = generate_otp()
        user.set_otp(otp_code)
        db.session.commit()
        
        send_otp_email(user.email, otp_code)
        session['reset_email'] = user.email
        flash("If an account exists, a reset code has been sent.", "info")
        return redirect(url_for('auth.reset_password'))

    flash("Enter a valid email address.", "error")
    return redirect(url_for('auth.forgot_password'))

@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    email = session.get('reset_email')
    
    if not email:
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        new_password = request.form.get('new_password')
        
        if not otp_entered or not new_password:
            flash("Please provide the OTP and a new password.", "error")
            return redirect(url_for('auth.reset_password'))

        user = User.query.filter_by(email=email).first()
        
        if user and user.is_otp_valid(otp_entered):
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user.password_hash = hashed_password
            user.clear_otp()
            db.session.commit()
            
            session.pop('reset_email', None)
            flash("Password updated successfully! You can now log in.", "success")
            return redirect(url_for('auth.login'))
        else:
            flash("Invalid or expired reset code. Codes expire after 10 minutes.", "error")

    return render_template('reset_password.html', email=email)

