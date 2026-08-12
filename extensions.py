# =========================================
# SHARED FLASK EXTENSIONS — BUBBL.OOO
# =========================================
# Initialized here, configured in app.py
# Using LOCAL Redis (free, unlimited, installed on the same VPS)

import os
from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


# --- RATE LIMIT KEY: the REAL visitor IP ---
# We sit behind nginx, so request.remote_addr is always 127.0.0.1.
# Using it as the limiter key means EVERY visitor on the platform shares a
# single bucket — one busy page load burns the quota for everybody.
# nginx already forwards X-Forwarded-For / X-Real-IP, so read those first.
def client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        # Left-most entry is the original client
        return forwarded.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or get_remote_address()


# --- ROUTES THAT MUST NEVER BE RATE LIMITED ---
# These are hit many times per single widget page load (static assets, the
# iframe document, avatar/link-colour lookups, socket.io polling).
# Counting them against a per-hour quota makes the widget die after a
# handful of page views. Paid endpoints (/api/chat, /api/lead) keep their
# own explicit @limiter.limit decorators.
UNMETERED_PREFIXES = (
    '/static/',
    '/socket.io/',
    '/embed/',
    '/api/bot_avatar/',
    '/admin/api/bot_link_colors/',
    '/favicon.ico',
    '/robots.txt',
    '/sitemap.xml',
)


def is_unmetered_request():
    return request.path.startswith(UNMETERED_PREFIXES)


# --- RATE LIMITER ---
# Uses Redis in production, falls back to memory:// for local dev without Redis
limiter = Limiter(
    key_func=client_ip,
    # Generous global ceiling — this is an abuse backstop, not a usage cap.
    default_limits=["1000 per hour", "100 per minute"],
    default_limits_exempt_when=is_unmetered_request,
    storage_uri=REDIS_URL,
    headers_enabled=True,  # Sends X-RateLimit-* + Retry-After for debugging
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
