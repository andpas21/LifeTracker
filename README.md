# LifeTracker

Web application multiutente di **Life Analytics** per monitorare le attività quotidiane, personali e
familiari con il sistema **"+1"**: ogni attività svolta si registra con un tocco, si arricchisce di
indicatori (km, minuti, pagine…) e diventa statistiche, grafici, obiettivi e confronti.

- **Backend**: Python 3.11+ · Flask · SQLAlchemy · Alembic (Flask-Migrate)
- **Frontend**: Jinja2 · Bootstrap 5.3 · Bootstrap Icons · Chart.js (tutto in locale, nessuna CDN)
- **Database**: SQLite (predisposto per PostgreSQL)
- **Produzione**: Raspberry Pi OS Lite · Nginx · Gunicorn · systemd · Tailscale · PWA installabile

## Stato del progetto

| Fase | Contenuto | Stato |
|---|---|---|
| 1 | Fondamenta, utenti, famiglie | ✅ completata |
| 2 | Categorie, attività, indicatori | ⏳ prossima |
| 3 | Registrazioni e storico | — |
| 4 | Dashboard e statistiche | — |
| 5 | Obiettivi e calendario | — |
| 6 | Funzionalità avanzate | — |
| 7 | Installazione su Raspberry Pi | — |

Dettagli in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Documentazione

- [`docs/ARCHITETTURA.md`](docs/ARCHITETTURA.md) — architettura, modello dati, cartelle, flussi, schermate, sicurezza
- [`docs/GUIDA_SVILUPPO.md`](docs/GUIDA_SVILUPPO.md) — installazione in locale passo passo, comandi utili, test
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — fasi di sviluppo e funzionalità di ciascuna

## Avvio rapido (sviluppo)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # poi imposta SECRET_KEY e FLASK_CONFIG=development
flask db upgrade              # crea il database
flask run                     # http://127.0.0.1:5000
pytest                        # esegue i test
```
