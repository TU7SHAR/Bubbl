from flask import redirect, url_for, session, flash, make_response
from . import auth_bp  

@auth_bp.route('/logout')
def logout():
    session.clear()
    # Clear localStorage (chat history, lead state) via client-side JS
    # then redirect to login. Can't clear localStorage from server.
    return '''<!DOCTYPE html>
<html><head><title>Logging out...</title></head>
<body>
<script>
try { localStorage.clear(); } catch(e) {}
window.location.href = "/login";
</script>
</body>
</html>'''