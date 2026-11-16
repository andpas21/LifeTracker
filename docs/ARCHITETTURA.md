# LifeTracker — Architettura del sistema

> Documento tecnico di riferimento. Viene aggiornato al termine di ogni fase.
> Stato attuale: **Fase 1 completata** (fondamenta, utenti, famiglie). Vedi `docs/ROADMAP.md`.

---

## 1. Visione d'insieme

LifeTracker è una web application *server-rendered* (Flask + Jinja2) con piccole
porzioni dinamiche in JavaScript (registrazione rapida, grafici Chart.js, calendario).
Questa scelta è adatta a un Raspberry Pi: poco carico sul server, nessun build step
JavaScript, pagine leggere e funzionanti anche su connessioni lente.

```
 Browser / PWA (smartphone, PC)
          │  HTTPS (Tailscale)
          ▼
 ┌──────────────────┐
 │      Nginx       │  file statici, limiti upload, header di sicurezza, proxy
 └────────┬─────────┘
          │ unix socket
 ┌────────▼─────────┐
 │    Gunicorn      │  2–3 worker sync (gestito da systemd)
 └────────┬─────────┘
 ┌────────▼──────────────────────────────────────────────┐
 │  Flask app (create_app)                               │
 │  Blueprint  →  Services  →  Models (SQLAlchemy)       │
 │     ▲             │                                   │
 │   Forms       Utils (tempo, permessi, upload, audit)  │
 └────────┬──────────────────────────────────────────────┘
          ▼
   SQLite (instance/lifetracker.db)  ── predisposto per PostgreSQL
   instance/uploads/ (foto profilo, allegati — fuori da /static)
   instance/backups/ (backup automatici)
```

### Livelli

| Livello | Responsabilità | Regola |
|---|---|---|
| **Routes** (`app/blueprints/*/routes.py`) | HTTP: legge la richiesta, chiama i servizi, sceglie il template | Niente logica di business, niente query complesse |
| **Forms** (`forms.py`) | Validazione input + CSRF (Flask-WTF) | Ogni POST passa da un form |
| **Services** (`app/services/`) | Logica di business, permessi, transazioni, audit | Unico punto in cui si modificano i dati |
| **Models** (`app/models/`) | Tabelle, relazioni, vincoli | Nessuna dipendenza da Flask request |
| **Utils** (`app/utils/`) | Funzioni trasversali: fuso orario, decoratori, upload | Pure e testabili |

### Multi-tenancy e isolamento

* Ogni dato "di dominio" (categorie, attività, registrazioni, tag, obiettivi, …) ha una colonna `family_id`.
* La **famiglia attiva** dell'utente è salvata in `users.current_family_id`.
* Ogni query passa per helper di servizio che filtrano sempre per `family_id` della famiglia attiva
  (`get_family_object_or_404(Model, id)`): un id di un'altra famiglia restituisce **404**, mai i dati.
* I permessi si verificano lato server con decoratori (`@family_required`, `@family_admin_required`) e
  con funzioni di servizio (`can_edit_entry`, …). L'interfaccia nasconde i pulsanti non permessi, ma non
  è mai l'unico controllo.

---

## 2. Persone, utenti e ruoli

Il modello separa **chi accede** da **chi svolge le attività**:

* **User** = account con credenziali (email + password).
* **Profile** = persona. Ogni User ha esattamente un Profile. Un Profile *dipendente* (es. un bambino)
  **non** ha User: viene gestito dagli amministratori della famiglia.
* **FamilyMember** = appartenenza di un Profile a una Family con un ruolo.

| Ruolo | Credenziali | Può |
|---|---|---|
| `admin` | sì | tutto nella famiglia: membri, inviti, ruoli, catalogo, dati di tutti |
| `member` | sì | registrare per sé e per i dipendenti, gestire i propri dati, vedere i dati condivisi |
| `dependent` | no | — (è un soggetto delle registrazioni, non un utente) |

Un utente può appartenere a più famiglie (es. famiglia propria e dei genitori) e passa dall'una all'altra
con il selettore famiglia. Una famiglia deve sempre avere almeno un amministratore.

**Invito membri**: l'amministratore genera un codice d'invito (monouso, con scadenza e ruolo). Il link
`/famiglia/unisciti/<codice>` può essere inviato via WhatsApp/email; chi lo apre si registra o accede e
entra nella famiglia. Nel database si salva solo l'**hash** del codice.

---

## 3. Modello dati

Convenzioni:
* Chiavi primarie intere `id`.
* Date/ore salvate in **UTC** (`DateTime` naive in UTC); conversione a `Europe/Rome` solo in presentazione
  e nell'input dei form (`app/utils/timezone.py`). Le aggregazioni per giorno/settimana/mese convertono
  prima nel fuso della famiglia.
* `created_at` / `updated_at` su tutte le entità principali.
* Archiviazione logica (`is_archived`) per catalogo; cancellazione logica (`deleted_at`) per le registrazioni,
  così storico e audit restano coerenti.
* Valori numerici con `Numeric(14, 4)` (nessun errore di arrotondamento float, compatibile PostgreSQL).
* Vincoli `CheckConstraint` per gli enum (portabili tra SQLite e PostgreSQL).
* Nomi dei vincoli tramite `naming_convention`, necessari ad Alembic (batch mode in SQLite).

### 3.1 Diagramma

```
families 1───* family_members *───1 profiles 0..1───1 users
   │                                   │
   ├──* family_invitations             ├──* activity_entries (performed_by)
   ├──* categories (self-ref parent)   └──* entry_participants
   │       └──* activities
   │               └──* metric_definitions
   ├──* activity_entries ──* metric_values *──1 metric_definitions
   │       ├──* entry_tags *──1 tags
   │       ├──* entry_participants
   │       ├──* attachments
   │       └──* entry_revisions (storico modifiche)
   ├──* goals ──* goal_events
   ├──* reminders
   ├──* notifications
   └──* audit_logs
```

### 3.2 Tabelle

**families** — gruppo familiare
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| name | str(120) | not null |
| timezone | str(64) | default `Europe/Rome` |
| created_by_user_id | FK users | null on delete |
| created_at, updated_at | datetime | |

**users** — account
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| email | str(255) | unique, minuscolo, indicizzato |
| password_hash | str(255) | scrypt (Werkzeug) |
| is_active | bool | |
| current_family_id | FK families | famiglia attiva, null on delete |
| theme | str(10) | `auto` / `light` / `dark` |
| failed_login_count | int | protezione brute force |
| locked_until | datetime | blocco temporaneo |
| last_login_at, created_at, updated_at | datetime | |

**profiles** — persona (con o senza account)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| user_id | FK users | unique, **nullable** (null = dipendente) |
| display_name | str(80) | not null |
| birth_date | date | opzionale |
| color | str(7) | colore `#rrggbb` nei grafici |
| avatar_filename | str(255) | file in `instance/uploads/avatars` |
| bio | str(500) | |
| created_at, updated_at | | |

**family_members** — appartenenza e ruolo
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK families | cascade |
| profile_id | FK profiles | cascade |
| role | str(16) | check in (`admin`,`member`,`dependent`) |
| joined_at | datetime | |
| | | **unique(family_id, profile_id)**, indice su profile_id |

**family_invitations**
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK families | cascade |
| code_hash | str(64) | sha256 del codice, unique |
| role | str(16) | `admin` / `member` |
| note | str(120) | es. "per Marco" |
| created_by_user_id | FK users | |
| expires_at | datetime | |
| accepted_at, accepted_by_user_id | | null finché non usato |
| revoked_at | datetime | |

**categories** — categorie e sottocategorie (Fase 2)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK families | cascade, indicizzato |
| parent_id | FK categories | null = categoria principale |
| name | str(80) | unique(family_id, parent_id, name) |
| description | str(500) | |
| icon | str(64) | nome Bootstrap Icon |
| color | str(7) | |
| sort_order | int | |
| is_archived | bool | |
| created_by_user_id, created_at, updated_at | | |

**activities** (Fase 2)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK families | |
| category_id | FK categories | restrict |
| name | str(80) | unique(family_id, name) |
| description, icon, color | | colore/icona ereditati dalla categoria se vuoti |
| count_label | str(40) | etichetta del contatore, es. "uscite", "sessioni" |
| default_quantity | Numeric | default 1 (il "+1") |
| default_scope | str | `personal` / `family` |
| is_favorite_quick | bool | mostrata nella barra di registrazione rapida |
| sort_order, is_archived, created_by_user_id, timestamps | | |

**metric_definitions** — indicatori configurabili (Fase 2)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| activity_id | FK activities | cascade |
| name | str(60) | es. "Chilometri" |
| key | str(40) | slug stabile, unique(activity_id, key) |
| data_type | str(16) | `integer`, `decimal`, `duration` (secondi), `boolean`, `text` |
| unit | str(20) | es. `km`, `m`, `bpm`, `W`, `pagine` |
| kind | str(20) | semantica per confronti: `distance`, `duration`, `elevation`, `count`, `heart_rate`, `power`, `other` |
| aggregation | str(8) | `sum`, `avg`, `max`, `min` — come si aggrega nei grafici |
| min_value, max_value | Numeric | validazione |
| is_required | bool | |
| sort_order, is_archived | | |

> Il campo `kind` + `unit` permette confronti **omogenei**: es. sommare la *durata* di attività diverse ha
> senso; sommare frequenze cardiache no (si usa `avg`). La dashboard comparativa confronta solo indicatori
> con stesso `kind` e unità compatibile.

**activity_entries** — registrazioni (Fase 3)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK families | indicizzato |
| activity_id | FK activities | restrict |
| performed_by_profile_id | FK profiles | **chi ha svolto** |
| created_by_user_id | FK users | **chi ha inserito** |
| occurred_at | datetime UTC | indicizzato (family_id, occurred_at) |
| quantity | Numeric | default 1 — distinto dal conteggio registrazioni |
| scope | str | `personal` / `family` |
| visibility | str | `private` (solo autore e chi l'ha svolta + admin) / `family` |
| description | str(500) | |
| notes | text | |
| deleted_at | datetime | cancellazione logica |
| created_at, updated_at | | |

**entry_participants** (Fase 3) — `entry_id`, `profile_id`, PK composta: partecipanti alle attività familiari.

**metric_values** (Fase 3)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| entry_id | FK activity_entries | cascade |
| metric_definition_id | FK metric_definitions | restrict |
| value_numeric | Numeric | integer/decimal/duration/boolean(0/1) |
| value_text | str(500) | per `text` |
| | | unique(entry_id, metric_definition_id) |

**tags** — `id`, `family_id`, `name` (unique per famiglia), `color`.
**entry_tags** — `entry_id`, `tag_id` (PK composta).

**entry_revisions** — storico modifiche delle registrazioni (Fase 3)
`id`, `entry_id`, `changed_by_user_id`, `changed_at`, `action` (`create`/`update`/`delete`/`restore`), `snapshot` (JSON con lo stato completo dopo la modifica).

**attachments** (Fase 3/6)
`id`, `family_id`, `entry_id` (cascade), `stored_filename` (nome casuale), `original_filename`, `mime_type`, `size_bytes`, `uploaded_by_user_id`, `created_at`.

**goals** (Fase 5)
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK | |
| owner_profile_id | FK profiles | null = obiettivo familiare |
| scope | str | `personal` / `family` |
| visibility | str | `private` / `family` |
| title, description | | |
| target_type | str | `count` (registrazioni), `quantity`, `metric` |
| activity_id / category_id | FK | ambito dell'obiettivo (almeno uno, o "tutte") |
| metric_definition_id | FK | se target_type = metric |
| target_value | Numeric | |
| recurrence | str | `none`, `weekly`, `monthly`, `yearly` |
| start_date, end_date | date | |
| status | str | `active`, `completed`, `expired`, `archived` |
| completed_at | datetime | |
| created_by_user_id, timestamps | | |

**goal_events** — storico obiettivi: `goal_id`, `event` (`created`, `progress_50`, `completed`, `expired`, …), `value`, `created_at`.

**reminders** (Fase 6) — `id`, `family_id`, `user_id`, `activity_id` (opz.), `title`, `message`, `frequency` (`once`/`daily`/`weekly`/`monthly`), `time_of_day`, `weekdays` (es. `0,2,4`), `next_run_at` (UTC), `last_sent_at`, `is_active`.

**notifications** (Fase 5/6) — `id`, `user_id`, `family_id`, `type`, `title`, `body`, `link`, `is_read`, `created_at`.

**audit_logs** — registro azioni
| colonna | tipo | note |
|---|---|---|
| id | int PK | |
| family_id | FK | nullable |
| user_id | FK | nullable |
| action | str(40) | es. `auth.login`, `family.member_role_changed` |
| entity_type, entity_id | | oggetto coinvolto |
| details | JSON (text) | valori prima/dopo |
| ip_address | str(45) | |
| created_at | datetime | indicizzato |

---

## 4. Struttura delle cartelle

```
LifeTracker/
├── app/
│   ├── __init__.py            # create_app(): factory dell'applicazione
│   ├── config.py              # configurazioni Development/Testing/Production da variabili d'ambiente
│   ├── extensions.py          # db, migrate, login_manager, csrf
│   ├── cli.py                 # comandi `flask lt ...`
│   ├── models/                # un file per area del dominio
│   ├── services/              # logica di business (auth, family, profile, audit, …)
│   ├── utils/                 # timezone, decoratori di sicurezza, upload immagini
│   ├── blueprints/
│   │   ├── auth/              # registrazione, login, logout
│   │   ├── main/              # home, offline page, service worker, manifest
│   │   ├── family/            # famiglia, membri, inviti, dipendenti
│   │   ├── profile/           # profilo, foto, password, preferenze
│   │   ├── catalog/           # (Fase 2) categorie, attività, indicatori, tag
│   │   ├── entries/           # (Fase 3) registrazioni rapide/complete, storico
│   │   ├── dashboard/         # (Fase 4) dashboard + API JSON per i grafici
│   │   ├── calendar/          # (Fase 5)
│   │   ├── goals/             # (Fase 5)
│   │   └── tools/             # (Fase 6) export, backup, promemoria, notifiche
│   ├── templates/             # base.html, partials/, una cartella per blueprint
│   └── static/
│       ├── css/app.css
│       ├── js/app.js
│       ├── img/               # icone PWA
│       └── vendor/            # Bootstrap, Bootstrap Icons, Chart.js (locali, niente CDN)
├── migrations/                # Alembic (Flask-Migrate)
├── tests/                     # pytest
├── deploy/                    # (Fase 7) nginx, systemd, script installazione/backup
├── docs/                      # questa documentazione
├── instance/                  # (non versionata) database, upload, backup, log
├── wsgi.py                    # entry point per Gunicorn
├── requirements.txt
└── .env.example
```

---

## 5. Flussi di navigazione

```
[Visitatore] ─► /accedi ──► credenziali ok ──► ha una famiglia? ──no──► /famiglia/benvenuto
     │                                            │                      ├─ Crea famiglia
     └─► /registrati ─────────────────────────────┘                      └─ Unisciti con codice
                                                  │ sì
                                                  ▼
                                                 Home  ◄──── selettore famiglia (se più di una)
```

Navigazione principale (sidebar desktop / barra inferiore + menu su smartphone):

| Voce | Fase | Contenuto |
|---|---|---|
| Home | 1 → 4 | riepilogo; dalla Fase 4 diventa la dashboard personale |
| **+ Registra** | 3 | pulsante centrale sempre visibile (bottom bar) → registrazione rapida |
| Registrazioni | 3 | storico filtrabile |
| Dashboard | 4 | personale / famiglia / confronti |
| Calendario | 5 | mese / settimana / giorno |
| Obiettivi | 5 | |
| Catalogo | 2 | categorie, attività, indicatori, tag |
| Famiglia | 1 | membri, inviti, dipendenti |
| Profilo | 1 | dati personali, foto, password, tema |

Le voci compaiono nel menu **solo quando la relativa fase è implementata** (nessun link non funzionante).

### Flusso registrazione rapida (Fase 3)
1. Tocco su **+** → foglio con le attività preferite (griglia di pulsanti colorati).
2. Tocco su un'attività → `POST` immediato con quantità = default (+1), persona = me, ora = adesso.
3. Toast "Ciclismo +1 · Aggiungi dettagli" → il link apre il form completo precompilato.

---

## 6. Schermate e funzionalità

| Schermata | URL | Funzioni |
|---|---|---|
| Accedi | `/accedi` | email, password, "ricordami", blocco dopo 5 tentativi falliti (15 min) |
| Registrati | `/registrati` | nome, email, password (min 10 caratteri), conferma; codice invito facoltativo |
| Benvenuto | `/famiglia/benvenuto` | crea famiglia / inserisci codice invito |
| Home | `/` | saluto, famiglia attiva, membri, scorciatoie (in Fase 4 diventa dashboard) |
| Famiglia | `/famiglia/` | membri con ruolo e foto; per admin: rinomina, ruoli, rimozione, inviti, dipendenti |
| Inviti | `/famiglia/inviti` | crea codice (ruolo, scadenza, nota), lista, revoca |
| Unisciti | `/famiglia/unisciti` e `/famiglia/unisciti/<codice>` | accetta invito |
| Dipendente | `/famiglia/dipendenti/nuovo`, `/<id>/modifica` | nome, data di nascita, colore, foto |
| Profilo | `/profilo/` | nome, colore, bio, data di nascita, foto |
| Sicurezza | `/profilo/password` | cambio password |
| Preferenze | `/profilo/preferenze` | tema (automatico/chiaro/scuro) |
| Catalogo | `/catalogo/…` | (Fase 2) CRUD categorie/sottocategorie/attività/indicatori/tag |
| Registrazioni | `/registrazioni/…` | (Fase 3) rapida, completa, modifica, elimina, storico revisioni, allegati |
| Dashboard | `/dashboard/{personale,famiglia,confronti}` | (Fase 4) KPI, grafici, filtri |
| Calendario | `/calendario` | (Fase 5) |
| Obiettivi | `/obiettivi` | (Fase 5) |
| Strumenti | `/strumenti` | (Fase 6) export CSV/Excel, backup, promemoria, notifiche |

---

## 7. Sicurezza

| Requisito | Implementazione |
|---|---|
| Hashing password | Werkzeug `generate_password_hash` (scrypt) |
| CSRF | Flask-WTF `CSRFProtect` globale (form e richieste fetch con header `X-CSRFToken`) |
| Sessioni | Flask-Login, cookie `HttpOnly`, `SameSite=Lax`, `Secure` configurabile, protezione sessione "strong" |
| Brute force | contatore tentativi + blocco temporaneo per account |
| Validazione | WTForms lato server su ogni input; vincoli DB |
| Permessi | decoratori + servizi, verifica `family_id` su ogni oggetto |
| Upload | estensioni consentite, dimensione massima, verifica reale con Pillow, ri-codifica (rimuove EXIF/GPS), nome file casuale, file serviti da route autenticata (non da `/static`) |
| Header | CSP restrittiva (solo risorse locali), `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` |
| Errori | pagine 400/403/404/413/429/500 personalizzate, rollback della sessione DB |
| Log | file a rotazione `instance/logs/lifetracker.log` + audit log su DB |
| Configurazione | variabili d'ambiente / file `.env` (mai segreti nel codice) |

---

## 8. Fuso orario

* Riferimento: `Europe/Rome` (configurabile per famiglia, colonna `families.timezone`).
* Il DB contiene sempre UTC; `app/utils/timezone.py` fornisce `utcnow()`, `to_local()`, `to_utc()`,
  `local_today()` e il filtro Jinja `|localdt`.
* I confini di giorno/settimana/mese per statistiche e calendario si calcolano nel fuso locale e poi
  si convertono in UTC per la query (gestisce correttamente il cambio ora legale).
