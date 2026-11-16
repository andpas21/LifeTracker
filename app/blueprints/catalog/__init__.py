from flask import Blueprint

bp = Blueprint("catalog", __name__, url_prefix="/catalogo")

from app.blueprints.catalog import routes  # noqa: E402,F401
