from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()


# ═══════════════════════════════════════════
# ORGANIZATION — Team/Company container
# ═══════════════════════════════════════════
class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plan = db.Column(db.String(20), default='free')  # free, starter, growth, pro
    messages_used = db.Column(db.Integer, default=0)
    messages_reset_at = db.Column(db.DateTime, nullable=True)
    paddle_subscription_id = db.Column(db.String(255), nullable=True)
    paddle_customer_id = db.Column(db.String(255), nullable=True)

    # --- SUBSCRIPTION LIFECYCLE ---
    subscription_status = db.Column(db.String(20), default='free')   # free, active, canceled
    subscription_started_at = db.Column(db.DateTime, nullable=True)
    subscription_ends_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    users = db.relationship('User', backref='organization', lazy=True)


# ═══════════════════════════════════════════
# USER — Individual account
# ═══════════════════════════════════════════
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)  # Nullable for Google OAuth users
    otp = db.Column(db.String(6), nullable=True)
    otp_created_at = db.Column(db.DateTime, nullable=True)
    is_verified = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(20), nullable=False, default='member')
    auth_provider = db.Column(db.String(20), default='email')  # 'email' or 'google'
    is_suspended = db.Column(db.Boolean, default=False)  # Admin can suspend users
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    bots = db.relationship('Bot', backref='owner', lazy=True)
    payments = db.relationship('Payment', backref='payer', lazy=True)

    def is_otp_valid(self, submitted_otp, expiry_minutes=10):
        """Check if OTP matches and hasn't expired (default: 10 min TTL)."""
        if not self.otp or not self.otp_created_at:
            return False
        if self.otp != submitted_otp:
            return False
        now = datetime.now(timezone.utc)
        otp_time = self.otp_created_at
        if otp_time.tzinfo is None:
            otp_time = otp_time.replace(tzinfo=timezone.utc)
        elapsed = now - otp_time
        if elapsed.total_seconds() > (expiry_minutes * 60):
            return False
        return True

    def set_otp(self, otp_code):
        """Set OTP with timestamp for expiration tracking."""
        self.otp = otp_code
        self.otp_created_at = datetime.now(timezone.utc)

    def clear_otp(self):
        """Clear OTP after successful verification."""
        self.otp = None
        self.otp_created_at = None


# ═══════════════════════════════════════════
# BOT — AI Chatbot agent
# ═══════════════════════════════════════════
class Bot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bot_name = db.Column(db.String(100), nullable=False)
    store_id = db.Column(db.String(255), unique=False, nullable=True)
    visibility = db.Column(db.String(10), nullable=False, default='public')
    access_key = db.Column(db.String(4), nullable=True)
    allowed_domains = db.Column(db.String(255), nullable=True)
    bot_type = db.Column(db.String(50), default='general')
    system_prompt = db.Column(db.Text, nullable=True)
    lead_capture_timing = db.Column(db.String(20), default='disabled')
    custom_form_fields = db.Column(db.JSON, default=[])
    managed_links = db.Column(db.JSON, default=[])  # Clickable button links for chat responses
    is_active = db.Column(db.Boolean, default=True)  # Admin can disable bots

    # --- USAGE METRICS ---
    tokens_used = db.Column(db.Integer, default=0)
    total_latency = db.Column(db.Float, default=0.0)
    interaction_count = db.Column(db.Integer, default=0)
    message_limit = db.Column(db.Integer, nullable=True)  # Per-bot cap (NULL = use org plan limit)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # --- RELATIONSHIPS ---
    documents = db.relationship('Document', backref='bot', lazy=True, cascade="all, delete-orphan")
    scrape_jobs = db.relationship('ScrapeJob', backref='bot_ref', lazy=True, cascade="all, delete-orphan")
    ui_settings = db.relationship('BotUI', backref='bot', uselist=False, cascade="all, delete-orphan")
    leads = db.relationship('Lead', backref='bot_ref', lazy=True, cascade="all, delete-orphan")
    chat_messages = db.relationship('ChatMessage', backref='bot_ref', lazy=True, cascade="all, delete-orphan")


# ═══════════════════════════════════════════
# PAYMENT — Transaction record (linked to User + Org)
# ═══════════════════════════════════════════
class Payment(db.Model):
    """Records every completed Paddle transaction."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # WHO paid
    org_id = db.Column(db.Integer, db.ForeignKey('organization.id'), nullable=True)  # Which account
    plan = db.Column(db.String(20), nullable=True)
    amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='INR')
    customer_email = db.Column(db.String(120), nullable=True)
    paddle_transaction_id = db.Column(db.String(255), unique=True, nullable=True)
    paddle_customer_id = db.Column(db.String(255), nullable=True)
    paddle_subscription_id = db.Column(db.String(255), nullable=True)
    product_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default='completed')

    # --- PAYMENT METHOD SNAPSHOT ---
    payment_method = db.Column(db.String(30), nullable=True)
    card_brand = db.Column(db.String(30), nullable=True)
    card_last4 = db.Column(db.String(4), nullable=True)

    # --- REFUND TRACKING ---
    refund_amount = db.Column(db.Float, default=0.0)
    refunded_at = db.Column(db.DateTime, nullable=True)
    tax_amount = db.Column(db.Float, default=0.0)  # Tax collected by Paddle

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════
# BOT UI — Visual settings (1:1 with Bot)
# ═══════════════════════════════════════════
class BotUI(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False, unique=True)

    theme_color = db.Column(db.String(20), default='#E8722A')
    header_color = db.Column(db.String(20), default='#FFFFFF')
    theme_mode = db.Column(db.String(10), default='light')
    avatar_base64 = db.Column(db.Text, nullable=True)
    glass_opacity = db.Column(db.Integer, default=35)
    glass_blur = db.Column(db.Integer, default=25)

    # --- EXTENDED CUSTOMIZATION ---
    greeting_message = db.Column(db.Text, nullable=True)       # Custom welcome message
    input_placeholder = db.Column(db.String(120), nullable=True)  # Input field placeholder
    header_title = db.Column(db.String(60), nullable=True)     # Override header text (default: bot name)
    bubble_radius = db.Column(db.Integer, default=16)          # Message bubble corner radius (px)
    font_family = db.Column(db.String(40), default='Inter')    # Inter | Outfit | Roboto | System
    font_size = db.Column(db.Integer, default=14)              # Base font size (px)
    user_bubble_color = db.Column(db.String(20), nullable=True)  # User msg bg (NULL = use theme_color)
    bot_bubble_color = db.Column(db.String(20), nullable=True)   # Bot msg bg (NULL = auto by theme)
    widget_position = db.Column(db.String(20), default='bottom-right')  # bottom-right | bottom-left
    show_branding = db.Column(db.Boolean, default=True)        # Show "Powered by bubbl.ooo"


# ═══════════════════════════════════════════
# DOCUMENT — Uploaded knowledge base files
# ═══════════════════════════════════════════
class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════
# SCRAPE JOB — Website scraping tasks
# ═══════════════════════════════════════════
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


# ═══════════════════════════════════════════
# LEAD — Captured contact information
# ═══════════════════════════════════════════
class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    custom_data = db.Column(db.JSON, default={})
    captured_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════
# FEEDBACK — User ratings and comments
# ═══════════════════════════════════════════
class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('lead.id'), nullable=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    bot = db.relationship('Bot', backref=db.backref('feedbacks', lazy=True, cascade="all, delete-orphan"))


# ═══════════════════════════════════════════
# CHAT MESSAGE — Persisted conversation history (NEW)
# ═══════════════════════════════════════════
class ChatMessage(db.Model):
    """Stores every message exchanged in a chat session."""
    id = db.Column(db.Integer, primary_key=True)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=True)  # Null = public Bubbl bot
    lead_id = db.Column(db.Integer, db.ForeignKey('lead.id'), nullable=True)  # If lead captured
    session_id = db.Column(db.String(64), nullable=False, index=True)  # Groups messages into a conversation
    role = db.Column(db.String(10), nullable=False)  # 'user' or 'bot'
    content = db.Column(db.Text, nullable=False)
    tokens_used = db.Column(db.Integer, default=0)  # Tokens for this specific response
    ip_address = db.Column(db.String(45), nullable=True)  # Visitor IP (IPv4/IPv6), captured on user messages
    rating = db.Column(db.SmallInteger, nullable=True)  # 1 = thumbs up, -1 = thumbs down, NULL = not rated
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))



# ═══════════════════════════════════════════
# SHARED CONVERSATION — Public share links for chat sessions
# ═══════════════════════════════════════════
class SharedConversation(db.Model):
    """Stores a shareable snapshot of a conversation."""
    id = db.Column(db.Integer, primary_key=True)
    share_token = db.Column(db.String(16), unique=True, nullable=False, index=True)
    session_id = db.Column(db.String(64), nullable=False)
    bot_id = db.Column(db.Integer, db.ForeignKey('bot.id'), nullable=True)
    bot_name = db.Column(db.String(100), nullable=True)  # Snapshot of bot name at share time
    messages_snapshot = db.Column(db.JSON, nullable=False)  # [{role, content, created_at}]
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)  # Optional expiry (30 days default)
