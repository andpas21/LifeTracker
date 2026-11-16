from flask import Blueprint

bp = Blueprint("family", __name__, url_prefix="/famiglia")

from app.blueprints.family import routes  # noqa: E402,F401
