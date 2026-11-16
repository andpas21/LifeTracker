"""Validatori e campi riutilizzabili dai form di tutti i blueprint."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import Regexp

HEX_COLOR = Regexp(r"^#[0-9a-fA-F]{6}$", message="Colore non valido (formato #rrggbb).")

# Palette proposta nei selettori colore (coerente con l'interfaccia)
COLOR_PALETTE = [
    "#4f46e5", "#0ea5e9", "#10b981", "#84cc16", "#f59e0b",
    "#f97316", "#ef4444", "#ec4899", "#8b5cf6", "#64748b",
]


class ColorField(StringField):
    """Campo colore: renderizzato come <input type="color">."""

    def __init__(self, label=None, validators=None, **kwargs):
        validators = list(validators or []) + [HEX_COLOR]
        kwargs.setdefault("render_kw", {})["type"] = "color"
        super().__init__(label, validators, **kwargs)


class ConfirmForm(FlaskForm):
    """Form vuoto: trasporta il token CSRF nei pulsanti che eseguono azioni POST."""

    submit = SubmitField("Conferma")
