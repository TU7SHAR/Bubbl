import os
from flask import Flask
from models.models import db
from config import Config
from routes.admin import admin_bp
from routes.auth import auth_bp
# from routes.chat_routes import chat_bp
from routes.profile import profile_bp
from routes.embed.views import views_bp
from routes.embed.api import api_bp
from flask_cors import CORS

app = Flask(__name__)
app.config.from_object(Config)
CORS(app, resources={r"/api/*": {"origins": "*"}})

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

with app.app_context():
    db.create_all()

@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)