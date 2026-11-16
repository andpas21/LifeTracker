from flask import abort, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required

from app.blueprints.profile import bp
from app.blueprints.profile.forms import AvatarForm, PasswordChangeForm, PreferencesForm, ProfileForm
from app.extensions import db
from app.models import THEMES, Profile
from app.services import ServiceError, auth_service, family_service, profile_service
from app.utils.forms import ConfirmForm
from app.utils.security import is_safe_next_url
from app.utils.uploads import upload_dir


@bp.route("/", methods=["GET", "POST"])
@login_required
def edit():
    profile = current_user.profile
    form = ProfileForm(obj=profile)
    if form.validate_on_submit():
        profile_service.update_profile(
            profile,
            display_name=form.display_name.data,
            birth_date=form.birth_date.data,
            color=form.color.data,
            bio=form.bio.data,
            family_id=current_user.current_family_id,
        )
        flash("Profilo aggiornato.", "success")
        return redirect(url_for("profile.edit"))
    return render_template(
        "profile/edit.html",
        form=form,
        avatar_form=AvatarForm(),
        confirm_form=ConfirmForm(),
        profile=profile,
        memberships=family_service.memberships_of(current_user),
    )


@bp.route("/foto", methods=["POST"])
@login_required
def upload_avatar():
    form = AvatarForm()
    if form.validate_on_submit():
        try:
            profile_service.set_avatar(current_user.profile, form.avatar.data, current_user.current_family_id)
            flash("Foto profilo aggiornata.", "success")
        except ServiceError as exc:
            flash(str(exc), "danger")
    else:
        for error in form.avatar.errors:
            flash(error, "danger")
    return redirect(url_for("profile.edit"))


@bp.route("/foto/rimuovi", methods=["POST"])
@login_required
def remove_avatar():
    if not ConfirmForm().validate_on_submit():
        abort(400)
    profile_service.remove_avatar(current_user.profile, current_user.current_family_id)
    flash("Foto profilo rimossa.", "info")
    return redirect(url_for("profile.edit"))


@bp.route("/avatar/<int:profile_id>")
@login_required
def avatar(profile_id):
    """Serve la foto solo a chi condivide almeno una famiglia con quel profilo."""
    if not family_service.shares_family(current_user, profile_id):
        abort(404)
    profile = db.session.get(Profile, profile_id)
    if profile is None or not profile.avatar_filename:
        abort(404)
    response = send_from_directory(upload_dir("avatars"), profile.avatar_filename, mimetype="image/webp")
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = PasswordChangeForm()
    if form.validate_on_submit():
        try:
            auth_service.change_password(current_user, form.current_password.data, form.new_password.data)
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Password aggiornata.", "success")
            return redirect(url_for("profile.edit"))
    return render_template("profile/password.html", form=form)


@bp.route("/preferenze", methods=["GET", "POST"])
@login_required
def preferences():
    form = PreferencesForm(obj=current_user)
    if form.validate_on_submit():
        current_user.weekly_summary = form.weekly_summary.data
        current_user.monthly_summary = form.monthly_summary.data
        current_user.goal_notifications = form.goal_notifications.data
        auth_service.set_theme(current_user, form.theme.data)
        flash("Preferenze salvate.", "success")
        return redirect(url_for("profile.preferences"))
    return render_template("profile/preferences.html", form=form)


@bp.route("/tema", methods=["POST"])
@login_required
def cycle_theme():
    """Pulsante rapido nella barra: automatico → chiaro → scuro → automatico."""
    if not ConfirmForm().validate_on_submit():
        abort(400)
    next_theme = THEMES[(THEMES.index(current_user.theme) + 1) % len(THEMES)]
    auth_service.set_theme(current_user, next_theme)
    next_url = request.form.get("next")
    return redirect(next_url if is_safe_next_url(next_url) else url_for("main.home"))
