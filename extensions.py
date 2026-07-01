# =========================================
# SHARED FLASK EXTENSIONS — BUBBL.OOO
# =========================================
# Initialized here, configured in app.py
# Using LOCAL Redis (free, unlimited, installed on the same VPS)

import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# --- RATE LIMITER ---
# Now uses Redis: consistent across ALL gunicorn workers.
# Before: memory:// = each worker tracked limits separately (broken).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri=REDIS_URL,
)

# --- CACHE ---
# Now uses Redis: shared across ALL gunicorn workers.
# Before: SimpleCache = each worker had its own cache (inconsistent).
# Bot configs fetched ONCE, served to all workers for 60 seconds.
cache = Cache(config={
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_URL": os.getenv('REDIS_URL', 'redis://localhost:6379/1'),
    "CACHE_DEFAULT_TIMEOUT": 60,
})
