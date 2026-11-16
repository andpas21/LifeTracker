from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.models import AGGREGATION_LABELS, DATA_TYPE_LABELS, KIND_LABELS, SCOPE_LABELS
from app.utils.forms import ColorField
from app.utils.icons import ICON_CHOICES


class CategoryForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=80)])
    parent_id = SelectField("Categoria superiore", coerce=int, default=0)
    description = TextAreaField("Descrizione", validators=[Optional(), Length(max=500)], render_kw={"rows": 2})
    icon = SelectField("Icona", choices=ICON_CHOICES, default="tag")
    color = ColorField("Colore", default="#4f46e5")
    sort_order = IntegerField("Ordine", default=0, validators=[Optional(), NumberRange(-999, 999)])
    submit = SubmitField("Salva")


class ActivityForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=80)])
    category_id = SelectField("Categoria", coerce=int, validators=[DataRequired("Scegli una categoria.")])
    description = TextAreaField("Descrizione", validators=[Optional(), Length(max=500)], render_kw={"rows": 2})
    icon = SelectField("Icona", choices=[("", "Come la categoria")] + ICON_CHOICES, default="")
    custom_color = BooleanField("Colore personalizzato (altrimenti quello della categoria)")
    color = ColorField("Colore", default="#4f46e5")
    count_label = StringField(
        "Etichetta del contatore", default="volte", validators=[DataRequired(), Length(max=40)],
        description="Come si chiama un \"+1\": es. uscite, sessioni, volte, partite.",
    )
    default_quantity = DecimalField(
        "Quantità predefinita", default=1, places=None, validators=[DataRequired(), NumberRange(min=0.0001)],
        description="Il valore registrato con la modalità rapida (di solito 1).",
    )
    default_scope = SelectField("Ambito predefinito", choices=list(SCOPE_LABELS.items()), default="personal")
    is_quick = BooleanField("Mostra nella registrazione rapida", default=True)
    sort_order = IntegerField("Ordine", default=0, validators=[Optional(), NumberRange(-999, 999)])
    submit = SubmitField("Salva")

    def to_data(self) -> dict:
        return {
            "name": self.name.data,
            "category_id": self.category_id.data,
            "description": self.description.data,
            "icon": self.icon.data,
            "color": self.color.data if self.custom_color.data else None,
            "count_label": self.count_label.data,
            "default_quantity": self.default_quantity.data,
            "default_scope": self.default_scope.data,
            "is_quick": self.is_quick.data,
            "sort_order": self.sort_order.data,
        }


class MetricForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=60)], render_kw={"placeholder": "es. Chilometri"})
    data_type = SelectField("Tipo di dato", choices=list(DATA_TYPE_LABELS.items()), default="decimal")
    unit = StringField("Unità di misura", validators=[Optional(), Length(max=20)], render_kw={"placeholder": "es. km"})
    kind = SelectField(
        "Significato", choices=list(KIND_LABELS.items()), default="other",
        description="Serve per confrontare attività diverse in modo omogeneo (es. sommare le distanze).",
    )
    aggregation = SelectField(
        "Aggregazione nei grafici", choices=list(AGGREGATION_LABELS.items()), default="sum",
        description="Somma per km o minuti; media per frequenza cardiaca o potenza.",
    )
    min_value = DecimalField("Valore minimo", places=None, validators=[Optional()])
    max_value = DecimalField("Valore massimo", places=None, validators=[Optional()])
    is_required = BooleanField("Obbligatorio nella registrazione completa")
    sort_order = IntegerField("Ordine", default=0, validators=[Optional(), NumberRange(-999, 999)])
    submit = SubmitField("Salva indicatore")

    def to_data(self) -> dict:
        return {f: getattr(self, f).data for f in (
            "name", "data_type", "unit", "kind", "aggregation", "min_value", "max_value", "is_required", "sort_order"
        )}


class TagForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired(), Length(max=40)])
    color = ColorField("Colore", default="#64748b")
    submit = SubmitField("Salva")
