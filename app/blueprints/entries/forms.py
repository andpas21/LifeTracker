"""Form delle registrazioni. I campi degli indicatori sono creati dinamicamente
per ogni attività (build_entry_form), così nuovi indicatori non richiedono codice."""
from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from wtforms import (
    BooleanField,
    DateField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Length, Optional

from app.models import SCOPE_LABELS, VISIBILITY_LABELS


class EntryForm(FlaskForm):
    activity_id = SelectField("Attività", coerce=int, validators=[DataRequired()])
    performed_by_profile_id = SelectField("Chi l'ha svolta", coerce=int, validators=[DataRequired()])
    occurred_date = DateField("Data", validators=[DataRequired()])
    occurred_time = TimeField("Ora", validators=[DataRequired()])
    quantity = StringField("Quantità", validators=[DataRequired(), Length(max=20)], render_kw={"inputmode": "decimal"})
    scope = SelectField("Ambito", choices=list(SCOPE_LABELS.items()))
    visibility = SelectField("Visibilità", choices=list(VISIBILITY_LABELS.items()), default="family")
    tag_ids = SelectMultipleField("Tag", coerce=int, validators=[Optional()])
    new_tags = StringField("Nuovi tag", validators=[Optional(), Length(max=200)],
                           render_kw={"placeholder": "separati da virgola, es. vacanza, mare"})
    participant_ids = SelectMultipleField("Partecipanti", coerce=int, validators=[Optional()])
    description = StringField("Descrizione", validators=[Optional(), Length(max=500)],
                              render_kw={"placeholder": "es. Giro del lago"})
    notes = TextAreaField("Note", validators=[Optional(), Length(max=5000)], render_kw={"rows": 3})
    attachments = MultipleFileField("Foto e allegati")
    submit = SubmitField("Salva")

    metric_field_names: list = []


def build_entry_form(activity, formdata_source=None, **kwargs) -> EntryForm:
    """Crea una sottoclasse di EntryForm con un campo per ogni indicatore attivo dell'attività."""

    class DynamicEntryForm(EntryForm):
        pass

    names = []
    for metric in (activity.active_metrics if activity else []):
        name = f"m_{metric.id}"
        label = metric.label
        if metric.data_type == "boolean":
            field = BooleanField(label)
        elif metric.data_type == "text":
            field = StringField(label, validators=[Optional(), Length(max=500)])
        else:
            placeholder = "ore:minuti, es. 1:30" if metric.data_type == "duration" else ""
            inputmode = "text" if metric.data_type == "duration" else (
                "numeric" if metric.data_type == "integer" else "decimal")
            field = StringField(label, validators=[Optional(), Length(max=30)],
                                render_kw={"placeholder": placeholder, "inputmode": inputmode})
        setattr(DynamicEntryForm, name, field)
        names.append((name, metric))
    DynamicEntryForm.metric_field_names = names
    return DynamicEntryForm(**kwargs)


class QuickAddForm(FlaskForm):
    performed_by_profile_id = SelectField("Per", coerce=int, validators=[Optional()])
