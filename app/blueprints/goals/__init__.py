from flask import Blueprint

bp = Blueprint("goals", __name__, url_prefix="/obiettivi")

from app.blueprints.goals import routes  # noqa: E402,F401
