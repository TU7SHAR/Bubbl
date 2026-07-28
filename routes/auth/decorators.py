from functools import wraps
from flask import session, redirect, url_for, flash

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('auth.login'))
        
        # Super admins have all admin privileges too
        if session.get('role') not in ('admin', 'super_admin'):
            flash("Access Denied: Administrator privileges required.", "error")
            return redirect(url_for('views_bp.dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function