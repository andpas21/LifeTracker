from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import DateField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models import ROLE_ADMIN, ROLE_LABELS, ROLE_MEMBER
from app.utils.forms import ColorField, ConfirmForm  # noqa: F401  (ConfirmForm riesportato)
from app.utils.uploads import ALLOWED_IMAGE_EXTENSIONS

ACCOUNT_ROLE_CHOICES = [(ROLE_MEMBER, ROLE_LABELS[ROLE_MEMBER]), (ROLE_ADMIN, ROLE_LABELS[ROLE_ADMIN])]


class FamilyCreateForm(FlaskForm):
    name = StringField("Nome della famiglia", validators=[DataRequired(), Length(min=2, max=120)])
    submit = SubmitField("Crea famiglia")


class FamilyRenameForm(FlaskForm):
    name = StringField("Nome della famiglia", validators=[DataRequired(), Length(min=2, max=120)])
    submit = SubmitField("Salva")


class FamilyDeleteForm(FlaskForm):
    confirm_name = StringField("Digita il nome della famiglia per confermare", validators=[DataRequired()])
    submit = SubmitField("Elimina definitivamente")


class JoinFamilyForm(FlaskForm):
    code = StringField("Codice invito", validators=[DataRequired(), Length(min=10, max=20)])
    submit = SubmitField("Unisciti")


class InvitationForm(FlaskForm):
    role = SelectField("Ruolo", choices=ACCOUNT_ROLE_CHOICES, default=ROLE_MEMBER)
    valid_days = IntegerField("Validità (giorni)", default=7, validators=[DataRequired(), NumberRange(1, 30)])
    note = StringField("Nota (facoltativa)", validators=[Optional(), Length(max=120)],
                       render_kw={"placeholder": "es. per la nonna"})
    submit = SubmitField("Genera codice")


class RoleForm(FlaskForm):
    role = SelectField("Ruolo", choices=ACCOUNT_ROLE_CHOICES)
    submit = SubmitField("Aggiorna")


class DependentForm(FlaskForm):
    display_name = StringField("Nome", validators=[DataRequired(), Length(min=1, max=80)])
    birth_date = DateField("Data di nascita", validators=[Optional()])
    color = ColorField("Colore", default="#10b981")
    bio = TextAreaField("Note", validators=[Optional(), Length(max=500)], render_kw={"rows": 2})
    avatar = FileField("Foto", validators=[FileAllowed(ALLOWED_IMAGE_EXTENSIONS, "Solo immagini.")])
    submit = SubmitField("Salva")

