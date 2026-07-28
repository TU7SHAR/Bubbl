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
# Single worker with GeventWebSocket for true WebSocket support.
# This allows socket.io to upgrade from HTTP polling to raw ws:// protocol.
# gevent uses cooperative multitasking (greenlets) — handles many concurrent
# connections efficiently without threads.
workers = 1
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"

# --- TIMEOUTS ---
# Gemini API can take 2-10 seconds; allow up to 120s before killing a worker
timeout = 120
graceful_timeout = 30
keepalive = 5

# --- PERFORMANCE ---
# preload_app MUST be False with the gevent worker.
#
# app.py runs gevent's monkey.patch_all() at import time. With preload_app=True,
# gunicorn imports the app (and initializes the gevent hub + the Redis-backed
# SocketIO message queue) in the MASTER process, then fork()s the worker.
# A forked child inherits a stale gevent hub — greenlets/hub threads do not
# survive fork() — so the first blocking I/O in the worker (e.g. creating a
# Gemini File Search store or the time.sleep() polling loop during bot creation)
# hits a dead hub and crashes with:
#   AssertionError in gevent AbstractLinkable._notify_links
#   [ERROR] Control server error: no running event loop
#
# Setting preload_app=False makes each worker import the app and build its own
# fresh gevent hub AFTER fork, which is the supported setup for gevent workers.
preload_app = False

# Max requests before worker restarts (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# --- LOGGING ---
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = "info"
# Force unbuffered stdout so print() statements from app code appear immediately
# in journalctl. Without this, gevent's greenlet-based I/O can buffer output.
raw_env = ["PYTHONUNBUFFERED=1"]

# --- SECURITY ---
# Limit request sizes (matches Flask MAX_CONTENT_LENGTH)
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190
