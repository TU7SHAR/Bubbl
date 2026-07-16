import os
from flask import Flask, request
from models.models import db
from config import Config
from routes.admin import admin_bp
from routes.auth import auth_bp
# from routes.chat_routes import chat_bp
from routes.profile import profile_bp
from routes.embed.views import views_bp
from routes.embed.api import api_bp
from routes.payments import payments_bp
from routes.super_admin import super_admin_bp
from flask_cors import CORS
from extensions import limiter, cache

app = Flask(__name__)
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True  # Required when SameSite is 'None'
app.config.from_object(Config)

# --- CORS: Restrict to your domains only ---
ALLOWED_ORIGINS = [
    "https://bubbl.ooo",
    "https://www.bubbl.ooo",
    "http://168.144.123.62:8080",
    os.getenv('HOST_URL', 'http://localhost:5000'),
]
CORS(app, resources={
    r"/api/chat": {"origins": "*"},          # Embed widget on any domain
    r"/api/lead": {"origins": "*"},          # Lead capture from any domain
    r"/api/platform-feedback": {"origins": "*"},  # Public feedback
    r"/api/bot_avatar/*": {"origins": "*"},  # Avatar fetch from embed
    r"/api/waitlist": {"origins": "*"},      # Marketing site waitlist
    r"/api/*": {"origins": ALLOWED_ORIGINS}, # All other API routes: restricted
})

# --- RATE LIMITER: Prevent abuse of paid APIs ---
limiter.init_app(app)

# --- CACHE: Avoid hitting the DB for the same data every request ---
cache.init_app(app)

UPLOAD_FOLDER = app.config.get('UPLOAD_FOLDER')
SCRAPE_FOLDER = app.config.get('SCRAPE_FOLDER')

if UPLOAD_FOLDER and not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if SCRAPE_FOLDER and not os.path.exists(SCRAPE_FOLDER):
    os.makedirs(SCRAPE_FOLDER)

db.init_app(app)

app.register_blueprint(admin_bp)
app.register_blueprint(auth_bp)
# app.register_blueprint(chat_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(views_bp)
app.register_blueprint(api_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(super_admin_bp)


def _run_auto_migrations():
    """Idempotent migrations — safe to run on every deploy."""
    from sqlalchemy import text
    sqls = [
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS tokens_used INTEGER DEFAULT 0',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS total_latency FLOAT DEFAULT 0.0',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS interaction_count INTEGER DEFAULT 0',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS created_at TIMESTAMP',
        "ALTER TABLE bot ALTER COLUMN custom_form_fields TYPE JSONB USING CASE WHEN custom_form_fields IS NULL OR custom_form_fields = '' THEN '[]'::jsonb ELSE custom_form_fields::jsonb END",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS managed_links JSONB DEFAULT '[]'",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20) DEFAULT 'free'",
        'ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_started_at TIMESTAMP',
        'ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMP',
        'ALTER TABLE organization ADD COLUMN IF NOT EXISTS created_at TIMESTAMP',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP',
        'ALTER TABLE payment ADD COLUMN IF NOT EXISTS user_id INTEGER',
        'ALTER TABLE document ADD COLUMN IF NOT EXISTS created_at TIMESTAMP',
        """CREATE TABLE IF NOT EXISTS chat_message (
            id SERIAL PRIMARY KEY, bot_id INTEGER, lead_id INTEGER,
            session_id VARCHAR(64) NOT NULL, role VARCHAR(10) NOT NULL,
            content TEXT NOT NULL, tokens_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
        'CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message(session_id)',
    ]
    for s in sqls:
        try:
            db.session.execute(text(s))
        except Exception:
            db.session.rollback()
    db.session.commit()


with app.app_context():
    db.create_all()
    _run_auto_migrations()

@app.after_request
def add_security_headers(response):
    # --- FRAME POLICY ---
    # Remove legacy X-Frame-Options (we use CSP frame-ancestors instead)
    if 'X-Frame-Options' in response.headers:
        del response.headers['X-Frame-Options']

    # Only allow framing on /embed/* routes (the widget iframe).
    # All other pages (login, admin, payments) are NOT frameable → prevents clickjacking.
    if 'Content-Security-Policy' not in response.headers:
        if request.path.startswith('/embed/'):
            response.headers['Content-Security-Policy'] = "frame-ancestors *"
        else:
            response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"

    # --- ADDITIONAL SECURITY HEADERS ---
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'

    # HSTS: only on HTTPS (browser will enforce HTTPS for 1 year)
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    return response


@app.before_request
def csrf_protect():
    """
    CSRF protection via Origin/Referer validation for state-changing requests.

    Strategy: For POST/PUT/DELETE/PATCH requests with JSON content-type,
    verify the Origin or Referer header matches our allowed domains.
    Cross-origin sites cannot forge these headers in modern browsers.

    Exemptions:
    - Paddle webhook (external service, verified by HMAC signature)
    - Non-JSON form submissions from our own templates (same-origin)
    - GET requests (safe, no state change)
    - Embed API chat/lead endpoints (called from iframe on third-party sites)
    """
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return  # Only protect state-changing methods

    # Exempt: Paddle webhook (uses signature verification instead)
    if request.path == '/payments/webhook/paddle':
        return

    # Exempt: Public embed endpoints (called from iframes on any site)
    exempt_paths = ('/api/chat', '/api/lead', '/api/platform-feedback', '/api/waitlist')
    if request.path in exempt_paths or request.path.startswith('/bot/') and '/widget/feedback' in request.path:
        return

    # Non-JSON requests (HTML form POST from our templates) — let through
    # These are protected by the form being served from our domain
    content_type = request.content_type or ''
    if 'application/json' not in content_type and 'multipart/form-data' not in content_type.lower():
        return

    # For JSON/multipart requests: validate Origin or Referer
    origin = request.headers.get('Origin', '')
    referer = request.headers.get('Referer', '')

    allowed_origins = {
        'https://bubbl.ooo',
        'https://www.bubbl.ooo',
        'http://168.144.123.62:8080',
        'https://app.bubbl.ooo',
        os.getenv('HOST_URL', 'http://localhost:5000'),
        'http://localhost:5000',
    }

    # Check Origin first (most reliable), then Referer
    if origin:
        if origin in allowed_origins:
            return  # Allowed
    elif referer:
        from urllib.parse import urlparse
        referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
        if referer_origin in allowed_origins:
            return  # Allowed
    else:
        # No Origin AND no Referer — likely same-origin or non-browser client
        # Allow through (server-to-server calls, curl, etc.)
        return

    # If we get here, Origin/Referer didn't match our allowed list
    from flask import jsonify
    return jsonify({"error": "Request blocked: invalid origin."}), 403

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)