from datetime import datetime

from flask import abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from app.blueprints.entries import bp
from app.blueprints.entries.forms import QuickAddForm, build_entry_form
from app.extensions import db
from app.models import SCOPE_LABELS, Activity, Attachment
from app.services import PermissionDenied, ServiceError, catalog_service, entry_service
from app.services.common import get_family_object
from app.services.entry_service import EntryData, EntryFilters, EntryValidationError
from app.services.period import local_date_range_utc, parse_date
from app.utils.formatting import fmt_number, parse_decimal
from app.utils.security import family_required, get_current_membership
from app.utils.timezone import local_now, to_local, to_utc
from app.utils.views import require_post_confirm, run_service

PAGE_SIZE = 30


def _actor():
    return get_current_membership()


def _entry_or_404(entry_id, include_deleted=False):
    entry = entry_service.get_visible_entry(_actor(), entry_id, include_deleted=include_deleted)
    if entry is None:
        abort(404)
    return entry


# --------------------------------------------------------------------------- elenco
def filters_from_args(args) -> EntryFilters:
    date_from, date_to = parse_date(args.get("da")), parse_date(args.get("a"))
    start = local_date_range_utc(date_from, date_from)[0] if date_from else None
    end = local_date_range_utc(date_to, date_to)[1] if date_to else None
    return EntryFilters(
        profile_id=args.get("persona", type=int),
        category_id=args.get("categoria", type=int),
        activity_id=args.get("attivita", type=int),
        tag_id=args.get("tag", type=int),
        scope=args.get("ambito") or None,
        date_from=start,
        date_to=end,
        text=(args.get("q") or "").strip() or None,
        deleted=args.get("stato") == "eliminate",
    )


@bp.route("/")
@family_required
def index():
    actor = _actor()
    filters = filters_from_args(request.args)
    page = max(request.args.get("pagina", 1, type=int), 1)
    pagination = db.paginate(entry_service.filtered_query(actor, filters), page=page, per_page=PAGE_SIZE,
                             error_out=False)
    args = {k: v for k, v in request.args.items() if k != "pagina" and v}
    return render_template(
        "entries/index.html",
        pagination=pagination,
        filters=filters,
        args=args,
        profiles=entry_service.family_profiles(actor.family_id),
        categories=catalog_service.category_choices(actor.family_id),
        activities=catalog_service.activity_choices(actor.family_id),
        tags=catalog_service.tags_of(actor.family_id),
        scope_labels=SCOPE_LABELS,
    )


# --------------------------------------------------------------------------- modalità rapida
@bp.route("/rapida")
@family_required
def quick():
    actor = _actor()
    form = QuickAddForm()
    form.performed_by_profile_id.choices = [(p.id, p.display_name) for p in entry_service.performer_choices(actor)]
    form.performed_by_profile_id.data = request.args.get("per", actor.profile_id, type=int)
    activities = catalog_service.quick_activities(actor.family_id)
    others = [a for a in catalog_service.active_activities(actor.family_id) if not a.is_quick]
    return render_template("entries/quick.html", form=form, activities=activities, others=others,
                           can_create_catalog=catalog_service.can_create(actor))


@bp.route("/rapida/<int:activity_id>", methods=["POST"])
@family_required
def quick_add(activity_id):
    actor = _actor()
    form = QuickAddForm()
    form.performed_by_profile_id.choices = [(p.id, p.display_name) for p in entry_service.performer_choices(actor)]
    wants_json = request.accept_mimetypes.best == "application/json"
    if not form.validate_on_submit():
        if wants_json:
            return jsonify(ok=False, message="Richiesta non valida, ricarica la pagina."), 400
        abort(400)
    try:
        entry = entry_service.quick_add(actor, activity_id, form.performed_by_profile_id.data)
    except PermissionDenied:
        abort(403)
    except ServiceError as exc:
        if wants_json:
            return jsonify(ok=False, message=str(exc)), 400
        flash(str(exc), "danger")
        return redirect(url_for("entries.quick"))
    who = "" if entry.performed_by_profile_id == actor.profile_id else f" per {entry.performed_by.display_name}"
    message = f"{entry.activity.name} +{fmt_number(entry.quantity)}{who}"
    details_url = url_for("entries.edit", entry_id=entry.id)
    if wants_json:
        return jsonify(ok=True, message=message, details_url=details_url, entry_id=entry.id)
    flash(f"{message} registrato. Puoi aggiungere i dettagli dalla registrazione.", "success")
    return redirect(url_for("entries.quick", per=form.performed_by_profile_id.data))


# --------------------------------------------------------------------------- modalità completa
def _prepare_form(actor, activity, entry=None, **kwargs):
    form = build_entry_form(activity, **kwargs)
    form.activity_id.choices = catalog_service.activity_choices(actor.family_id)
    if entry and entry.activity.is_archived:
        form.activity_id.choices.insert(0, (entry.activity_id, f"{entry.activity.name} (archiviata)"))
    performers = entry_service.performer_choices(actor)
    if entry and entry.performed_by_profile_id not in {p.id for p in performers}:
        performers.append(entry.performed_by)
    form.performed_by_profile_id.choices = [(p.id, p.display_name) for p in performers]
    form.tag_ids.choices = [(t.id, t.name) for t in catalog_service.tags_of(actor.family_id)]
    form.participant_ids.choices = [(p.id, p.display_name) for p in entry_service.family_profiles(actor.family_id)]
    return form


def _form_to_data(form) -> EntryData:
    try:
        quantity = parse_decimal(form.quantity.data)
    except ValueError:
        quantity = None
    occurred = to_utc(datetime.combine(form.occurred_date.data, form.occurred_time.data))
    return EntryData(
        activity_id=form.activity_id.data,
        performed_by_profile_id=form.performed_by_profile_id.data,
        occurred_at=occurred,
        quantity=quantity,
        scope=form.scope.data,
        visibility=form.visibility.data,
        description=form.description.data,
        notes=form.notes.data,
        tag_ids=form.tag_ids.data or [],
        new_tags=[t for t in (form.new_tags.data or "").split(",") if t.strip()],
        participant_ids=form.participant_ids.data or [],
        metric_inputs={metric.id: getattr(form, name).data for name, metric in form.metric_field_names},
    )


def _apply_errors(form, exc: EntryValidationError):
    for name, message in exc.errors.items():
        field = getattr(form, name, None)
        if field is not None:
            field.errors = list(field.errors) + [message]
        else:
            flash(message, "danger")
    flash(str(exc), "danger")


@bp.route("/nuova", methods=["GET", "POST"])
@family_required
def new():
    actor = _actor()
    activity_id = request.values.get("attivita", type=int) or request.form.get("activity_id", type=int)
    activity = get_family_object(Activity, activity_id, actor.family_id) if activity_id else None
    if activity is None or activity.is_archived:
        activities = catalog_service.active_activities(actor.family_id)
        return render_template("entries/choose_activity.html", activities=activities,
                               day=request.args.get("data"),
                               can_create_catalog=catalog_service.can_create(actor))
    form = _prepare_form(actor, activity)
    if request.method == "GET":
        now = local_now()
        form.activity_id.data = activity.id
        form.performed_by_profile_id.data = request.args.get("per", actor.profile_id, type=int)
        form.occurred_date.data = parse_date(request.args.get("data")) or now.date()
        form.occurred_time.data = now.time().replace(second=0, microsecond=0)
        form.quantity.data = fmt_number(activity.default_quantity, 4).replace(".", "")
        form.scope.data = activity.default_scope
    if form.validate_on_submit():
        if form.activity_id.data != activity.id:  # attività cambiata senza JavaScript
            return redirect(url_for("entries.new", attivita=form.activity_id.data))
        try:
            entry = entry_service.create_entry(actor, _form_to_data(form), request.files.getlist(form.attachments.name))
        except PermissionDenied:
            abort(403)
        except EntryValidationError as exc:
            _apply_errors(form, exc)
        else:
            flash(f"{entry.activity.name} registrata.", "success")
            return redirect(url_for("entries.detail", entry_id=entry.id))
    return render_template("entries/form.html", form=form, activity=activity, entry=None,
                           max_mb=entry_service.max_upload_mb())


@bp.route("/<int:entry_id>")
@family_required
def detail(entry_id):
    actor = _actor()
    entry = _entry_or_404(entry_id, include_deleted=True)
    return render_template(
        "entries/detail.html",
        entry=entry,
        can_edit=entry_service.can_edit(actor, entry),
        values=[(v.definition, entry_service.format_metric_value(v)) for v in
                sorted(entry.metric_values, key=lambda v: (v.definition.sort_order, v.definition.id))],
        history=entry_service.revision_history(entry),
        scope_labels=SCOPE_LABELS,
    )


@bp.route("/<int:entry_id>/modifica", methods=["GET", "POST"])
@family_required
def edit(entry_id):
    actor = _actor()
    entry = _entry_or_404(entry_id)
    if not entry_service.can_edit(actor, entry):
        abort(403)
    activity = entry.activity
    requested = request.args.get("attivita", type=int)
    if requested and requested != entry.activity_id:
        activity = get_family_object(Activity, requested, actor.family_id) or abort(404)
    if request.method == "POST" and request.form.get("activity_id", type=int) not in (None, activity.id):
        new_activity = get_family_object(Activity, request.form.get("activity_id", type=int), actor.family_id)
        if new_activity:
            return redirect(url_for("entries.edit", entry_id=entry.id, attivita=new_activity.id))
    form = _prepare_form(actor, activity, entry)
    if request.method == "GET":
        local = to_local(entry.occurred_at)
        form.activity_id.data = activity.id
        form.performed_by_profile_id.data = entry.performed_by_profile_id
        form.occurred_date.data = local.date()
        form.occurred_time.data = local.time().replace(second=0, microsecond=0)
        form.quantity.data = fmt_number(entry.quantity, 4).replace(".", "")
        form.scope.data = entry.scope
        form.visibility.data = entry.visibility
        form.description.data = entry.description
        form.notes.data = entry.notes
        form.tag_ids.data = [t.id for t in entry.tags]
        form.participant_ids.data = [p.id for p in entry.participants]
        for name, metric in form.metric_field_names:
            getattr(form, name).data = entry_service.metric_input_value(entry.value_for(metric.id))
    if form.validate_on_submit():
        try:
            entry_service.update_entry(actor, entry, _form_to_data(form), request.files.getlist(form.attachments.name))
        except PermissionDenied:
            abort(403)
        except EntryValidationError as exc:
            db.session.rollback()
            _apply_errors(form, exc)
        else:
            flash("Registrazione aggiornata.", "success")
            return redirect(url_for("entries.detail", entry_id=entry.id))
    return render_template("entries/form.html", form=form, activity=activity, entry=entry,
                           max_mb=entry_service.max_upload_mb())


@bp.route("/<int:entry_id>/elimina", methods=["POST"])
@family_required
def delete(entry_id):
    require_post_confirm()
    entry = _entry_or_404(entry_id)
    ok, _ = run_service(lambda: entry_service.delete_entry(_actor(), entry), "Registrazione spostata nel cestino.")
    return redirect(url_for("entries.index") if ok else url_for("entries.detail", entry_id=entry_id))


@bp.route("/<int:entry_id>/ripristina", methods=["POST"])
@family_required
def restore(entry_id):
    require_post_confirm()
    entry = _entry_or_404(entry_id, include_deleted=True)
    run_service(lambda: entry_service.restore_entry(_actor(), entry), "Registrazione ripristinata.")
    return redirect(url_for("entries.detail", entry_id=entry_id))


@bp.route("/<int:entry_id>/elimina-definitivamente", methods=["POST"])
@family_required
def purge(entry_id):
    require_post_confirm()
    entry = _entry_or_404(entry_id, include_deleted=True)
    ok, _ = run_service(lambda: entry_service.purge_entry(_actor(), entry), "Registrazione eliminata definitivamente.")
    return redirect(url_for("entries.index", stato="eliminate") if ok else url_for("entries.detail", entry_id=entry_id))


# --------------------------------------------------------------------------- allegati
def _attachment_or_404(attachment_id):
    actor = _actor()
    attachment = get_family_object(Attachment, attachment_id, actor.family_id)
    if attachment is None or entry_service.get_visible_entry(actor, attachment.entry_id, include_deleted=True) is None:
        abort(404)
    return attachment


@bp.route("/allegati/<int:attachment_id>")
@family_required
def attachment(attachment_id):
    item = _attachment_or_404(attachment_id)
    folder, name = entry_service.attachment_path(item)
    response = send_from_directory(
        folder, name, mimetype=item.mime_type,
        as_attachment=request.args.get("scarica") == "1",
        download_name=item.original_filename if not item.is_image else item.original_filename.rsplit(".", 1)[0] + ".webp",
    )
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return response


@bp.route("/allegati/<int:attachment_id>/elimina", methods=["POST"])
@family_required
def delete_attachment(attachment_id):
    require_post_confirm()
    item = _attachment_or_404(attachment_id)
    entry_id = item.entry_id
    run_service(lambda: entry_service.delete_attachment(_actor(), item), "Allegato eliminato.")
    return redirect(url_for("entries.detail", entry_id=entry_id))
