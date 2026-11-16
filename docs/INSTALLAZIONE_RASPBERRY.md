# Installazione su Raspberry Pi

LifeTracker si installa con **un solo comando**, anche da remoto con l'iPhone tramite Tailscale.
Lo script `deploy/install.sh` è idempotente: rilanciandolo aggiorna l'app conservando dati e configurazione.

## Requisiti

- Raspberry Pi con **Raspberry Pi OS Bookworm** (o Debian 12+), anche Lite, con Python 3.10 o superiore
- Accesso SSH al Raspberry
- (Consigliato) **Tailscale** attivo sul Raspberry e sull'iPhone

## 1. Collegarsi al Raspberry dall'iPhone (fuori casa)

1. Sull'iPhone apri l'app **Tailscale** e verifica che sia connessa.
2. Installa un'app SSH, ad esempio **Termius** (gratuita).
3. In Termius crea un nuovo host:
   - *Hostname*: l'IP Tailscale del Raspberry (100.x.y.z, lo vedi nell'app Tailscale) oppure il suo nome (es. `raspberrypi`)
   - *Username* e *password* del Raspberry (es. `pi`)
4. Connettiti.

## 2. Installare

Nel terminale del Raspberry incolla:

```bash
curl -fsSL https://raw.githubusercontent.com/andpas21/LifeTracker/claude/lifetracker-project-s2wasa/deploy/install.sh | sudo bash
```

La prima installazione richiede alcuni minuti (scarica le librerie Python). Alla fine lo script mostra
gli indirizzi, ad esempio:

```
✔ LifeTracker è attivo!
   Tailscale:    http://100.101.102.103:8050
                 http://raspberrypi.tail1234.ts.net:8050
   Rete di casa: http://192.168.1.50:8050
```

**Porta già occupata?** Se il portale (o un'altra app) usa già la porta 8050, scegline un'altra:

```bash
curl -fsSL https://raw.githubusercontent.com/andpas21/LifeTracker/claude/lifetracker-project-s2wasa/deploy/install.sh | sudo LT_PORT=8060 bash
```

## 3. Aggiungerlo al portale

LifeTracker ha un proprio sito Nginx sulla sua porta e **non modifica gli altri siti** già configurati
(compreso il tuo portale). Nel portale basta aggiungere un collegamento all'indirizzo mostrato dallo script
(es. `http://raspberrypi.tail1234.ts.net:8050`).

## 4. Primo accesso

1. Apri l'indirizzo dall'iPhone e **registrati**: sarai il primo utente.
2. Crea la tua famiglia, poi invita gli altri da *Famiglia → Inviti*.
3. Quando tutti hanno l'account, conviene chiudere la registrazione libera:
   ```bash
   sudo nano /opt/lifetracker/.env        # imposta ALLOW_REGISTRATION=0
   sudo systemctl restart lifetracker
   ```
   (i nuovi membri potranno comunque registrarsi con un codice d'invito)

## 5. HTTPS e app sull'iPhone (consigliato)

Su HTTPS l'app si installa sulla schermata Home con tutte le funzioni PWA (pagina offline, avvio rapido).
Tailscale fornisce un certificato valido gratuitamente:

```bash
sudo tailscale serve --bg --https=8443 http://127.0.0.1:8050
```

Poi apri `https://<nome-raspberry>.<tailnet>.ts.net:8443` (il nome lo mostra lo script) e da Safari:
**Condividi → Aggiungi alla schermata Home**.

Se usi solo HTTPS puoi rendere i cookie ancora più sicuri: in `/opt/lifetracker/.env` imposta
`SESSION_COOKIE_SECURE=1` e riavvia (`sudo systemctl restart lifetracker`).

> Se la porta 8443 è già usata da `tailscale serve` per il portale, scegline un'altra (es. `--https=10000`).

## 6. Cosa installa lo script

| Elemento | Dove |
|---|---|
| Codice e ambiente Python | `/opt/lifetracker` (utente di sistema `lifetracker`) |
| Configurazione (chiave segreta generata) | `/opt/lifetracker/.env` (permessi 600) |
| Database, foto, allegati, log, backup | `/opt/lifetracker/instance/` |
| Servizio web (Gunicorn) | `lifetracker.service` |
| Attività periodiche ogni 5 minuti (promemoria, obiettivi, riepiloghi, backup giornaliero) | `lifetracker-tasks.timer` |
| Sito Nginx | `/etc/nginx/sites-available/lifetracker` |

## 7. Manutenzione

| Operazione | Comando |
|---|---|
| Aggiornare all'ultima versione | rilancia il comando di installazione (fa prima un backup) |
| Stato del servizio | `sudo systemctl status lifetracker` |
| Log in tempo reale | `sudo journalctl -u lifetracker -f` |
| Log applicativo | `sudo tail -f /opt/lifetracker/instance/logs/lifetracker.log` |
| Backup immediato | `sudo -u lifetracker bash -c 'cd /opt/lifetracker && .venv/bin/flask --app wsgi.py lt backup'` |
| Elenco backup | `ls -lh /opt/lifetracker/instance/backups/` (ne vengono tenuti 14, uno al giorno) |
| Reimpostare una password | `sudo -u lifetracker bash -c 'cd /opt/lifetracker && .venv/bin/flask --app wsgi.py lt reset-password email@esempio.it'` |
| Sbloccare un account | `... lt unlock email@esempio.it` |

### Ripristinare un backup

```bash
sudo systemctl stop lifetracker
sudo -u lifetracker bash -c 'cd /opt/lifetracker && .venv/bin/flask --app wsgi.py lt restore instance/backups/lifetracker-AAAAMMGG-HHMMSS.zip'
sudo -u lifetracker bash -c 'cd /opt/lifetracker && .venv/bin/flask --app wsgi.py db upgrade'
sudo systemctl start lifetracker
```

Consiglio: copia periodicamente la cartella `instance/backups` su un altro dispositivo (chiavetta, NAS, PC),
così i dati sono al sicuro anche se la scheda SD si guasta.

## 8. Disinstallare

```bash
sudo systemctl disable --now lifetracker lifetracker-tasks.timer
sudo rm /etc/systemd/system/lifetracker*.service /etc/systemd/system/lifetracker-tasks.timer
sudo rm /etc/nginx/sites-enabled/lifetracker /etc/nginx/sites-available/lifetracker && sudo systemctl reload nginx
sudo rm -rf /opt/lifetracker          # ATTENZIONE: elimina anche dati e backup
sudo userdel lifetracker
```
