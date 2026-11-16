from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TimeField,
    widgets,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.services.period import WEEKDAYS_IT
from app.services.reminder_service import FREQUENCY_LABELS


class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class ReminderForm(FlaskForm):
    title = StringField("Titolo", validators=[DataRequired(), Length(max=120)],
                        render_kw={"placeholder": "es. Allenamento in bici"})
    message = StringField("Messaggio", validators=[Optional(), Length(max=500)])
    activity_id = SelectField("Attività collegata", coerce=int, validators=[Optional()],
                              description="Il promemoria aprirà direttamente la registrazione di questa attività.")
    frequency = SelectField("Frequenza", choices=list(FREQUENCY_LABELS.items()), default="daily")
    time_of_day = TimeField("Ora", validators=[DataRequired()])
    start_date = DateField("Dal giorno", validators=[DataRequired()])
    weekdays = MultiCheckboxField("Giorni", coerce=int, choices=[(i, d.capitalize()) for i, d in enumerate(WEEKDAYS_IT)])
    day_of_month = IntegerField("Giorno del mese", validators=[Optional(), NumberRange(1, 31)])
    submit = SubmitField("Salva")


class ExportForm(FlaskForm):
    class Meta:
        csrf = False  # solo lettura (GET)

    da = DateField("Dal", validators=[Optional()])
    a = DateField("Al", validators=[Optional()])
    persona = SelectField("Persona", coerce=int, validators=[Optional()])
    categoria = SelectField("Categoria", coerce=int, validators=[Optional()])
    attivita = SelectField("Attività", coerce=int, validators=[Optional()])
    formato = SelectField("Formato", choices=[("xlsx", "Excel (.xlsx)"), ("csv", "CSV (separatore ;)")], default="xlsx")
