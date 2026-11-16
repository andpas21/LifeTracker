from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.blueprints.family import bp
from app.blueprints.family.forms import (
    ConfirmForm,
    DependentForm,
    FamilyCreateForm,
    FamilyDeleteForm,
    FamilyRenameForm,
    InvitationForm,
    JoinFamilyForm,
    RoleForm,
)
from app.extensions import db
from app.models import AuditLog
from app.services import ServiceError, family_service, profile_service
from app.utils.security import family_admin_required, family_required, get_current_membership, is_safe_next_url

AUDIT_PAGE_SIZE = 50


# --------------------------------------------------------------------------- onboarding
@bp.route("/benvenuto")
@login_required
def welcome():
    return render_template(
        "family/welcome.html",
        create_form=FamilyCreateForm(),
        join_form=JoinFamilyForm(),
        memberships=family_service.memberships_of(current_user),
    )


@bp.route("/nuova", methods=["POST"])
@login_required
def create():
    form = FamilyCreateForm()
    if form.validate_on_submit():
        family = family_service.create_family(current_user, form.name.data)
        flash(f"Famiglia «{family.name}» creata. Sei l'amministratore.", "success")
        return redirect(url_for("family.overview"))
    for error in form.name.errors:
        flash(error, "danger")
    return redirect(url_for("family.welcome"))


@bp.route("/unisciti", methods=["GET", "POST"])
@bp.route("/unisciti/<code>", methods=["GET", "POST"])
@login_required
def join(code=None):
    form = JoinFamilyForm()
    if code and request.method == "GET":
        form.code.data = code
    invitation = family_service.find_valid_invitation(form.code.data) if form.code.data else None
    if form.validate_on_submit():
        try:
            membership = family_service.accept_invitation(current_user, form.code.data)
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash(f"Ora fai parte della famiglia «{membership.family.name}».", "success")
            return redirect(url_for("main.home"))
    return render_template("family/join.html", form=form, invitation=invitation)


@bp.route("/cambia/<int:family_id>", methods=["POST"])
@login_required
def switch(family_id):
    form = ConfirmForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        family = family_service.switch_family(current_user, family_id)
    except ServiceError:
        abort(404)
    flash(f"Famiglia attiva: {family.name}", "info")
    next_url = request.form.get("next")
    return redirect(next_url if is_safe_next_url(next_url) else url_for("main.home"))


# --------------------------------------------------------------------------- famiglia
@bp.route("/")
@family_required
def overview():
    membership = get_current_membership()
    return render_template(
        "family/overview.html",
        membership=membership,
        family=membership.family,
        members=family_service.family_members(membership.family),
        role_form=RoleForm(),
        confirm_form=ConfirmForm(),
    )


@bp.route("/impostazioni", methods=["GET", "POST"])
@family_admin_required
def settings():
    membership = get_current_membership()
    rename_form = FamilyRenameForm(obj=membership.family)
    delete_form = FamilyDeleteForm(prefix="del")
    if rename_form.submit.data and rename_form.validate_on_submit():
        family_service.rename_family(membership, rename_form.name.data)
        flash("Nome della famiglia aggiornato.", "success")
        return redirect(url_for("family.settings"))
    return render_template(
        "family/settings.html", family=membership.family, rename_form=rename_form, delete_form=delete_form
    )


@bp.route("/elimina", methods=["POST"])
@family_admin_required
def delete():
    form = FamilyDeleteForm(prefix="del")
    if not form.validate_on_submit():
        abort(400)
    try:
        family_service.delete_family(get_current_membership(), form.confirm_name.data)
    except ServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("family.settings"))
    flash("Famiglia eliminata.", "info")
    return redirect(url_for("main.home"))


@bp.route("/esci", methods=["POST"])
@family_required
def leave():
    if not ConfirmForm().validate_on_submit():
        abort(400)
    try:
        family_service.leave_family(get_current_membership())
    except ServiceError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("family.overview"))
    flash("Hai lasciato la famiglia.", "info")
    return redirect(url_for("main.home"))


# --------------------------------------------------------------------------- membri
def _member_or_404(member_id):
    member = family_service.get_member_or_none(get_current_membership().family, member_id)
    if member is None:
        abort(404)
    return member


@bp.route("/membri/<int:member_id>/ruolo", methods=["POST"])
@family_admin_required
def change_role(member_id):
    member = _member_or_404(member_id)
    form = RoleForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        family_service.change_role(get_current_membership(), member, form.role.data)
        flash(f"Ruolo di {member.profile.display_name} aggiornato.", "success")
    except ServiceError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("family.overview"))


@bp.route("/membri/<int:member_id>/rimuovi", methods=["POST"])
@family_admin_required
def remove_member(member_id):
    member = _member_or_404(member_id)
    if not ConfirmForm().validate_on_submit():
        abort(400)
    name = member.profile.display_name
    try:
        family_service.remove_member(get_current_membership(), member)
        flash(f"{name} è stato rimosso dalla famiglia.", "info")
    except ServiceError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("family.overview"))


# --------------------------------------------------------------------------- inviti
@bp.route("/inviti", methods=["GET", "POST"])
@family_admin_required
def invitations():
    membership = get_current_membership()
    form = InvitationForm()
    if form.validate_on_submit():
        try:
            _, code = family_service.create_invitation(
                membership, form.role.data, form.valid_days.data, form.note.data
            )
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            # Il codice in chiaro si mostra una sola volta: lo passiamo alla GET tramite sessione.
            session["new_invite_code"] = code
            return redirect(url_for("family.invitations"))
    new_code = session.pop("new_invite_code", None)
    return render_template(
        "family/invitations.html",
        form=form,
        confirm_form=ConfirmForm(),
        invitations=family_service.list_invitations(membership.family),
        new_code=new_code,
        new_link=url_for("family.join", code=new_code, _external=True) if new_code else None,
    )


@bp.route("/inviti/<int:invitation_id>/revoca", methods=["POST"])
@family_admin_required
def revoke_invitation(invitation_id):
    if not ConfirmForm().validate_on_submit():
        abort(400)
    try:
        family_service.revoke_invitation(get_current_membership(), invitation_id)
        flash("Invito revocato.", "info")
    except ServiceError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("family.invitations"))


# --------------------------------------------------------------------------- dipendenti
@bp.route("/dipendenti/nuovo", methods=["GET", "POST"])
@family_admin_required
def add_dependent():
    membership = get_current_membership()
    form = DependentForm()
    if form.validate_on_submit():
        profile = family_service.add_dependent(
            membership, form.display_name.data, form.birth_date.data, form.color.data, form.bio.data
        )
        if form.avatar.data:
            try:
                profile_service.set_avatar(profile, form.avatar.data, family_id=membership.family_id)
            except ServiceError as exc:
                flash(f"Profilo creato, ma la foto non è stata salvata: {exc}", "warning")
                return redirect(url_for("family.edit_dependent", profile_id=profile.id))
        flash(f"Profilo di {profile.display_name} creato.", "success")
        return redirect(url_for("family.overview"))
    return render_template("family/dependent_form.html", form=form, profile=None)


@bp.route("/dipendenti/<int:profile_id>/modifica", methods=["GET", "POST"])
@family_admin_required
def edit_dependent(profile_id):
    membership = get_current_membership()
    dependent = family_service.get_dependent_or_none(membership.family, profile_id)
    if dependent is None:
        abort(404)
    profile = dependent.profile
    form = DependentForm(obj=profile)
    if form.validate_on_submit():
        profile_service.update_profile(
            profile,
            display_name=form.display_name.data,
            birth_date=form.birth_date.data,
            color=form.color.data,
            bio=form.bio.data,
            family_id=membership.family_id,
        )
        if form.avatar.data:
            try:
                profile_service.set_avatar(profile, form.avatar.data, family_id=membership.family_id)
            except ServiceError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("family.edit_dependent", profile_id=profile.id))
        flash("Profilo aggiornato.", "success")
        return redirect(url_for("family.overview"))
    return render_template(
        "family/dependent_form.html", form=form, profile=profile, confirm_form=ConfirmForm()
    )


@bp.route("/dipendenti/<int:profile_id>/foto/rimuovi", methods=["POST"])
@family_admin_required
def remove_dependent_avatar(profile_id):
    membership = get_current_membership()
    dependent = family_service.get_dependent_or_none(membership.family, profile_id)
    if dependent is None:
        abort(404)
    if not ConfirmForm().validate_on_submit():
        abort(400)
    profile_service.remove_avatar(dependent.profile, family_id=membership.family_id)
    flash("Foto rimossa.", "info")
    return redirect(url_for("family.edit_dependent", profile_id=profile_id))


# --------------------------------------------------------------------------- registro attività
@bp.route("/registro")
@family_admin_required
def audit_log():
    membership = get_current_membership()
    page = max(request.args.get("pagina", 1, type=int), 1)
    pagination = db.paginate(
        db.select(AuditLog)
        .filter_by(family_id=membership.family_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()),
        page=page,
        per_page=AUDIT_PAGE_SIZE,
        error_out=False,
    )
    return render_template("family/audit_log.html", pagination=pagination)
