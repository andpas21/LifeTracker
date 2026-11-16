from flask import abort, redirect, render_template, request, url_for

from app.blueprints.goals import bp
from app.blueprints.goals.forms import GoalForm
from app.extensions import db
from app.models import Activity, MetricDefinition
from app.services import catalog_service, goal_service
from app.utils.security import family_required, get_current_membership
from app.utils.timezone import local_today
from app.utils.views import require_post_confirm, run_service


def _goal_or_404(goal_id):
    goal = goal_service.get_visible_goal(get_current_membership(), goal_id)
    if goal is None:
        abort(404)
    return goal


def _prepare(form, actor):
    form.owner_profile_id.choices = [(p.id, p.display_name) for p in goal_service.owner_choices(actor)]
    form.category_id.choices = [(0, "Tutte le categorie")] + catalog_service.category_choices(actor.family_id)
    form.activity_id.choices = [(0, "Tutte le attività")] + catalog_service.activity_choices(actor.family_id)
    metrics = db.session.scalars(
        db.select(MetricDefinition).join(Activity)
        .where(Activity.family_id == actor.family_id, MetricDefinition.is_archived.is_(False),
               MetricDefinition.data_type.in_(("integer", "decimal", "duration")))
        .order_by(Activity.name, MetricDefinition.sort_order)
    )
    form.metric_definition_id.choices = [(0, "—")] + [
        (m.id, f"{m.activity.name} › {m.name}{' (minuti)' if m.data_type == 'duration' else (' (' + m.unit + ')' if m.unit else '')}")
        for m in metrics
    ]
    if not actor.is_admin:
        form.scope.choices = [("personal", "Individuale")]
    return form


@bp.route("/")
@family_required
def index():
    actor = get_current_membership()
    status = "history" if request.args.get("stato") == "storico" else "active"
    return render_template("goals/index.html", goals=goal_service.list_goals(actor, status), status=status)


@bp.route("/nuovo", methods=["GET", "POST"])
@family_required
def new():
    actor = get_current_membership()
    form = _prepare(GoalForm(), actor)
    if request.method == "GET":
        form.owner_profile_id.data = actor.profile_id
        form.start_date.data = local_today()
        form.activity_id.data = request.args.get("attivita", 0, type=int)
    if form.validate_on_submit():
        ok, goal = run_service(lambda: goal_service.create_goal(actor, form.to_data()), "Obiettivo creato.")
        if ok:
            return redirect(url_for("goals.detail", goal_id=goal.id))
    return render_template("goals/form.html", form=form, goal=None)


@bp.route("/<int:goal_id>")
@family_required
def detail(goal_id):
    actor = get_current_membership()
    goal = _goal_or_404(goal_id)
    return render_template(
        "goals/detail.html", goal=goal, p=goal_service.compute(goal), can_edit=goal_service.can_edit(actor, goal),
        history=goal_service.history_periods(goal), event_labels=goal_service.EVENT_LABELS,
    )


@bp.route("/<int:goal_id>/modifica", methods=["GET", "POST"])
@family_required
def edit(goal_id):
    actor = get_current_membership()
    goal = _goal_or_404(goal_id)
    if not goal_service.can_edit(actor, goal):
        abort(403)
    form = _prepare(GoalForm(obj=goal), actor)
    if request.method == "GET":
        form.owner_profile_id.data = goal.owner_profile_id or actor.profile_id
        form.category_id.data = goal.category_id or 0
        form.activity_id.data = goal.activity_id or 0
        form.metric_definition_id.data = goal.metric_definition_id or 0
    if form.validate_on_submit():
        ok, _ = run_service(lambda: goal_service.update_goal(actor, goal, form.to_data()), "Obiettivo aggiornato.")
        if ok:
            return redirect(url_for("goals.detail", goal_id=goal.id))
    return render_template("goals/form.html", form=form, goal=goal)


@bp.route("/<int:goal_id>/archivia", methods=["POST"])
@family_required
def archive(goal_id):
    require_post_confirm()
    goal = _goal_or_404(goal_id)
    archived = goal.status != "archived"
    run_service(lambda: goal_service.set_archived(get_current_membership(), goal, archived),
                "Obiettivo archiviato." if archived else "Obiettivo riaperto.")
    return redirect(url_for("goals.detail", goal_id=goal_id))


@bp.route("/<int:goal_id>/elimina", methods=["POST"])
@family_required
def delete(goal_id):
    require_post_confirm()
    goal = _goal_or_404(goal_id)
    ok, _ = run_service(lambda: goal_service.delete_goal(get_current_membership(), goal), "Obiettivo eliminato.")
    return redirect(url_for("goals.index") if ok else url_for("goals.detail", goal_id=goal_id))
