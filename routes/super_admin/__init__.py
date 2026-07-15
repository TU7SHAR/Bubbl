from flask import Blueprint

super_admin_bp = Blueprint('super_admin_bp', __name__, url_prefix='/super_admin')

from . import dashboard, users, bots, billing, leads, feedback, conversations, actions, scrapes
