"""Super Admin — System actions (DB migration, etc.)."""
from flask import jsonify
from models.models import db
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/migrate_db', methods=['POST'])
@super_admin_required
def migrate_db():
    """Run safe DB migrations to add any missing columns."""
    from sqlalchemy import text
    migrations = [
        # Bot metrics
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS tokens_used INTEGER DEFAULT 0",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS total_latency FLOAT DEFAULT 0.0",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS interaction_count INTEGER DEFAULT 0",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE bot ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        # Organization subscription
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20) DEFAULT 'free'",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_started_at TIMESTAMP",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMP",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30)",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS card_brand VARCHAR(30)",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS card_last4 VARCHAR(4)",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        # User fields
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE",
        "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        # Payment → User link
        "ALTER TABLE payment ADD COLUMN IF NOT EXISTS user_id INTEGER",
        # Document timestamp
        "ALTER TABLE document ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        # Feedback nullable bot_id
        "ALTER TABLE feedback ALTER COLUMN bot_id DROP NOT NULL",
        # ChatMessage table (create if not exists)
        """CREATE TABLE IF NOT EXISTS chat_message (
            id SERIAL PRIMARY KEY,
            bot_id INTEGER REFERENCES bot(id),
            lead_id INTEGER REFERENCES lead(id),
            session_id VARCHAR(64) NOT NULL,
            role VARCHAR(10) NOT NULL,
            content TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message(session_id)",
    ]

    results = []
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            results.append(f"OK: {sql[:70]}")
        except Exception as e:
            results.append(f"SKIP: {sql[:70]} ({str(e)[:50]})")
    db.session.commit()
    return jsonify({"success": True, "results": results})
