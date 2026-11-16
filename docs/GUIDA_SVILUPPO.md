# Guida allo sviluppo

Istruzioni passo passo, pensate anche per chi sta imparando Python e Flask.

## 1. Prerequisiti

- Python **3.11 o superiore** (`python3 --version`)
- Git

## 2. Preparare l'ambiente

```bash
git clone <url-del-repository> LifeTracker
cd LifeTracker

# Ambiente virtuale: una "scatola" con le librerie del progetto, separata dal sistema
python3 -m venv .venv
source .venv/bin/activate        # su Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
```

## 3. Configurazione

```bash
cp .env.example .env
```

Apri `.env` e imposta almeno:

```
SECRET_KEY=<genera con: python -c "import secrets; print(secrets.token_hex(32))">
FLASK_CONFIG=development
```

`SECRET_KEY` firma i cookie di sessione: deve restare segreta e non va mai messa nel codice.

## 4. Creare il database

```bash
flask db upgrade
```

Il comando applica le **migrazioni** (cartella `migrations/versions/`) e crea `instance/lifetracker.db`.

Quando in una fase successiva si modificano i modelli:

```bash
flask db migrate -m "descrizione della modifica"   # genera un nuovo file di migrazione
# controlla il file generato in migrations/versions/
flask db upgrade                                    # applica la modifica al database
flask db check                                      # verifica che modelli e database coincidano
```

## 5. Avviare l'applicazione

```bash
flask run
```

Apri <http://127.0.0.1:5000>, registrati, crea la tua famiglia.

Per provarla dallo smartphone nella stessa rete: `flask run --host 0.0.0.0` e apri `http://<ip-del-pc>:5000`.

## 6. Eseguire i test

```bash
pytest            # tutti i test
pytest -k invito  # solo i test che contengono "invito" nel nome
pytest -x -vv     # si ferma al primo errore, output dettagliato
```

I test usano un database in memoria: non toccano i tuoi dati.

## 7. Comandi di amministrazione

| Comando | A cosa serve |
|---|---|
| `flask lt users` | elenca gli account |
| `flask lt reset-password email@dominio.it` | reimposta una password (non c'è un servizio email) |
| `flask lt unlock email@dominio.it` | sblocca un account bloccato per troppi tentativi |

## 8. Come è organizzato il codice (in breve)

Una richiesta HTTP percorre questi livelli:

```
URL → blueprints/<area>/routes.py → forms.py (validazione) → services/<area>_service.py → models/
                                   ↘ templates/<area>/*.html (risposta)
```

Esempio: "crea famiglia"
1. `app/blueprints/family/routes.py::create` riceve il POST;
2. `FamilyCreateForm` valida il nome e il token CSRF;
3. `family_service.create_family()` crea famiglia e membership admin e scrive l'audit log;
4. redirect alla pagina della famiglia.

Regole del progetto:
- la logica sta nei **servizi**, non nelle route;
- ogni oggetto si cerca **sempre filtrando per la famiglia attiva** (isolamento dei dati);
- ogni POST passa da un form Flask-WTF (protezione CSRF);
- le date nel DB sono in UTC; si mostrano con il filtro `|localdt` (Europe/Rome).

## 9. Librerie frontend

Bootstrap, Bootstrap Icons e Chart.js sono copiati in `app/static/vendor/` (con le licenze), così
l'app funziona anche senza Internet e la Content-Security-Policy può ammettere solo risorse locali.
