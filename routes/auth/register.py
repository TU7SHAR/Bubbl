import bcrypt
from flask import config, render_template, request, redirect, url_for, session, flash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email
from sqlalchemy.exc import IntegrityError

from models.models import db, User, Organization
from utils.mail_helper import send_otp_email, generate_otp
from extensions import limiter
from . import auth_bp  

class RegistrationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])  # Prevents registration spam
def register():
    # --- UTM CAPTURE: Save UTM params from URL into session ---
    # Works when user lands on /register?utm_source=google&utm_medium=cpc&utm_campaign=launch
    utm_params = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']
    for param in utm_params:
        val = request.args.get(param)
        if val:
            session[param] = val

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            hashed_pwd = bcrypt.hashpw(
                form.password.data.encode('utf-8'), 
                bcrypt.gensalt()
            ).decode('utf-8')
            
            org_name_input = f"{form.name.data}'s Organization"
            new_org = Organization(name=org_name_input)
            db.session.add(new_org)
            db.session.commit()

            otp_code = generate_otp()
            new_user = User(
                org_id=new_org.id,
                name=form.name.data, 
                email=form.email.data, 
                password_hash=hashed_pwd, 
                role='admin', 
                is_verified=False,
                otp=otp_code
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            email_sent = send_otp_email(new_user.email, otp_code)
            
            session['verify_email'] = new_user.email 
            
            if email_sent:
                flash("Account created! Please check your email for the verification code.", "success")
            else:
                flash("Account created, but the email could not be delivered. Please log in to try resending.", "error")
                
            return redirect(url_for('auth.verify_otp'))
            
        except IntegrityError:
            db.session.rollback()
            flash("Email already registered.", "error")
            return redirect(url_for('auth.register'))
            
    return render_template('register.html', form=form)

@auth_bp.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('verify_email')
    
    if not email:
        flash("Session expired. Please log in to request a new code.", "error")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        user = User.query.filter_by(email=email).first()

        if user and user.otp == user_otp:
            user.is_verified = True
            user.otp = None
            db.session.commit()

            session['user_id'] = user.id
            session['user_name'] = user.name
            session['org_name'] = user.organization.name
            session['org_id'] = user.org_id
            session['role'] = user.role
            session['just_registered'] = True
            session.pop('verify_email', None)

            flash(f"Account verified successfully! Welcome to {{config.COMPANY_NAME_FIRST}}.{{config.COMPANY_LAST_NAME}}", "success")
            return redirect(url_for('views_bp.dashboard'))
        else:
            flash("Invalid or expired verification code.", "error")

    return render_template('verify_otp.html', email=email)

@auth_bp.route('/resend_otp')
@limiter.limit("3 per minute")  # Prevents OTP email flood
def resend_otp():
    email = session.get('verify_email')
    
    if not email:
        flash("Session expired. Please log in to request a new code.", "error")
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    
    if user and not user.is_verified:
        otp_code = generate_otp()
        user.otp = otp_code
        db.session.commit()
        
        email_sent = send_otp_email(user.email, otp_code)
        
        if email_sent:
            flash("A fresh verification code has been sent to your email.", "info")
        else:
            flash("Failed to send email. Please try a valid email address.", "error")
    
    return redirect(url_for('auth.verify_otp'))