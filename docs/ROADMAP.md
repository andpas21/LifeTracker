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
- Test automatici (autenticazione, famiglie, inviti, permessi, isolamento tra famiglie, upload,
  CSRF, header, fuso orario con ora legale, CLI).

**Da verificare manualmente** (checklist)
1. Registrazione → crea famiglia → aggiungi un profilo dipendente con foto.
2. Crea un invito, aprilo in una finestra anonima, registra un secondo utente con il link.
3. Cambia ruolo del secondo utente, prova a rimuoverlo, prova "Lascia la famiglia" da admin unico.
4. Da smartphone: barra inferiore, menu, tema scuro, "Aggiungi a schermata Home".

## Fase 2 — Categorie, attività e indicatori ✅
- Categorie e sottocategorie (due livelli), icone (selettore con anteprima), colori, ordinamento, archiviazione.
- Attività con etichetta del contatore ("uscite", "sessioni"…), quantità predefinita del +1, ambito predefinito,
  presenza nella registrazione rapida, colore/icona propri o ereditati.
- Indicatori configurabili senza codice: tipo (intero, decimale, durata, sì/no, testo), unità, significato
  (distanza, durata, frequenza cardiaca…), aggregazione (somma, media, max, min), minimo/massimo, obbligatorio.
- Tag della famiglia. Permessi: creano tutti i membri; modificano amministratori e autori.
- Gli elementi usati nelle registrazioni non si eliminano: si archiviano.

## Fase 3 — Registrazioni e storico ✅
- Registrazione rapida "+1" con un tocco (pulsante centrale su smartphone), anche per i profili dipendenti,
  con notifica e link "aggiungi dettagli".
- Modalità completa: persona, data/ora, quantità, indicatori dinamici, ambito, visibilità, tag (anche nuovi),
  partecipanti, descrizione, note, foto e PDF (ridimensionati/validati).
- Distinzione tra chi ha svolto e chi ha inserito; registrazioni private o visibili alla famiglia.
- Modifica, cestino con ripristino, eliminazione definitiva (admin), storico modifiche con differenze.
- Elenco filtrabile (persona, categoria, attività, tag, ambito, date, testo) con paginazione.
- Correzione critica: le migrazioni SQLite non cancellano più i dati collegati (test di regressione).

## Fase 4 — Dashboard e statistiche ✅
- Dashboard personale, familiare e comparativa (persone, mesi/anni, categorie, attività, io vs famiglia).
- Grafici a linee, area, barre, torta (ciambella), radar, heatmap annuale, barre di progresso obiettivi;
  ogni grafico con vista tabellare.
- Filtri: periodo (giorno, settimana, mese, trimestre, semestre, anno, personalizzato) con navigazione
  avanti/indietro, persona, categoria, attività, ambito, misura omogenea.
- KPI: totale, oggi/settimana/mese, tempo dedicato, giorni attivi, variazione sul periodo precedente.

## Fase 5 — Obiettivi e calendario ✅
- Obiettivi individuali (privati o visibili alla famiglia) e familiari; misure: registrazioni, quantità,
  indicatori (somma/media/max/min secondo l'indicatore); una tantum o ricorrenti (settimana/mese/anno).
- Progresso automatico, notifiche a metà strada / raggiunto / scaduto, storico eventi e risultati per periodo.
- Calendario mese/settimana/giorno con filtri persona/categoria, inserimento diretto e riepilogo del periodo.
- Nuova home: registrazione con un tocco, KPI del giorno/settimana, ultime attività, obiettivi, famiglia.

## Fase 6 — Funzionalità avanzate ✅
- Notifiche in-app con contatore (campanella, titolo della pagina).
- Promemoria personali (una volta, giornalieri, settimanali con giorni scelti, mensili) collegabili a un'attività.
- Riepiloghi settimanali e mensili (pagina + notifica automatica, disattivabili nelle preferenze).
- Esportazione Excel (con foglio di riepilogo) e CSV (formato italiano), con filtri.
- Backup automatici giornalieri (database + file) con rotazione; comandi `lt backup` / `lt restore`.
- Preferenze: tema, riepiloghi, notifiche obiettivi.

## Fase 7 — Installazione su Raspberry Pi ✅
- `deploy/install.sh`: un comando installa o aggiorna (pacchetti, utente di servizio, ambiente Python,
  `.env` con chiave casuale, backup preventivo, migrazioni, Gunicorn + systemd, timer delle attività
  periodiche, sito Nginx dedicato su porta configurabile senza toccare gli altri siti, verifica finale).
- Guida: `docs/INSTALLAZIONE_RASPBERRY.md` (anche da iPhone via Tailscale, HTTPS con `tailscale serve`).
- Verificato in un ambiente Linux con Nginx reale: installazione, aggiornamento, registrazione, upload,
  +1, dashboard e attività periodiche attraverso Nginx.

## Possibili estensioni (da concordare)
- Notifiche push sul telefono (Web Push).
- Integrazione con Strava/Coros per importare automaticamente le uscite sportive.
- Modelli di catalogo suggeriti da importare con un clic.
