"""
Google OAuth 2.0 Login — Sign in / Sign up with Gmail.

Flow:
  1. GET /auth/google/login → Redirects user to Google consent screen
  2. GET /auth/google/callback → Google redirects back with auth code
     → Exchange code for user info (email, name)
     → If user exists: log them in
     → If new user: create Org + User, log them in
"""

import os
import logging
from flask import redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth
from models.models import db, User, Organization
from utils.enums import AuthProvider

# OAuth instance (registered in register_google_oauth)
oauth = OAuth()


def register_google_oauth(app):
    """Initialize the Google OAuth client. Called from __init__.py or app setup."""
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile',
        },
    )


def google_login():
    """Redirect the user to Google's OAuth consent screen."""
    # Force HTTPS in redirect URI (Flask behind nginx doesn't know it's HTTPS)
    redirect_uri = url_for('auth.google_callback', _external=True, _scheme='https')
    return oauth.google.authorize_redirect(redirect_uri)


def google_callback():
    """Handle Google's OAuth callback after user grants consent."""
    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        logging.error(f"[google_oauth] Token exchange failed: {e}")
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for('auth.login'))

    # Get user info from the ID token
    user_info = token.get('userinfo')
    if not user_info:
        flash("Could not retrieve your Google account info.", "error")
        return redirect(url_for('auth.login'))

    email = user_info.get('email', '').lower().strip()
    name = user_info.get('name', '') or email.split('@')[0]

    if not email:
        flash("No email found in your Google account.", "error")
        return redirect(url_for('auth.login'))

    # --- SUPER ADMIN CHECK (bypasses DB, matches login.py) ---
    # The super admin is env-based (SUPER_ADMIN_MAIL), NOT a DB user.
    # Without this, logging in via Google with the super admin email would
    # create/log in a normal DB account instead of granting super admin.
    super_admin_email = os.environ.get('SUPER_ADMIN_MAIL')
    if super_admin_email and email == super_admin_email.lower().strip():
        session['user_id'] = -1
        session['user_name'] = "Super Admin"
        session['org_name'] = "Platform Admin"
        session['org_id'] = -1
        session['role'] = 'super_admin'
        flash("God Mode Activated (via Google).", "success")
        return redirect(url_for('super_admin_bp.dashboard'))

    # --- CHECK: Does this user already exist? ---
    user = User.query.filter_by(email=email).first()

    if user:
        # Existing user — check if suspended
        if getattr(user, 'is_suspended', False):
            flash("Your account has been suspended. Contact support.", "error")
            return redirect(url_for('auth.login'))

        # Update auth_provider if they previously used email-only
        if user.auth_provider == 'email':
            user.auth_provider = AuthProvider.GOOGLE
            db.session.commit()

        # Mark as verified (Google already verified the email)
        if not user.is_verified:
            user.is_verified = True
            db.session.commit()

        # Log them in — set the 5 session keys
        _set_login_session(user)
        flash("Signed in with Google.", "success")

    else:
        # --- NEW USER: Create Organization + User ---
        try:
            new_org = Organization(name=f"{name}'s Organization")
            db.session.add(new_org)
            db.session.flush()  # Get org ID without full commit

            new_user = User(
                org_id=new_org.id,
                name=name,
                email=email,
                password_hash=None,  # No password for Google users
                role='admin',        # First user of org is admin
                is_verified=True,    # Google already verified email
                auth_provider=AuthProvider.GOOGLE,
            )
            db.session.add(new_user)
            db.session.commit()

            _set_login_session(new_user)
            session['just_registered'] = True
            flash(f"Welcome to Bubbl! Account created with Google.", "success")

        except Exception as e:
            db.session.rollback()
            logging.error(f"[google_oauth] User creation failed: {e}")
            flash("Error creating your account. Please try again.", "error")
            return redirect(url_for('auth.register'))

    # Redirect to dashboard (or honor ?next= if present)
    next_url = session.pop('google_next_url', None)
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for('views_bp.dashboard'))


def _set_login_session(user):
    """Set the standard 5 session keys after successful authentication."""
    session['user_id'] = user.id
    session['user_name'] = user.name
    session['org_name'] = user.organization.name
    session['org_id'] = user.org_id
    session['role'] = user.role
