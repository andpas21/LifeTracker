from flask import Blueprint

bp = Blueprint("calendar", __name__, url_prefix="/calendario")

from app.blueprints.calendar import routes  # noqa: E402,F401
