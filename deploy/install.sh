#!/usr/bin/env bash
# =============================================================================
#  LifeTracker — installazione / aggiornamento su Raspberry Pi OS (Debian)
#
#  Uso (dal Raspberry, anche via SSH dall'iPhone):
#    curl -fsSL https://raw.githubusercontent.com/andpas21/LifeTracker/claude/lifetracker-project-s2wasa/deploy/install.sh | sudo bash
#
#  Variabili opzionali (es.  ... | sudo LT_PORT=8060 bash):
#    LT_PORT    porta HTTP su cui Nginx espone LifeTracker   (default 8050)
#    LT_BRANCH  ramo git da installare                        (default claude/lifetracker-project-s2wasa)
#    LT_DIR     cartella di installazione                     (default /opt/lifetracker)
#    LT_REPO    repository git                                (default https://github.com/andpas21/LifeTracker.git)
#
#  Lo script è idempotente: rilanciato, aggiorna il codice e conserva dati e configurazione.
#  Non modifica altri siti Nginx già presenti (es. il tuo portale): aggiunge solo il proprio.
# =============================================================================
set -euo pipefail

LT_PORT="${LT_PORT:-8050}"
LT_BRANCH="${LT_BRANCH:-claude/lifetracker-project-s2wasa}"
LT_DIR="${LT_DIR:-/opt/lifetracker}"
LT_REPO="${LT_REPO:-https://github.com/andpas21/LifeTracker.git}"
LT_USER="lifetracker"

green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "esegui lo script con sudo."
command -v apt-get >/dev/null || fail "serve un sistema Debian / Raspberry Pi OS."

# --- 1. Pacchetti di sistema --------------------------------------------------
info "Installo i pacchetti necessari (python, nginx, git)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip python3-dev git nginx curl \
  libjpeg-dev zlib1g-dev libwebp-dev >/dev/null

PYV=$(python3 -c 'import sys; print(sys.version_info >= (3, 10))')
[ "$PYV" = "True" ] || fail "serve Python 3.10 o superiore (Raspberry Pi OS Bookworm o più recente)."
git config --global --add safe.directory "$LT_DIR" 2>/dev/null || true

# --- 2. Porta libera? ----------------------------------------------------------
if [ ! -f /etc/nginx/sites-available/lifetracker ] && ss -ltn "( sport = :$LT_PORT )" | grep -q LISTEN; then
  fail "la porta $LT_PORT è già usata da un altro servizio. Rilancia con un'altra porta, es.:  ... | sudo LT_PORT=8060 bash"
fi

# --- 3. Utente di servizio e codice -------------------------------------------
id "$LT_USER" >/dev/null 2>&1 || useradd --system --home "$LT_DIR" --shell /usr/sbin/nologin "$LT_USER"
if [ -d "$LT_DIR/.git" ]; then
  info "Aggiorno il codice ($LT_BRANCH)..."
  git -C "$LT_DIR" fetch --quiet origin "$LT_BRANCH"
  git -C "$LT_DIR" checkout --quiet -B "$LT_BRANCH" "origin/$LT_BRANCH"
else
  info "Scarico LifeTracker in $LT_DIR..."
  git clone --quiet --branch "$LT_BRANCH" "$LT_REPO" "$LT_DIR"
fi
mkdir -p "$LT_DIR/instance"
chown -R "$LT_USER:$LT_USER" "$LT_DIR"

# --- 4. Ambiente Python ------------------------------------------------------
info "Preparo l'ambiente Python (alla prima installazione può richiedere qualche minuto)..."
sudo -u "$LT_USER" python3 -m venv "$LT_DIR/.venv"
sudo -u "$LT_USER" "$LT_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$LT_USER" "$LT_DIR/.venv/bin/pip" install --quiet -r "$LT_DIR/requirements.txt"

# --- 5. Configurazione (.env creato solo la prima volta) -----------------------
if [ ! -f "$LT_DIR/.env" ]; then
  info "Creo la configurazione $LT_DIR/.env con una chiave segreta casuale..."
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  cat > "$LT_DIR/.env" <<ENV
SECRET_KEY=$SECRET
FLASK_CONFIG=production
APP_TIMEZONE=Europe/Rome
# 1 se accedi solo in HTTPS (es. tramite 'tailscale serve')
SESSION_COOKIE_SECURE=0
# 0 = nuovi account solo con codice d'invito (consigliato dopo aver creato il tuo)
ALLOW_REGISTRATION=1
MAX_UPLOAD_MB=10
BACKUP_KEEP=14
LOG_LEVEL=INFO
ENV
  chown "$LT_USER:$LT_USER" "$LT_DIR/.env"
  chmod 600 "$LT_DIR/.env"
fi

# --- 6. Database: backup preventivo e migrazioni --------------------------------
cd "$LT_DIR"
if [ -f "$LT_DIR/instance/lifetracker.db" ]; then
  info "Backup del database prima dell'aggiornamento..."
  sudo -u "$LT_USER" env FLASK_APP=wsgi.py "$LT_DIR/.venv/bin/flask" lt backup >/dev/null
fi
info "Aggiorno la struttura del database..."
sudo -u "$LT_USER" env FLASK_APP=wsgi.py "$LT_DIR/.venv/bin/flask" db upgrade

# --- 7. Servizi systemd -------------------------------------------------------
info "Configuro i servizi systemd..."
cat > /etc/systemd/system/lifetracker.service <<UNIT
[Unit]
Description=LifeTracker (Gunicorn)
After=network.target

[Service]
User=$LT_USER
Group=www-data
WorkingDirectory=$LT_DIR
EnvironmentFile=$LT_DIR/.env
RuntimeDirectory=lifetracker
ExecStart=$LT_DIR/.venv/bin/gunicorn --workers 2 --threads 2 --timeout 60 \\
  --bind unix:/run/lifetracker/gunicorn.sock --umask 007 \\
  --access-logfile - --error-logfile - wsgi:app
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$LT_DIR/instance

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/lifetracker-tasks.service <<UNIT
[Unit]
Description=LifeTracker - attività periodiche (promemoria, obiettivi, riepiloghi, backup)

[Service]
Type=oneshot
User=$LT_USER
WorkingDirectory=$LT_DIR
EnvironmentFile=$LT_DIR/.env
Environment=FLASK_APP=wsgi.py
ExecStart=$LT_DIR/.venv/bin/flask lt run-scheduled
UNIT

cat > /etc/systemd/system/lifetracker-tasks.timer <<UNIT
[Unit]
Description=LifeTracker - esegue le attività periodiche ogni 5 minuti

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now lifetracker.service >/dev/null
systemctl restart lifetracker.service
systemctl enable --now lifetracker-tasks.timer >/dev/null

# --- 8. Nginx (sito dedicato, non tocca gli altri) ------------------------------
info "Configuro Nginx sulla porta $LT_PORT..."
cat > /etc/nginx/sites-available/lifetracker <<NGINX
# LifeTracker — generato da deploy/install.sh
server {
    listen $LT_PORT;
    server_name _;

    client_max_body_size 12m;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;

    location /static/ {
        alias $LT_DIR/app/static/;
        expires 7d;
        access_log off;
    }

    location / {
        proxy_pass http://unix:/run/lifetracker/gunicorn.sock;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$http_host;
        proxy_read_timeout 60s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/lifetracker /etc/nginx/sites-enabled/lifetracker
# Nginx deve poter leggere i file statici
chmod o+x "$LT_DIR" "$LT_DIR/app"
chmod -R o+rX "$LT_DIR/app/static"
nginx -t -q || fail "configurazione Nginx non valida (vedi sopra). Nessun altro sito è stato modificato."
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx || systemctl start nginx

# --- 9. Verifica ------------------------------------------------------------------
info "Verifico che l'app risponda..."
for i in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$LT_PORT/health" >/dev/null 2>&1; then OK=1; break; fi
  sleep 1
done
[ "${OK:-0}" = 1 ] || fail "l'app non risponde. Controlla i log con:  sudo journalctl -u lifetracker -n 50"

LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
TS_IP=$(command -v tailscale >/dev/null && tailscale ip -4 2>/dev/null | head -1 || true)
TS_NAME=$(command -v tailscale >/dev/null && tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null || true)

echo
green "✔ LifeTracker è attivo!"
echo
[ -n "$TS_IP" ]   && echo "   Tailscale:    http://$TS_IP:$LT_PORT"
[ -n "$TS_NAME" ] && echo "                 http://$TS_NAME:$LT_PORT"
[ -n "$LAN_IP" ]  && echo "   Rete di casa: http://$LAN_IP:$LT_PORT"
echo
echo "   Aggiungi questo indirizzo come collegamento nel tuo portale."
echo
echo "   HTTPS (consigliato per installare l'app sull'iPhone con tutte le funzioni PWA):"
echo "     sudo tailscale serve --bg --https=8443 http://127.0.0.1:$LT_PORT"
[ -n "$TS_NAME" ] && echo "     poi apri  https://$TS_NAME:8443"
echo
echo "   Comandi utili:"
echo "     stato:       sudo systemctl status lifetracker"
echo "     log:         sudo journalctl -u lifetracker -f"
echo "     aggiornare:  rilancia questo stesso comando"
echo "     backup ora:  sudo -u $LT_USER bash -c 'cd $LT_DIR && .venv/bin/flask --app wsgi.py lt backup'"
echo
