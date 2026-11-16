"""Livello dei servizi: qui vive la logica di business.

Le route chiamano i servizi; i servizi modificano i modelli, scrivono l'audit log
e sollevano ServiceError con messaggi pensati per l'utente finale.
"""


class ServiceError(Exception):
    """Errore 'previsto' (input non valido, regola violata): il messaggio è mostrabile all'utente."""


class PermissionDenied(ServiceError):
    """L'utente non ha i permessi per l'operazione richiesta."""
