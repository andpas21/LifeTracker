from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import DateField, PasswordField, RadioField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, Optional

from app.services.auth_service import MIN_PASSWORD_LENGTH
from app.utils.forms import ColorField
from app.utils.uploads import ALLOWED_IMAGE_EXTENSIONS


class ProfileForm(FlaskForm):
    display_name = StringField("Nome visualizzato", validators=[DataRequired(), Length(min=2, max=80)])
    birth_date = DateField("Data di nascita", validators=[Optional()])
    color = ColorField("Colore personale", description="Usato per distinguerti nei grafici e nel calendario.")
    bio = TextAreaField("Presentazione", validators=[Optional(), Length(max=500)], render_kw={"rows": 3})
    submit = SubmitField("Salva profilo")


class AvatarForm(FlaskForm):
    avatar = FileField(
        "Nuova foto",
        validators=[FileRequired("Seleziona un'immagine."), FileAllowed(ALLOWED_IMAGE_EXTENSIONS, "Solo immagini.")],
    )
    submit = SubmitField("Carica foto")


class PasswordChangeForm(FlaskForm):
    current_password = PasswordField("Password attuale", validators=[DataRequired()])
    new_password = PasswordField(
        "Nuova password",
        validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH, max=128)],
        description=f"Almeno {MIN_PASSWORD_LENGTH} caratteri, con lettere e numeri o simboli.",
    )
    confirm = PasswordField(
        "Conferma nuova password", validators=[DataRequired(), EqualTo("new_password", "Le password non coincidono.")]
    )
    submit = SubmitField("Cambia password")


class PreferencesForm(FlaskForm):
    theme = RadioField(
        "Tema",
        choices=[("auto", "Automatico (come il dispositivo)"), ("light", "Chiaro"), ("dark", "Scuro")],
        default="auto",
    )
    submit = SubmitField("Salva preferenze")
