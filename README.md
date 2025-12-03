# LDC-100 Boot Utility

Sistema di boot e aggiornamento per dispositivi LDC-100 su Raspberry Pi.

## Descrizione

Utility di avvio che gestisce:
- Lancio automatico delle applicazioni LDC-100 (GUI, Core, Socket, Cloud)
- Sistema di aggiornamento software da USB o repository
- Backup database
- Sincronizzazione database remoti
- Gestione processi e monitoraggio

## Requisiti

- Raspberry Pi con Raspberry Pi OS (Debian-based)
- Python 3.7+
- Accesso root (sudo)
- Connessione internet per installazione dipendenze

## Installazione

### 1. Clona il repository

```bash
git clone https://github.com/nadaluttilogicahs/LDC-100-boot.git
cd LDC-100-boot
```

### 2. Esegui lo script di installazione

```bash
sudo bash install.sh
```

Lo script eseguirà automaticamente:
- Installazione dipendenze di sistema (Python, numpy libs, git)
- Creazione virtual environment Python
- Installazione dipendenze Python (requirements.txt)
- Configurazione servizio systemd
- Avvio automatico del servizio

### 3. Verifica installazione

```bash
sudo systemctl status ldc-100-boot
```

## Aggiornamento

Per aggiornare all'ultima versione:

```bash
cd /home/lg58/LDC-100/boot
sudo bash update.sh
```

Lo script di aggiornamento:
- Ferma il servizio
- Aggiorna il codice da git (`git pull`)
- Aggiorna le dipendenze Python se necessario
- Riavvia il servizio

## Struttura Directory

```
/home/lg58/LDC-100/
├── boot.sh                 # Launcher script (generato da install.sh)
├── boot/                   # Repository boot utility
│   └── app/                # Script applicativi
│       ├── de01boot.py     # Script principale
│       ├── syncdb.py       # Sincronizzazione database
│       ├── venv/           # Virtual environment Python
│       └── requirements.txt # Dipendenze Python
├── data/                   # Directory dati e database
└── ...                     # Altre utility (gui, core, socket, cloud)
```

## Configurazione

### Servizio Systemd

Il servizio è configurato per:
- Avviarsi automaticamente all'boot
- Controllare tty1 per output console
- Riavviarsi in caso di errore
- File: `/etc/systemd/system/ldc-100-boot.service`

### Variabili d'Ambiente

Modificare in `install.sh` prima dell'installazione:
- `APP_DIR`: Directory installazione (default: `/home/lg58/LDC-100/boot`)
- `SERVICE_USER`: Utente di sistema (default: `lg58`)
- `DATA_DIR`: Directory dati (default: `/home/lg58/LDC-100/data`)

## Comandi Utili

```bash
# Stato servizio
sudo systemctl status ldc-100-boot

# Riavvia servizio
sudo systemctl restart ldc-100-boot

# Ferma servizio
sudo systemctl stop ldc-100-boot

# Visualizza log in tempo reale
sudo journalctl -u ldc-100-boot -f

# Visualizza log completo
sudo journalctl -u ldc-100-boot --no-pager

# Disabilita avvio automatico
sudo systemctl disable ldc-100-boot

# Riabilita avvio automatico
sudo systemctl enable ldc-100-boot
```

## Funzionalità Principali

### Sistema di Aggiornamento

L'utility supporta aggiornamenti software da:
- File ZIP su chiavetta USB
- Repository git remoti
- Directory di download locale

### Sincronizzazione Database

Lo script `syncdb.py` permette di sincronizzare database SQLite con diverse modalità:
- `exclude`: Esclude tabella dalla sincronizzazione
- `fullcopy`: Copia completa della tabella
- `ncolfield`: Sincronizza schema + valori nuove colonne
- `fullsync`: Sincronizza righe con ID
- `fullfield`: Sincronizza righe complete con tutti i valori

Configurazione tramite file JSON con `dbSyncConfigs`.

### Backup Database

Funzionalità di backup automatico del database configurabile tramite interfaccia GUI.

## Dipendenze

### Sistema
- python3, python3-pip, python3-venv
- git
- libatlas-base-dev, libopenblas-dev (per numpy)

### Python (requirements.txt)
- tqdm: Progress bar operazioni file
- keyboard: Gestione input tastiera
- ldc-common: Libreria comune LDC-100

## Sviluppo

### Modifiche Locali

Per testare modifiche senza sovrascrivere l'installazione:

```bash
# Backup installazione corrente
mv /home/lg58/LDC-100/boot /home/lg58/LDC-100/boot_backup

# Testa modifiche
# ...

# Ripristina se necessario
rm -rf /home/lg58/LDC-100/boot
mv /home/lg58/LDC-100/boot_backup /home/lg58/LDC-100/boot
```

### Test Installazione

Per testare l'installazione su path diverso, modifica temporaneamente in `install.sh`:

```bash
APP_DIR="/home/lg58/LDC-100/boot-test"
```

## Troubleshooting

### Il servizio non si avvia

```bash
# Verifica errori nei log
sudo journalctl -u ldc-100-boot -n 50

# Verifica che la directory dati esista
ls -la /home/lg58/LDC-100/data

# Verifica permessi
sudo chown -R lg58:lg58 /home/lg58/LDC-100/boot
sudo chmod -R 750 /home/lg58/LDC-100/boot
```

### Problemi con dipendenze Python

```bash
# Reinstalla requirements
cd /home/lg58/LDC-100/boot
sudo -u lg58 venv/bin/pip install -r requirements.txt --force-reinstall
```

### Git pull fallisce

```bash
# Verifica stato repository
cd /home/lg58/LDC-100/boot
git status

# Reset modifiche locali (ATTENZIONE: perde modifiche non committate)
sudo -u lg58 git reset --hard origin/main
sudo -u lg58 git pull
```

## Licenza

Proprietario: Logica H&S Srl

## Contatti

Per supporto tecnico contattare Logica H&S Srl.
