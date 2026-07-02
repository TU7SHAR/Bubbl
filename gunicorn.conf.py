# =========================================
# GUNICORN PRODUCTION CONFIG — BUBBL.OOO
# =========================================
# Run with: gunicorn -c gunicorn.conf.py app:app

import os

# --- NETWORKING ---
# MUST bind to the platform-assigned $PORT (Heroku/DO/Render set this dynamically).
# Falling back to 5000 only for local runs.
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
backlog = 2048

# --- WORKERS ---
# Optimized for 1GB VPS with Celery handling background tasks.
# All gunicorn slots are now dedicated to serving web requests (chat, pages).
#   - 1GB VPS  -> 2 workers × 12 threads = 24 concurrent slots
#   - 2GB VPS  -> 3 workers × 12 threads = 36 slots
#   - 4GB VPS  -> 4 workers × 12 threads = 48 slots
# Override per-instance with WEB_CONCURRENCY / GUNICORN_THREADS env vars.
workers = int(os.environ.get('WEB_CONCURRENCY', 2))
threads = int(os.environ.get('GUNICORN_THREADS', 12))
worker_class = "gthread"

# --- TIMEOUTS ---
# Gemini API can take 2-10 seconds; allow up to 120s before killing a worker
timeout = 120
graceful_timeout = 30
keepalive = 5

# --- PERFORMANCE ---
# Preload app so workers share memory (saves ~30% RAM — important on small dynos)
preload_app = True

# Max requests before worker restarts (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# --- LOGGING ---
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = "info"

# --- SECURITY ---
# Limit request sizes (matches Flask MAX_CONTENT_LENGTH)
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190
