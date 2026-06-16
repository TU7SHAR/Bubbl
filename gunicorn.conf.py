# =========================================
# GUNICORN PRODUCTION CONFIG — BUBBL.OOO
# =========================================
# Run with: gunicorn -c gunicorn.conf.py app:app

import multiprocessing

# --- WORKERS ---
# 8 workers with 4 threads each = 32 concurrent requests
# Rule of thumb: (2 × CPU cores) + 1 for workers
workers = 8
threads = 4
worker_class = "gthread"

# --- NETWORKING ---
bind = "0.0.0.0:5000"
backlog = 2048

# --- TIMEOUTS ---
# Gemini API can take 2-10 seconds; allow up to 120s before killing a worker
timeout = 120
graceful_timeout = 30
keepalive = 5

# --- PERFORMANCE ---
# Preload app so workers share memory (saves ~30% RAM)
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
