import bcrypt
from flask import render_template, request, redirect, url_for, session, flash, current_app
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email, Length, ValidationError
from sqlalchemy.exc import IntegrityError

from models.models import db, User, Organization
from utils.mail_helper import send_otp_email, generate_otp
from extensions import limiter
from . import auth_bp  


def password_strength(form, field):
    """Ensure password has at least one letter and one digit."""
    pwd = field.data or ''
    has_letter = any(c.isalpha() for c in pwd)
    has_digit = any(c.isdigit() for c in pwd)
    if not (has_letter and has_digit):
        raise ValidationError("Password must contain at least one letter and one number.")


class RegistrationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[
        DataRequired(),
        Length(min=8, message="Password must be at least 8 characters."),
        password_strength,
    ])
    confirm_password = PasswordField("Confirm Password", validators=[
        DataRequired(message="Please confirm your password."),
    ])

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("Passwords do not match.")

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
            )
            new_user.set_otp(otp_code)
            
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

    # Form validation failed — flash the errors so user sees what's wrong
    if request.method == 'POST' and form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(error, "error")

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

        if user and user.is_otp_valid(user_otp):
            user.is_verified = True
            user.clear_otp()
            db.session.commit()

            session['user_id'] = user.id
            session['user_name'] = user.name
            session['org_name'] = user.organization.name
            session['org_id'] = user.org_id
            session['role'] = user.role
            session['just_registered'] = True
            session.pop('verify_email', None)

            flash(f"Account verified successfully! Welcome to {current_app.config.get('COMPANY_NAME_FIRST', 'Bubbl')}.{current_app.config.get('COMPANY_LAST_NAME', 'ooo')}", "success")
            return redirect(url_for('views_bp.dashboard'))
        else:
            flash("Invalid or expired verification code. Codes expire after 10 minutes.", "error")

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
        user.set_otp(otp_code)
        db.session.commit()
        
        email_sent = send_otp_email(user.email, otp_code)
        
        if email_sent:
            flash("A fresh verification code has been sent to your email.", "info")
        else:
            flash("Failed to send email. Please try a valid email address.", "error")
    
    return redirect(url_for('auth.verify_otp'))