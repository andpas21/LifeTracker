# Roadmap e stato delle fasi

Ogni fase si chiude solo dopo verifica: test automatici verdi, prova manuale, documentazione aggiornata.

## Fase 1 — Fondamenta, utenti e famiglie ✅

**Realizzato**
- Struttura modulare: app factory, configurazione da variabili d'ambiente, blueprint, servizi, utilità.
- Database: `users`, `profiles`, `families`, `family_members`, `family_invitations`, `audit_logs`
  + prima migrazione Alembic (portabile su PostgreSQL: FK circolare families↔users gestita).
- Registrazione e accesso (password scrypt, blocco dopo 5 tentativi falliti per 15 minuti,
  "ricordami", protezione dagli open redirect, registrazione libera disattivabile).
- Famiglie: creazione, rinomina, eliminazione con conferma del nome, uscita, più famiglie per utente
  con selettore della famiglia attiva.
- Ruoli: amministratore / membro / profilo dipendente; almeno un amministratore sempre garantito.
- Inviti con codice monouso (salvato solo come hash), scadenza 1–30 giorni, link e condivisione,
  revoca; registrazione direttamente con codice invito.
- Profili dipendenti (senza credenziali) con foto, data di nascita, colore.
- Profilo personale: nome, colore, presentazione, data di nascita, foto (validata, ridimensionata,
  ri-codificata in WebP senza EXIF, servita solo ai membri delle stesse famiglie).
- Cambio password, preferenze tema (automatico/chiaro/scuro) + pulsante rapido.
- Registro attività della famiglia (audit log) consultabile dagli amministratori.
- Interfaccia responsive: sidebar desktop, barra inferiore e menu laterale su smartphone, tema scuro.
- PWA: manifest, icone, service worker (cache solo delle risorse statiche, pagina offline).
- Sicurezza: CSRF globale, CSP restrittiva, header di sicurezza, pagine di errore, log a rotazione.
- Comandi CLI: `flask lt users | reset-password | unlock`.
- 34 test automatici (autenticazione, famiglie, inviti, permessi, isolamento tra famiglie, upload,
  CSRF, header, fuso orario con ora legale, CLI).

**Da verificare manualmente** (checklist)
1. Registrazione → crea famiglia → aggiungi un profilo dipendente con foto.
2. Crea un invito, aprilo in una finestra anonima, registra un secondo utente con il link.
3. Cambia ruolo del secondo utente, prova a rimuoverlo, prova "Lascia la famiglia" da admin unico.
4. Da smartphone: barra inferiore, menu, tema scuro, "Aggiungi a schermata Home".

## Fase 2 — Categorie, attività e indicatori ⏳
Tabelle `categories` (con sottocategorie), `activities`, `metric_definitions`, `tags`.
CRUD completo con icone (selettore Bootstrap Icons) e colori; indicatori configurabili
(tipo di dato, unità, aggregazione, semantica per confronti omogenei, min/max, obbligatorio);
archiviazione invece della cancellazione quando esistono registrazioni; ordinamento.

## Fase 3 — Registrazioni e storico
`activity_entries`, `entry_participants`, `metric_values`, `entry_tags`, `entry_revisions`, `attachments`.
Registrazione rapida "+1" (pulsante centrale nella barra mobile), modalità completa, modifica,
eliminazione logica e ripristino, storico revisioni, elenco filtrabile, allegati e foto.

## Fase 4 — Dashboard e statistiche
Dashboard personale, familiare e comparativa; API JSON per i grafici; Chart.js (linee, barre, torta,
area, radar), heatmap calendario; filtri per utente, categoria, attività, periodo, ambito.

## Fase 5 — Obiettivi e calendario
`goals`, `goal_events`, `notifications`. Calendario mese/settimana/giorno con inserimento diretto.

## Fase 6 — Funzionalità avanzate
Promemoria (`reminders`), notifiche in-app, riepiloghi settimanali/mensili, export CSV/Excel,
backup automatici, preferenze aggiuntive.

## Fase 7 — Installazione su Raspberry Pi
Script di installazione, Gunicorn + systemd, Nginx, Tailscale (HTTPS con `tailscale serve`),
backup pianificati con timer systemd, guida all'aggiornamento.
