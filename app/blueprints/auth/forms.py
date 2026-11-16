from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional

from app.services.auth_service import MIN_PASSWORD_LENGTH


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_strip])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    remember = BooleanField("Ricordami su questo dispositivo")
    submit = SubmitField("Accedi")


class RegisterForm(FlaskForm):
    display_name = StringField("Nome", validators=[DataRequired(), Length(min=2, max=80)])
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_strip])
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH, max=128)],
        description=f"Almeno {MIN_PASSWORD_LENGTH} caratteri, con lettere e numeri o simboli.",
    )
    confirm = PasswordField(
        "Conferma password", validators=[DataRequired(), EqualTo("password", "Le password non coincidono.")]
    )
    invite_code = StringField("Codice invito", validators=[Optional(), Length(max=20)])
    submit = SubmitField("Crea account")
