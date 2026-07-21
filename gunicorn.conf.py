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
# Single worker with 24 threads for WebSocket (Socket.IO) compatibility.
# Socket.IO polling sessions are per-process — multiple workers cause 400 errors
# because the session created on worker 1 isn't found by worker 2.
#
# 1 worker × 24 threads = 24 concurrent slots (same capacity as 2×12).
# To scale beyond 24 concurrent users: switch to gevent worker + Redis session store.
#
# Override with env vars if needed:
#   WEB_CONCURRENCY=1 GUNICORN_THREADS=24
workers = int(os.environ.get('WEB_CONCURRENCY', 1))
threads = int(os.environ.get('GUNICORN_THREADS', 24))
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
