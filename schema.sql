-- ═══════════════════════════════════════════════════════════════
-- BUBBL.OOO — NORMALIZED DATABASE SCHEMA
-- PostgreSQL (NeonDB Serverless)
-- Last updated: July 2026
-- ═══════════════════════════════════════════════════════════════

-- ═══ ORGANIZATION (Team/Company identity) ═══
CREATE TABLE organization (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    plan VARCHAR(20) DEFAULT 'free',         -- free, starter, growth, pro
    messages_used INTEGER DEFAULT 0,
    messages_reset_at TIMESTAMP,
    paddle_subscription_id VARCHAR(255),
    paddle_customer_id VARCHAR(255),
    subscription_status VARCHAR(20) DEFAULT 'free',  -- free, active, canceled
    subscription_started_at TIMESTAMP,
    subscription_ends_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ═══ USER (Individual account, belongs to an org) ═══
CREATE TABLE "user" (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    otp VARCHAR(6),
    otp_created_at TIMESTAMP,
    is_verified BOOLEAN DEFAULT FALSE,
    role VARCHAR(20) NOT NULL DEFAULT 'member',  -- admin, member
    is_suspended BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ═══ BOT (AI Chatbot agent, owned by user within an org) ═══
CREATE TABLE bot (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    created_by INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    bot_name VARCHAR(100) NOT NULL,
    store_id VARCHAR(255),                    -- Gemini vector store ID
    visibility VARCHAR(10) NOT NULL DEFAULT 'public',
    access_key VARCHAR(4),
    allowed_domains VARCHAR(255),
    bot_type VARCHAR(50) DEFAULT 'general',
    system_prompt TEXT,
    lead_capture_timing VARCHAR(20) DEFAULT 'disabled',
    custom_form_fields VARCHAR(500) DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,
    tokens_used INTEGER DEFAULT 0,
    total_latency FLOAT DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ═══ PAYMENT (Transaction record — linked to BOTH User and Org) ═══
CREATE TABLE payment (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES "user"(id) ON DELETE SET NULL,  -- WHO paid
    org_id INTEGER REFERENCES organization(id) ON DELETE SET NULL,
    plan VARCHAR(20),
    amount FLOAT DEFAULT 0.0,
    currency VARCHAR(10) DEFAULT 'INR',
    customer_email VARCHAR(120),
    paddle_transaction_id VARCHAR(255) UNIQUE,
    paddle_customer_id VARCHAR(255),
    paddle_subscription_id VARCHAR(255),
    product_id VARCHAR(255),
    status VARCHAR(30) DEFAULT 'completed',   -- completed, refunded, partially_refunded
    payment_method VARCHAR(30),               -- card, paypal, upi, etc.
    card_brand VARCHAR(30),                   -- visa, mastercard, rupay
    card_last4 VARCHAR(4),
    refund_amount FLOAT DEFAULT 0.0,
    refunded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- FK constraint (named for easy reference in ERD)
ALTER TABLE payment ADD CONSTRAINT fk_payment_user
    FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE SET NULL;

-- ═══ BOT_UI (Visual settings, 1:1 with Bot) ═══
CREATE TABLE bot_ui (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL UNIQUE REFERENCES bot(id) ON DELETE CASCADE,
    theme_color VARCHAR(20) DEFAULT '#E8722A',
    header_color VARCHAR(20) DEFAULT '#FFFFFF',
    theme_mode VARCHAR(10) DEFAULT 'light',
    avatar_base64 TEXT,
    glass_opacity INTEGER DEFAULT 35,
    glass_blur INTEGER DEFAULT 25
);

-- ═══ DOCUMENT (Knowledge base files) ═══
CREATE TABLE document (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ═══ SCRAPE_JOB (Website scraping tasks) ═══
CREATE TABLE scrape_job (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    url VARCHAR(2048) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    "limit" INTEGER DEFAULT 20,
    error_message TEXT,
    logs TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- ═══ LEAD (Captured contacts) ═══
CREATE TABLE lead (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL,
    phone VARCHAR(20),
    custom_data JSONB DEFAULT '{}',
    captured_at TIMESTAMP DEFAULT NOW()
);

-- ═══ FEEDBACK (Ratings + comments) ═══
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER REFERENCES bot(id) ON DELETE CASCADE,  -- NULL = platform feedback
    lead_id INTEGER REFERENCES lead(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ═══ CHAT_MESSAGE (Persisted conversation history) ═══
CREATE TABLE chat_message (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER REFERENCES bot(id) ON DELETE SET NULL,
    lead_id INTEGER REFERENCES lead(id) ON DELETE SET NULL,
    session_id VARCHAR(64) NOT NULL,          -- Groups messages into conversations
    role VARCHAR(10) NOT NULL,                -- 'user' or 'bot'
    content TEXT NOT NULL,
    tokens_used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ═══ INDEXES ═══
CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_message_bot ON chat_message(bot_id);
CREATE INDEX IF NOT EXISTS idx_lead_bot ON lead(bot_id);
CREATE INDEX IF NOT EXISTS idx_lead_email ON lead(email);
CREATE INDEX IF NOT EXISTS idx_payment_org ON payment(org_id);
CREATE INDEX IF NOT EXISTS idx_payment_user ON payment(user_id);
CREATE INDEX IF NOT EXISTS idx_user_org ON "user"(org_id);
CREATE INDEX IF NOT EXISTS idx_bot_org ON bot(org_id);
CREATE INDEX IF NOT EXISTS idx_feedback_bot ON feedback(bot_id);


-- ═══════════════════════════════════════════════════════════════
-- RELATIONSHIPS SUMMARY (for ERD tools):
--
-- Organization 1──∞ User
-- Organization 1──∞ Bot (via org_id)
-- Organization 1──∞ Payment (which org was charged)
-- User 1──∞ Bot (created_by)
-- User 1──∞ Payment (who paid)
-- Bot 1──1 BotUI
-- Bot 1──∞ Document
-- Bot 1──∞ ScrapeJob
-- Bot 1──∞ Lead
-- Bot 1──∞ ChatMessage
-- Bot 1──∞ Feedback
-- Lead 1──∞ ChatMessage (optional link)
-- Lead 1──∞ Feedback (optional link)
-- ═══════════════════════════════════════════════════════════════
