#!/bin/bash

###############################################################################
# LDC-100 Boot Utility - Installation Script
# 
# This script sets up the boot utility with:
# - System dependencies installation
# - Git repository clone
# - Python virtual environment creation
# - Requirements installation
# - Systemd service configuration and activation
###############################################################################

# Configurazione
REPO_URL="https://github.com/nadaluttilogicahs/LDC-100-boot.git"
APP_NAME="boot"
LDC_BASE_DIR="/home/lg58/LDC-100"
APP_DIR="${LDC_BASE_DIR}/${APP_NAME}"
SERVICE_USER="lg58"
SERVICE_NAME="ldc-100-boot.service"
DATA_DIR="${LDC_BASE_DIR}/data

echo "🚀 Installazione ${APP_NAME}..."

# Verifica se è root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Esegui con sudo: sudo bash install.sh"
    exit 1
fi

# Step 1: Installa dipendenze sistema
echo "📦 Installazione dipendenze sistema..."
apt update
apt install -y python3 python3-pip python3-venv git libatlas-base-dev libopenblas-dev

# Step 2: Crea directory app
echo "📁 Creazione directory ${APP_DIR}..."
mkdir -p ${APP_DIR}

# Dai i permessi a lg58 PRIMA di clonare
chown ${SERVICE_USER}:${SERVICE_USER} ${APP_DIR}

cd ${APP_DIR}

# Step 3: Clona repository
echo "📥 Clone repository..."
if [ -d ".git" ]; then
    echo "Repository già esistente, aggiornamento..."
    sudo -u ${SERVICE_USER} git pull
else
    sudo -u ${SERVICE_USER} git clone ${REPO_URL} .
fi

# Step 4: Crea virtual environment
echo "🐍 Creazione virtual environment..."
sudo -u ${SERVICE_USER} python3 -m venv venv

# Step 5: Installa requirements
echo "📚 Installazione requirements..."
sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/pip install --upgrade pip
sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/pip install -r requirements.txt

# Step 6: Imposta permessi
echo "🔒 Impostazione permessi..."
chown -R ${SERVICE_USER}:${SERVICE_USER} ${APP_DIR}
chmod -R 750 ${APP_DIR}

# Step 7: Crea boot.sh launcher script
echo "🔧 Creazione boot launcher script..."
cat > ${LDC_BASE_DIR}/boot.sh << 'EOFBOOTSH'
#!/bin/bash
# LDC-100 Boot Launcher Script
# Activates virtual environment and launches boot utility

BOOT_DIR="/home/lg58/LDC-100/boot/app"
VENV_DIR="$BOOT_DIR/venv"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Launch boot utility
cd "$BOOT_DIR"
python3 de01boot.py
EOFBOOTSH

chmod +x ${LDC_BASE_DIR}/boot.sh
chown ${SERVICE_USER}:${SERVICE_USER} ${LDC_BASE_DIR}/boot.sh

# Step 8: Verifica che la directory dati esista
if [ ! -d "${DATA_DIR}" ]; then
    echo "⚠️  ATTENZIONE: La directory dati ${DATA_DIR} non esiste!"
    echo "   Assicurati che esista prima di avviare il servizio."
fi

# Step 9: Crea systemd service
echo "🔧 Creazione systemd service..."
cat > /etc/systemd/system/${SERVICE_NAME} <<'EOFSERVICE'
[Unit]
Description=ldc-100-boot
# Se non connessa rete vedo schermata nera dopo slash 2 perchè rc-local attende - per ora così
After=rc-local.service splashscreen.service
# Per dhcpcd (opzionale):
#Wants=dhcpcd.service
#After=dhcpcd.service
# prendi controllo esclusivo di tty1 finché giri tu
Conflicts=getty@tty1.service
Before=getty@tty1.service

[Service]
Type=simple
User=root
Group=root

WorkingDirectory=${LDC_BASE_DIR}

# Attendi davvero che tty1 e ALSA esistano (evita race all'avvio)
ExecStartPre=/usr/bin/chmod +x ${APP_DIR}/boot.sh
ExecStartPre=/bin/sh -c 'until [ -e /dev/tty1 ]; do sleep 0.2; done'
ExecStartPre=/bin/sh -c 'until ls /dev/snd/* >/dev/null 2>&1; do sleep 0.2; done'
# Pulisci lo schermo e mostra l'IP (attende max 10s)
# Per ora indirizzo ip visualizzato con rc-local
#ExecStartPre=/bin/sh -c 'IP=\$(hostname -I | awk "{print \\$1}"); echo "IP: \$IP" > /dev/tty1'

# Libera tty1 da agetty per tutta la durata dell'app
# Evita lo stop "manuale" del getty nel tuo servizio (ce l'hai già dichiarativo) - Conflicts=getty@tty1.service e Before=getty@tty1.service
#ExecStartPre=/bin/sh -c 'systemctl stop getty@tty1.service || true'

# Lancia l'app con stdout line-buffered (vedi "Premi ESC..." subito)
ExecStart=/usr/bin/stdbuf -oL ${LDC_BASE_DIR}/boot.sh

# I/O "grezzo" su tty1 (nessun timestamp)
StandardInput=tty

StandardOutput=tty
StandardError=tty

TTYPath=/dev/tty1

TTYReset=yes
TTYVHangup=yes

# Uscite volontarie non causano restart
SuccessExitStatus=0 130 143
KillMode=process
Restart=on-failure
RestartSec=5

# Alla fine: ripulisci la tty e RIAVVIA il login su tty1
ExecStopPost=/bin/sh -c 'stty sane < /dev/tty1 || true; systemctl start getty@tty1.service || true'

[Install]
WantedBy=multi-user.target
EOFSERVICE

echo "✅ Service file creato in /etc/systemd/system/${SERVICE_NAME}"

# Step 10: Ricarica systemd
echo "🔄 Ricarica systemd..."
systemctl daemon-reload

# Step 11: Abilita e avvia servizio
echo "▶️  Avvio servizio..."
systemctl enable ${SERVICE_NAME}
systemctl start ${SERVICE_NAME}

# Verifica stato
sleep 2
systemctl status ${SERVICE_NAME} --no-pager

echo ""
echo "✅ Installazione completata!"
echo ""
echo "⚠️  RICORDA: "
echo "   - Verifica che ${DATA_DIR} esista e contenga i database"
echo ""
echo "Comandi utili:"
echo "  - Stato:    sudo systemctl status ${SERVICE_NAME}"
echo "  - Log:      sudo journalctl -u ${SERVICE_NAME} -f"
echo "  - Restart:  sudo systemctl restart ${SERVICE_NAME}"
echo "  - Stop:     sudo systemctl stop ${SERVICE_NAME}"
echo ""
