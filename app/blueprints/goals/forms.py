from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, RadioField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models import GOAL_RECURRENCE_LABELS, GOAL_TARGET_LABELS


class GoalForm(FlaskForm):
    title = StringField("Titolo", validators=[DataRequired(), Length(max=120)],
                        render_kw={"placeholder": "es. 1000 km in bici quest'anno"})
    description = TextAreaField("Descrizione", validators=[Optional(), Length(max=500)], render_kw={"rows": 2})
    scope = RadioField("Tipo", choices=[("personal", "Individuale"), ("family", "Familiare (di tutta la famiglia)")],
                       default="personal")
    owner_profile_id = SelectField("Di chi è l'obiettivo", coerce=int, validators=[Optional()])
    visibility = SelectField("Visibilità", choices=[("family", "Visibile alla famiglia"), ("private", "Privato")],
                             default="family")
    target_type = SelectField("Cosa misurare", choices=list(GOAL_TARGET_LABELS.items()), default="count")
    category_id = SelectField("Categoria", coerce=int, validators=[Optional()])
    activity_id = SelectField("Attività", coerce=int, validators=[Optional()])
    metric_definition_id = SelectField("Indicatore", coerce=int, validators=[Optional()])
    target_value = DecimalField("Traguardo", places=None, validators=[DataRequired(), NumberRange(min=0.0001)],
                                description="Per gli indicatori di durata il traguardo è in minuti.")
    recurrence = SelectField("Ricorrenza", choices=list(GOAL_RECURRENCE_LABELS.items()), default="none")
    start_date = DateField("Inizio", validators=[DataRequired()])
    end_date = DateField("Scadenza", validators=[Optional()],
                         description="Obbligatoria per gli obiettivi una tantum; facoltativa per quelli ricorrenti.")
    submit = SubmitField("Salva")

    def to_data(self) -> dict:
        return {
            "title": self.title.data, "description": self.description.data, "scope": self.scope.data,
            "owner_profile_id": self.owner_profile_id.data, "visibility": self.visibility.data,
            "target_type": self.target_type.data, "category_id": self.category_id.data or None,
            "activity_id": self.activity_id.data or None,
            "metric_definition_id": self.metric_definition_id.data or None,
            "target_value": self.target_value.data, "recurrence": self.recurrence.data,
            "start_date": self.start_date.data, "end_date": self.end_date.data,
        }
