"""Super Admin — System actions (DB migration, logs)."""
from flask import jsonify, render_template
from models.models import db
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/migrate_db', methods=['POST'])
@super_admin_required
def migrate_db():
    """Run safe DB migrations to add any missing columns + normalize relationships."""
    from sqlalchemy import text
    migrations = [
        # ═══ BOT ═══
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS tokens_used INTEGER DEFAULT 0",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS total_latency FLOAT DEFAULT 0.0",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS interaction_count INTEGER DEFAULT 0",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",


        # ═══ ORGANIZATION ═══
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20) DEFAULT 'free'",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_started_at TIMESTAMP",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMP",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30)",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS card_brand VARCHAR(30)",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS card_last4 VARCHAR(4)",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",

        # ═══ USER ═══
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP',


        # ═══ PAYMENT → USER (NORMALIZATION) ═══
        "ALTER TABLE payment ADD COLUMN IF NOT EXISTS user_id INTEGER",
        """DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_payment_user' AND table_name = 'payment'
            ) THEN
                ALTER TABLE payment ADD CONSTRAINT fk_payment_user
                FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE SET NULL;
            END IF;
        END $$""",
        """UPDATE payment SET user_id = u.id
           FROM "user" u
           WHERE payment.user_id IS NULL
           AND payment.customer_email IS NOT NULL
           AND lower(payment.customer_email) = lower(u.email)""",

        # ═══ DOCUMENT ═══
        "ALTER TABLE document ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",

        # ═══ FEEDBACK ═══
        "ALTER TABLE feedback ALTER COLUMN bot_id DROP NOT NULL",


        # ═══ CHAT_MESSAGE TABLE ═══
        """CREATE TABLE IF NOT EXISTS chat_message (
            id SERIAL PRIMARY KEY,
            bot_id INTEGER REFERENCES bot(id) ON DELETE SET NULL,
            lead_id INTEGER REFERENCES lead(id) ON DELETE SET NULL,
            session_id VARCHAR(64) NOT NULL,
            role VARCHAR(10) NOT NULL,
            content TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_chat_message_bot ON chat_message(bot_id)",
        "ALTER TABLE chat_message ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)",

        # ═══ CLEANUP: Remove redundant columns ═══
        "ALTER TABLE organization DROP COLUMN IF EXISTS payment_method",
        "ALTER TABLE organization DROP COLUMN IF EXISTS card_brand",
        "ALTER TABLE organization DROP COLUMN IF EXISTS card_last4",
        "ALTER TABLE bot DROP COLUMN IF EXISTS theme_color",
    ]


    results = []
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            results.append(f"OK: {sql[:80]}")
        except Exception as e:
            results.append(f"SKIP: {sql[:80]} ({str(e)[:60]})")
    db.session.commit()
    return jsonify({"success": True, "results": results})


# ═══════════════════════════════════════════
# NEW ROUTES
# ═══════════════════════════════════════════


@super_admin_bp.route('/logs')
@super_admin_required
def system_logs():
    """Display system logs page."""
    return render_template('super_admin/logs.html')
