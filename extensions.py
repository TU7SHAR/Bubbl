# =========================================
# SHARED FLASK EXTENSIONS — BUBBL.OOO
# =========================================
# Initialized here, configured in app.py

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri="memory://",  # Switch to "redis://localhost:6379" when Redis is added
)

# --- CACHE ---
# SimpleCache = in-memory, per-process, FREE (no Redis, no extra service).
# Stores frequently-read data (bot configs, avatars) in RAM so we don't hit
# the database on every single request. Switch CACHE_TYPE to "RedisCache"
# later if we move to multi-server.
cache = Cache(config={
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 60,  # entries expire after 60 seconds
})
