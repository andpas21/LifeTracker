from flask import Blueprint

bp = Blueprint("tools", __name__)

from app.blueprints.tools import routes  # noqa: E402,F401
