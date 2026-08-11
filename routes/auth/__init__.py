from flask import Blueprint
auth_bp = Blueprint('auth', __name__)
from . import login, register, logout

# --- Google OAuth routes ---
from .google_auth import register_google_oauth, google_login, google_callback

auth_bp.add_url_rule('/auth/google/login', 'google_login', google_login)
auth_bp.add_url_rule('/auth/google/callback', 'google_callback', google_callback)