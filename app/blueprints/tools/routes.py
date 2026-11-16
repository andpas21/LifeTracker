"""Strumenti: notifiche, promemoria, riepiloghi, esportazione dati."""
from flask import Response, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.tools import bp
from app.blueprints.tools.forms import ExportForm, ReminderForm
from app.services import catalog_service, entry_service, export_service, notification_service, reminder_service, \
    summary_service
from app.services.entry_service import EntryFilters
from app.services.period import local_date_range_utc, parse_date, period_for
from app.utils.security import family_required, get_current_membership, is_safe_next_url
from app.utils.timezone import local_now, local_today
from app.utils.views import flash_form_errors, require_post_confirm, run_service


@bp.route("/strumenti/")
@family_required
def index():
    return render_template("tools/index.html")


# --------------------------------------------------------------------------- notifiche
@bp.route("/notifiche/")
@login_required
def notifications():
    return render_template("tools/notifications.html", items=notification_service.latest(current_user))


@bp.route("/notifiche/<int:notification_id>/apri", methods=["POST"])
@login_required
def open_notification(notification_id):
    require_post_confirm()
    item = notification_service.mark_read(current_user, notification_id)
    if item is None:
        abort(404)
    return redirect(item.link if is_safe_next_url(item.link) else url_for("tools.notifications"))


@bp.route("/notifiche/lette", methods=["POST"])
@login_required
def mark_all_read():
    require_post_confirm()
    notification_service.mark_read(current_user)
    return redirect(url_for("tools.notifications"))


@bp.route("/notifiche/pulisci", methods=["POST"])
@login_required
def clear_read():
    require_post_confirm()
    notification_service.delete_read(current_user)
    return redirect(url_for("tools.notifications"))


@bp.route("/notifiche/conteggio")
@login_required
def unread_count():
    return {"unread": notification_service.unread_count(current_user)}


# --------------------------------------------------------------------------- promemoria
def _reminder_form(actor, obj=None):
    form = ReminderForm(obj=obj)
    form.activity_id.choices = [(0, "— Nessuna —")] + catalog_service.activity_choices(actor.family_id)
    return form


def _reminder_data(form) -> dict:
    return {
        "title": form.title.data, "message": form.message.data, "activity_id": form.activity_id.data or None,
        "frequency": form.frequency.data, "time_of_day": form.time_of_day.data, "start_date": form.start_date.data,
        "weekdays": form.weekdays.data, "day_of_month": form.day_of_month.data,
    }


@bp.route("/strumenti/promemoria", methods=["GET", "POST"])
@family_required
def reminders():
    actor = get_current_membership()
    form = _reminder_form(actor)
    if request.method == "GET":
        form.start_date.data = local_today()
        form.time_of_day.data = local_now().time().replace(second=0, microsecond=0)
        form.weekdays.data = [local_today().weekday()]
    if form.validate_on_submit():
        ok, _ = run_service(lambda: reminder_service.save(actor, None, _reminder_data(form)), "Promemoria creato.")
        if ok:
            return redirect(url_for("tools.reminders"))
    elif request.method == "POST":
        flash_form_errors(form)
    return render_template("tools/reminders.html", form=form, reminders=reminder_service.list_for(actor),
                           labels=reminder_service.FREQUENCY_LABELS)


def _reminder_or_404(reminder_id):
    reminder = reminder_service.get_own(get_current_membership(), reminder_id)
    if reminder is None:
        abort(404)
    return reminder


@bp.route("/strumenti/promemoria/<int:reminder_id>/modifica", methods=["GET", "POST"])
@family_required
def edit_reminder(reminder_id):
    actor = get_current_membership()
    reminder = _reminder_or_404(reminder_id)
    form = _reminder_form(actor, reminder)
    if request.method == "GET":
        form.activity_id.data = reminder.activity_id or 0
        form.weekdays.data = reminder.weekday_list
    if form.validate_on_submit():
        ok, _ = run_service(lambda: reminder_service.save(actor, reminder, _reminder_data(form)), "Promemoria aggiornato.")
        if ok:
            return redirect(url_for("tools.reminders"))
    return render_template("tools/reminder_form.html", form=form, reminder=reminder)


@bp.route("/strumenti/promemoria/<int:reminder_id>/attiva", methods=["POST"])
@family_required
def toggle_reminder(reminder_id):
    require_post_confirm()
    reminder = _reminder_or_404(reminder_id)
    run_service(lambda: reminder_service.toggle(get_current_membership(), reminder))
    return redirect(url_for("tools.reminders"))


@bp.route("/strumenti/promemoria/<int:reminder_id>/elimina", methods=["POST"])
@family_required
def delete_reminder(reminder_id):
    require_post_confirm()
    reminder = _reminder_or_404(reminder_id)
    run_service(lambda: reminder_service.delete(get_current_membership(), reminder), "Promemoria eliminato.")
    return redirect(url_for("tools.reminders"))


# --------------------------------------------------------------------------- riepiloghi
@bp.route("/riepiloghi")
@family_required
def summaries():
    actor = get_current_membership()
    kind = "month" if request.args.get("tipo") == "mese" else "week"
    period = period_for(kind, parse_date(request.args.get("rif")) or local_today())
    return render_template("tools/summary.html", s=summary_service.build(actor, period), kind=kind,
                           tipo="mese" if kind == "month" else "settimana")


# --------------------------------------------------------------------------- esportazione
@bp.route("/strumenti/esporta")
@family_required
def export():
    actor = get_current_membership()
    form = ExportForm(request.args)
    form.persona.choices = [(0, "Tutti")] + [(p.id, p.display_name) for p in entry_service.family_profiles(actor.family_id)]
    form.categoria.choices = [(0, "Tutte")] + catalog_service.category_choices(actor.family_id)
    form.attivita.choices = [(0, "Tutte")] + catalog_service.activity_choices(actor.family_id)
    if "formato" not in request.args:
        return render_template("tools/export.html", form=form)
    if not form.validate():
        flash_form_errors(form)
        return render_template("tools/export.html", form=form)
    start = local_date_range_utc(form.da.data, form.da.data)[0] if form.da.data else None
    end = local_date_range_utc(form.a.data, form.a.data)[1] if form.a.data else None
    filters = EntryFilters(profile_id=form.persona.data or None, category_id=form.categoria.data or None,
                           activity_id=form.attivita.data or None, date_from=start, date_to=end)
    stamp = local_today().isoformat()
    if form.formato.data == "csv":
        return Response(export_service.to_csv(actor, filters), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="lifetracker-{stamp}.csv"'})
    return Response(export_service.to_xlsx(actor, filters),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="lifetracker-{stamp}.xlsx"'})
