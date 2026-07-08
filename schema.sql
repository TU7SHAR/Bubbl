-- ==========================================
-- BCKUP SCRIPT FOR RECREATE TABLES
-- ==========================================

-- ORGANIZATION TABLE
CREATE TABLE organization (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- USER TABLE
CREATE TABLE "user" (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    otp VARCHAR(6),
    otp_created_at TIMESTAMP WITHOUT TIME ZONE,
    is_verified BOOLEAN DEFAULT FALSE,
    role VARCHAR(20) NOT NULL DEFAULT 'member'
);

-- BOT TABLE
CREATE TABLE bot (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    created_by INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    bot_name VARCHAR(100) NOT NULL,
    store_id VARCHAR(255),
    visibility VARCHAR(10) NOT NULL DEFAULT 'public',
    access_key VARCHAR(4),
    allowed_domains VARCHAR(255),
    bot_type VARCHAR(50) DEFAULT 'general',
    theme_color VARCHAR(20) DEFAULT '#10b981',
    system_prompt TEXT,
    lead_capture_timing VARCHAR(20) DEFAULT 'disabled',
    custom_form_fields VARCHAR(500) DEFAULT '',
    tokens_used INTEGER DEFAULT 0,
    total_latency DOUBLE PRECISION DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0
);

-- BOT UI TABLE
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

-- DOCUMENT TABLE
CREATE TABLE document (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL
);

-- SCRAPE JOB TABLE
CREATE TABLE scrape_job (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    url VARCHAR(2048) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    "limit" INTEGER DEFAULT 20,
    error_message TEXT,
    logs TEXT DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITHOUT TIME ZONE
);

-- LEAD TABLE
CREATE TABLE lead (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL,
    phone VARCHAR(20),
    custom_data JSONB DEFAULT '{}'::jsonb,
    captured_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- FEEDBACK TABLE
CREATE TABLE feedback (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL REFERENCES bot(id) ON DELETE CASCADE,
    lead_id INTEGER REFERENCES lead(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);