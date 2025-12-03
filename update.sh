#!/bin/bash

###############################################################################
# LDC-100 Boot Utility - Update Script
# 
# This script updates the boot utility:
# - Stops the service
# - Pulls latest changes from git
# - Updates Python dependencies if needed
# - Restarts the service
###############################################################################

# Configurazione
APP_NAME="boot"
APP_DIR="/home/lg58/LDC-100/${APP_NAME}"
SERVICE_USER="lg58"
SERVICE_NAME="ldc-100-boot.service"

echo "🔄 Aggiornamento ${APP_NAME}..."

# Verifica se è root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Esegui con sudo: sudo bash update.sh"
    exit 1
fi

# Verifica che la directory esista
if [ ! -d "${APP_DIR}" ]; then
    echo "❌ Directory ${APP_DIR} non trovata. Esegui prima install.sh"
    exit 1
fi

# Verifica che sia un repository git
if [ ! -d "${APP_DIR}/.git" ]; then
    echo "❌ ${APP_DIR} non è un repository git. Esegui prima install.sh"
    exit 1
fi

# Step 1: Ferma il servizio
echo "⏸️  Arresto servizio..."
systemctl stop ${SERVICE_NAME}
echo "✅ Servizio arrestato"

# Step 2: Backup requirements.txt per confronto
BACKUP_REQ="${APP_DIR}/requirements.txt.bak"
if [ -f "${APP_DIR}/requirements.txt" ]; then
    cp ${APP_DIR}/requirements.txt ${BACKUP_REQ}
fi

# Step 3: Aggiorna repository
echo "📥 Aggiornamento repository da git..."
cd ${APP_DIR}
sudo -u ${SERVICE_USER} git pull

if [ $? -ne 0 ]; then
    echo "❌ Errore durante git pull"
    systemctl start ${SERVICE_NAME}
    exit 1
fi

echo "✅ Repository aggiornato"

# Step 4: Verifica se requirements è cambiato
REQUIREMENTS_CHANGED=false

if [ -f "${APP_DIR}/requirements.txt" ] && [ -f "${BACKUP_REQ}" ]; then
    if ! cmp -s "${APP_DIR}/requirements.txt" "${BACKUP_REQ}"; then
        REQUIREMENTS_CHANGED=true
    fi
elif [ -f "${APP_DIR}/requirements.txt" ] && [ ! -f "${BACKUP_REQ}" ]; then
    REQUIREMENTS_CHANGED=true
fi

# Step 5: Aggiorna dipendenze Python se necessario
if [ "$REQUIREMENTS_CHANGED" = true ]; then
    echo "📚 Requirements modificato, aggiornamento dipendenze Python..."
    sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/pip install --upgrade pip
    sudo -u ${SERVICE_USER} ${APP_DIR}/venv/bin/pip install -r ${APP_DIR}/requirements.txt
    echo "✅ Dipendenze Python aggiornate"
else
    echo "ℹ️  Nessun cambiamento in requirements.txt"
fi

# Rimuovi backup
rm -f ${BACKUP_REQ}

# Step 6: Assicurati che boot.sh sia eseguibile
chmod +x ${APP_DIR}/boot.sh

# Step 7: Riavvia il servizio
echo "▶️  Riavvio servizio..."
systemctl daemon-reload
systemctl start ${SERVICE_NAME}

# Verifica stato
sleep 2
systemctl status ${SERVICE_NAME} --no-pager

echo ""
echo "✅ Aggiornamento completato!"
echo ""
echo "Comandi utili:"
echo "  - Stato:    sudo systemctl status ${SERVICE_NAME}"
echo "  - Log:      sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
