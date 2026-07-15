"""Shared decorators for super admin routes."""
from functools import wraps
from flask import session, jsonify, redirect, url_for, request


def super_admin_required(f):
    """Reject non-super-admin users. Returns 403 JSON for API routes, redirect for pages."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'super_admin':
            if request.is_json or request.content_type == 'application/json':
                return jsonify({"error": "Access denied"}), 403
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated
