from flask import Blueprint

bp = Blueprint("entries", __name__, url_prefix="/registrazioni")

from app.blueprints.entries import routes  # noqa: E402,F401
