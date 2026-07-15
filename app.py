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