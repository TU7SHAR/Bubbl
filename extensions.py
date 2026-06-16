# =========================================
# SHARED FLASK EXTENSIONS — BUBBL.OOO
# =========================================
# Initialized here, configured in app.py

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri="memory://",  # Switch to "redis://localhost:6379" when Redis is added
)
