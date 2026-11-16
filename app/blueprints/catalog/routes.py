from flask import abort, flash, redirect, render_template, request, url_for

from app.blueprints.catalog import bp
from app.blueprints.catalog.forms import ActivityForm, CategoryForm, MetricForm, TagForm
from app.models import AGGREGATION_LABELS, DATA_TYPE_LABELS, KIND_LABELS, Activity, Category, Tag
from app.services import catalog_service
from app.services.common import get_family_object_or_404
from app.utils.security import family_required, get_current_membership
from app.utils.views import flash_form_errors, require_post_confirm, run_service


def _actor():
    return get_current_membership()


# --------------------------------------------------------------------------- panoramica
@bp.route("/")
@family_required
def index():
    actor = _actor()
    show_archived = request.args.get("archiviati") == "1"
    categories = catalog_service.categories_tree(actor.family_id, include_archived=show_archived)
    return render_template(
        "catalog/index.html",
        categories=categories,
        show_archived=show_archived,
        can_create=catalog_service.can_create(actor),
        can_edit=lambda obj: catalog_service.can_edit(actor, obj),
    )


# --------------------------------------------------------------------------- categorie
def _category_form(form, category=None):
    actor = _actor()
    exclude = category.id if category else None
    form.parent_id.choices = [(0, "— Nessuna (categoria principale) —")] + catalog_service.category_choices(
        actor.family_id, top_level_only=True, exclude_id=exclude
    )
    return form


def _category_values(form):
    return dict(
        name=form.name.data, parent_id=form.parent_id.data or None, description=form.description.data,
        icon=form.icon.data, color=form.color.data, sort_order=form.sort_order.data,
    )


@bp.route("/categorie/nuova", methods=["GET", "POST"])
@family_required
def new_category():
    actor = _actor()
    if not catalog_service.can_create(actor):
        abort(403)
    form = _category_form(CategoryForm())
    if request.method == "GET" and request.args.get("superiore", type=int):
        form.parent_id.data = request.args.get("superiore", type=int)
    if form.validate_on_submit():
        ok, _ = run_service(lambda: catalog_service.create_category(actor, **_category_values(form)), "Categoria creata.")
        if ok:
            return redirect(url_for("catalog.index"))
    return render_template("catalog/category_form.html", form=form, category=None)


@bp.route("/categorie/<int:category_id>/modifica", methods=["GET", "POST"])
@family_required
def edit_category(category_id):
    actor = _actor()
    category = get_family_object_or_404(Category, category_id, actor.family_id)
    if not catalog_service.can_edit(actor, category):
        abort(403)
    form = _category_form(CategoryForm(obj=category), category)
    if request.method == "GET":
        form.parent_id.data = category.parent_id or 0
    if form.validate_on_submit():
        ok, _ = run_service(lambda: catalog_service.update_category(actor, category, **_category_values(form)),
                     "Categoria aggiornata.")
        if ok:
            return redirect(url_for("catalog.index"))
    return render_template("catalog/category_form.html", form=form, category=category)


@bp.route("/categorie/<int:category_id>/archivia", methods=["POST"])
@family_required
def archive_category(category_id):
    require_post_confirm()
    actor = _actor()
    category = get_family_object_or_404(Category, category_id, actor.family_id)
    run_service(lambda: catalog_service.toggle_archive_category(actor, category),
         "Categoria archiviata." if not category.is_archived else "Categoria ripristinata.")
    return redirect(url_for("catalog.index", archiviati=1 if category.is_archived else None))


@bp.route("/categorie/<int:category_id>/elimina", methods=["POST"])
@family_required
def delete_category(category_id):
    require_post_confirm()
    actor = _actor()
    category = get_family_object_or_404(Category, category_id, actor.family_id)
    run_service(lambda: catalog_service.delete_category(actor, category), "Categoria eliminata.")
    return redirect(url_for("catalog.index"))


# --------------------------------------------------------------------------- attività
def _activity_form(form):
    form.category_id.choices = catalog_service.category_choices(_actor().family_id)
    return form


@bp.route("/attivita/nuova", methods=["GET", "POST"])
@family_required
def new_activity():
    actor = _actor()
    if not catalog_service.can_create(actor):
        abort(403)
    form = _activity_form(ActivityForm())
    if not form.category_id.choices:
        flash("Crea prima almeno una categoria.", "info")
        return redirect(url_for("catalog.new_category"))
    if request.method == "GET" and request.args.get("categoria", type=int):
        form.category_id.data = request.args.get("categoria", type=int)
    if form.validate_on_submit():
        ok, activity = run_service(lambda: catalog_service.create_activity(actor, form.to_data()),
                            "Attività creata. Ora puoi aggiungere gli indicatori.")
        if ok:
            return redirect(url_for("catalog.activity_detail", activity_id=activity.id))
    return render_template("catalog/activity_form.html", form=form, activity=None)


@bp.route("/attivita/<int:activity_id>")
@family_required
def activity_detail(activity_id):
    actor = _actor()
    activity = get_family_object_or_404(Activity, activity_id, actor.family_id)
    return render_template(
        "catalog/activity_detail.html",
        activity=activity,
        metric_form=MetricForm(),
        can_edit=catalog_service.can_edit(actor, activity),
        entry_count=catalog_service.entry_count_for_activity(activity.id),
        data_type_labels=DATA_TYPE_LABELS,
        kind_labels=KIND_LABELS,
        aggregation_labels=AGGREGATION_LABELS,
    )


@bp.route("/attivita/<int:activity_id>/modifica", methods=["GET", "POST"])
@family_required
def edit_activity(activity_id):
    actor = _actor()
    activity = get_family_object_or_404(Activity, activity_id, actor.family_id)
    if not catalog_service.can_edit(actor, activity):
        abort(403)
    form = _activity_form(ActivityForm(obj=activity))
    if request.method == "GET":
        form.custom_color.data = bool(activity.color)
        form.color.data = activity.display_color
        form.icon.data = activity.icon or ""
    if form.validate_on_submit():
        ok, _ = run_service(lambda: catalog_service.update_activity(actor, activity, form.to_data()), "Attività aggiornata.")
        if ok:
            return redirect(url_for("catalog.activity_detail", activity_id=activity.id))
    return render_template("catalog/activity_form.html", form=form, activity=activity)


@bp.route("/attivita/<int:activity_id>/archivia", methods=["POST"])
@family_required
def archive_activity(activity_id):
    require_post_confirm()
    actor = _actor()
    activity = get_family_object_or_404(Activity, activity_id, actor.family_id)
    run_service(lambda: catalog_service.toggle_archive_activity(actor, activity),
         "Attività archiviata." if not activity.is_archived else "Attività ripristinata.")
    return redirect(url_for("catalog.activity_detail", activity_id=activity.id))


@bp.route("/attivita/<int:activity_id>/elimina", methods=["POST"])
@family_required
def delete_activity(activity_id):
    require_post_confirm()
    actor = _actor()
    activity = get_family_object_or_404(Activity, activity_id, actor.family_id)
    ok, _ = run_service(lambda: catalog_service.delete_activity(actor, activity), "Attività eliminata.")
    if ok:
        return redirect(url_for("catalog.index"))
    return redirect(url_for("catalog.activity_detail", activity_id=activity_id))


# --------------------------------------------------------------------------- indicatori
@bp.route("/attivita/<int:activity_id>/indicatori", methods=["POST"])
@family_required
def add_metric(activity_id):
    actor = _actor()
    activity = get_family_object_or_404(Activity, activity_id, actor.family_id)
    form = MetricForm()
    if form.validate_on_submit():
        run_service(lambda: catalog_service.add_metric(actor, activity, form.to_data()), "Indicatore aggiunto.")
    else:
        flash_form_errors(form)
    return redirect(url_for("catalog.activity_detail", activity_id=activity_id))


def _metric_or_404(metric_id):
    metric = catalog_service.get_family_metric(metric_id, _actor().family_id)
    if metric is None:
        abort(404)
    return metric


@bp.route("/indicatori/<int:metric_id>/modifica", methods=["GET", "POST"])
@family_required
def edit_metric(metric_id):
    actor = _actor()
    metric = _metric_or_404(metric_id)
    if not catalog_service.can_edit(actor, metric.activity):
        abort(403)
    form = MetricForm(obj=metric)
    if form.validate_on_submit():
        ok, _ = run_service(lambda: catalog_service.update_metric(actor, metric, form.to_data()), "Indicatore aggiornato.")
        if ok:
            return redirect(url_for("catalog.activity_detail", activity_id=metric.activity_id))
    return render_template("catalog/metric_form.html", form=form, metric=metric)


@bp.route("/indicatori/<int:metric_id>/archivia", methods=["POST"])
@family_required
def archive_metric(metric_id):
    require_post_confirm()
    actor = _actor()
    metric = _metric_or_404(metric_id)
    run_service(lambda: catalog_service.toggle_archive_metric(actor, metric),
         "Indicatore archiviato." if not metric.is_archived else "Indicatore ripristinato.")
    return redirect(url_for("catalog.activity_detail", activity_id=metric.activity_id))


@bp.route("/indicatori/<int:metric_id>/elimina", methods=["POST"])
@family_required
def delete_metric(metric_id):
    require_post_confirm()
    actor = _actor()
    metric = _metric_or_404(metric_id)
    activity_id = metric.activity_id
    run_service(lambda: catalog_service.delete_metric(actor, metric), "Indicatore eliminato.")
    return redirect(url_for("catalog.activity_detail", activity_id=activity_id))


# --------------------------------------------------------------------------- tag
@bp.route("/tag", methods=["GET", "POST"])
@family_required
def tags():
    actor = _actor()
    form = TagForm()
    if form.validate_on_submit():
        ok, _ = run_service(lambda: catalog_service.create_tag(actor, form.name.data, form.color.data), "Tag creato.")
        if ok:
            return redirect(url_for("catalog.tags"))
    tag_list = catalog_service.tags_of(actor.family_id)
    usage = {t.id: catalog_service.tag_usage(t.id) for t in tag_list}
    return render_template("catalog/tags.html", form=form, tags=tag_list, usage=usage)


@bp.route("/tag/<int:tag_id>/modifica", methods=["GET", "POST"])
@family_required
def edit_tag(tag_id):
    actor = _actor()
    tag = get_family_object_or_404(Tag, tag_id, actor.family_id)
    form = TagForm(obj=tag)
    if form.validate_on_submit():
        ok, _ = run_service(lambda: catalog_service.update_tag(actor, tag, form.name.data, form.color.data), "Tag aggiornato.")
        if ok:
            return redirect(url_for("catalog.tags"))
    return render_template("catalog/tag_form.html", form=form, tag=tag)


@bp.route("/tag/<int:tag_id>/elimina", methods=["POST"])
@family_required
def delete_tag(tag_id):
    require_post_confirm()
    actor = _actor()
    tag = get_family_object_or_404(Tag, tag_id, actor.family_id)
    run_service(lambda: catalog_service.delete_tag(actor, tag), "Tag eliminato.")
    return redirect(url_for("catalog.tags"))
