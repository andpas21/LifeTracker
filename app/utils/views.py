"""Helper condivisi dalle route di tutti i blueprint."""
from flask import abort, flash

from app.services import PermissionDenied, ServiceError
from app.utils.forms import ConfirmForm


def run_service(action, success_message=None):
    """Esegue un'azione di servizio.

    - PermissionDenied → errore 403;
    - ServiceError → messaggio all'utente, restituisce (False, None);
    - successo → messaggio opzionale, restituisce (True, risultato).
    """
    try:
        result = action()
    except PermissionDenied:
        abort(403)
    except ServiceError as exc:
        flash(str(exc), "danger")
        return False, None
    if success_message:
        flash(success_message, "success")
    return True, result


def require_post_confirm():
    """Verifica il token CSRF dei pulsanti-azione (form senza campi)."""
    if not ConfirmForm().validate_on_submit():
        abort(400)


def flash_form_errors(form):
    for field, errors in form.errors.items():
        label = getattr(form, field).label.text if hasattr(form, field) else field
        for error in errors:
            flash(f"{label}: {error}", "danger")
