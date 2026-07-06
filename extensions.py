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
# Uses Redis in production, falls back to memory:// for local dev without Redis
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri=REDIS_URL,
)

# --- CACHE ---
if REDIS_URL.startswith('memory'):
    cache = Cache(config={
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": 60,
    })
else:
    cache = Cache(config={
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": os.getenv('REDIS_URL', 'redis://localhost:6379/1'),
        "CACHE_DEFAULT_TIMEOUT": 60,
    })
