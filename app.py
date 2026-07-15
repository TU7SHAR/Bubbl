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
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

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

with app.app_context():
    db.create_all()
    # Auto-run safe migrations (adds missing columns to existing tables)
    _run_auto_migrations()


def _run_auto_migrations():
    """Idempotent migrations that run on every deploy. Safe to re-run."""
    from sqlalchemy import text
    migrations = [
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS tokens_used INTEGER DEFAULT 0',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS total_latency FLOAT DEFAULT 0.0',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS interaction_count INTEGER DEFAULT 0',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE',
        'ALTER TABLE bot ADD COLUMN IF NOT EXISTS created_at TIMESTAMP',
        'ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20) DEFAULT \'free\'',
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
    for sql in migrations:
        try:
            db.session.execute(text(sql))
        except Exception:
            db.session.rollback()
    db.session.commit()

@app.after_request
def add_security_headers(response):
    if 'X-Frame-Options' in response.headers:
        del response.headers['X-Frame-Options']
        
    # Only open the iframe globally if a specific route hasn't locked it down
    if 'Content-Security-Policy' not in response.headers:
        response.headers['Content-Security-Policy'] = "frame-ancestors *"
        
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)