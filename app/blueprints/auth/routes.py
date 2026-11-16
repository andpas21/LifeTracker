from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.blueprints.auth import bp
from app.blueprints.auth.forms import LoginForm, RegisterForm
from app.extensions import db
from app.services import ServiceError, auth_service, family_service
from app.services.audit_service import log_action
from app.utils.security import is_safe_next_url


@bp.route("/accedi", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = auth_service.authenticate(form.email.data, form.password.data)
        except ServiceError as exc:
            flash(str(exc), "danger")
        else:
            login_user(user, remember=form.remember.data)
            next_url = request.args.get("next")
            return redirect(next_url if is_safe_next_url(next_url) else url_for("main.home"))
    return render_template("auth/login.html", form=form)


@bp.route("/registrati", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    allow_open = current_app.config["ALLOW_REGISTRATION"]
    form = RegisterForm()
    if request.method == "GET" and request.args.get("invito"):
        form.invite_code.data = request.args["invito"]

    if form.validate_on_submit():
        code = (form.invite_code.data or "").strip()
        if code and family_service.find_valid_invitation(code) is None:
            form.invite_code.errors.append("Codice d'invito non valido, scaduto o già utilizzato.")
        elif not code and not allow_open:
            form.invite_code.errors.append("La registrazione è possibile solo con un codice d'invito.")
        else:
            try:
                user = auth_service.register_user(form.email.data, form.password.data, form.display_name.data)
            except ServiceError as exc:
                flash(str(exc), "danger")
            else:
                login_user(user)
                if code:
                    try:
                        membership = family_service.accept_invitation(user, code)
                        flash(f"Benvenuto nella famiglia {membership.family.name}!", "success")
                        return redirect(url_for("main.home"))
                    except ServiceError as exc:  # invito usato da altri nel frattempo
                        flash(str(exc), "warning")
                flash("Account creato. Ora crea la tua famiglia o unisciti a una esistente.", "success")
                return redirect(url_for("family.welcome"))
    return render_template("auth/register.html", form=form, allow_open=allow_open)


@bp.route("/esci", methods=["POST"])
@login_required
def logout():
    log_action("auth.logout", family_id=current_user.current_family_id)
    db.session.commit()
    logout_user()
    flash("Sei uscito da LifeTracker.", "info")
    return redirect(url_for("auth.login"))
