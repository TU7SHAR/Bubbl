from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plan = db.Column(db.String(20), default='free')  # free, starter, growth, pro
    messages_used = db.Column(db.Integer, default=0)
    messages_reset_at = db.Column(db.DateTime, nullable=True)  # When the monthly counter resets
    paddle_subscription_id = db.Column(db.String(255), nullable=True)
    paddle_customer_id = db.Column(db.String(255), nullable=True)
    users = db.relationship('User', backref='organization', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    otp = db.Column(db.String(6), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)
    bots = db.relationship('Bot', backref='owner', lazy=True)
    role = db.Column(db.String(20), nullable=False, default='member')

class Bot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)    
    bot_name = db.Column(db.String(100), nullable=False)
    store_id = db.Column(db.String(255), unique=False, nullable=True)
    visibility = db.Column(db.String(10), nullable=False, default='public')
    access_key = db.Column(db.String(4), nullable=True)
    documents = db.relationship('Document', backref='bot', lazy=True, cascade="all, delete-orphan")
    scrape_jobs = db.relationship('ScrapeJob', backref='bot_ref', lazy=True, cascade="all, delete-orphan")
    allowed_domains = db.Column(db.String(255), nullable=True)
    bot_type = db.Column(db.String(50), default='general') # 'sales', 'support', 'general', 'custom'
    theme_color = db.Column(db.String(20), default='#10b981') # Default to a nice green or your #8a6535 brown
    system_prompt = db.Column(db.Text, nullable=True)
    lead_capture_timing = db.Column(db.String(20), default='disabled')
    ui_settings = db.relationship('BotUI', backref='bot', uselist=False, cascade="all, delete-orphan")
    leads = db.relationship('Lead', backref='bot_ref', lazy=True, cascade="all, delete-orphan")
    custom_form_fields = db.Column(db.String(500), default="")
    tokens_used = db.Column(db.Integer, default=0)
    total_latency = db.Column(db.Float, default=0.0)
    interaction_count = db.Column(db.Integer, default=0)

class BotUI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False, unique=True)
    
    theme_color = db.Column(db.String(20), default='#E8722A')
    header_color = db.Column(db.String(20), default='#FFFFFF')
    theme_mode = db.Column(db.String(10), default='light')
    avatar_base64 = db.Column(db.Text, nullable=True)    
    glass_opacity = db.Column(db.Integer, default=35)
    glass_blur = db.Column(db.Integer, default=25)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)

class ScrapeJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False)
    url = db.Column(db.String(2048), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending') 
    limit = db.Column(db.Integer, default=20)   
    error_message = db.Column(db.Text, nullable=True)
    logs = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)

class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    custom_data = db.Column(db.JSON, default={})
    captured_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False)
    lead_id = db.Column(db.Integer, db.ForeignKey('lead.id'), nullable=True) # Optional
    
    rating = db.Column(db.Integer, nullable=False) # 1 to 5 stars
    comment = db.Column(db.Text, nullable=True) # Optional text feedback
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Optional: Add a relationship to the Bot model for easy querying later
    bot = db.relationship('Bot', backref=db.backref('feedbacks', lazy=True, cascade="all, delete-orphan"))