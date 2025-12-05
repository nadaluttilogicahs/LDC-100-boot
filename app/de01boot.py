#!/usr/bin/env python3
import subprocess
import sys
import os
import sqlite3
import json
import time
import fnmatch
import shutil
import keyboard
import zipfile
import glob
from pathlib import Path
from datetime import datetime
from tqdm import tqdm  # Assicurati di aver installato tqdm (pip install tqdm)
import syncdb

# import _sqlite
# import _def

# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# from ldc_common import _sqlite, _def
from ldc_common._paths import PATHS
from ldc_common import _sqlite

#import psutil

##############################################################
# Attivare ambiente virtuale (se usato)
# source .venv/bin/activate 
##############################################################

#================================================================================
SW_VERSION                         = 2  # != 0 

# 1         Alligned to Ver.3 of moistline boot (ml01boot)
# 2         Alligned to Ver.4 of moistline boot (ml01boot)
#           !! Baco: da USB key in realtà poi copiava file da /download_dir
#================================================================================

user = os.getlogin()
GUI_PROCCESS = ''
# exename = os.path.basename(__file__)

work_dir = PATHS.work_dir                    # ex. "/home/lg58/LDC-100"
work_dir_name = PATHS.work_dir_name          # ex. "LDC-100"
root_dir = PATHS.root_dir                   # ex. "/home/lg58"
rollback_dir = PATHS.rollback_dir            # ex. "/home/lg58/rollback"
download_dir = PATHS.download_dir
usb_dir = PATHS.usb_dir


swSrcDir = None
swToRunDict = {}
procNameDict = {} 
swRevCurr = []
dbSyncConfigs = {}


# Upg ctrl command (table: system_ctrl, ID: guiUpdtCtrl)
UCC_IDLE                            = 0
UCC_START_UPGRADE                   = 1      

# Upg status value (table: system_status, ID: guiUpdtSts)
USV_NO_INIT                         = 0 # don't use
# USV_NO_FOLDER                       = 1
USV_NO_JSON                         = 2
USV_IDLE                            = 3
USV_NO_NEW_VER                      = 4
USV_UPG_AVAILABLE                   = 5
# USV_FILE_READING_ERR                = 6
# USV_IN_PROGRESS                     = 7

# User command (for this application)
UCBOOT_RESET                        = 0      # reset by this application
# set by gui
UCBOOT_DO_BACKUP                    = 1


info_path_usb = None


#=============================================================================================================================
def doBackup ():

    # get id of moistline
    res1 = _sqlite.select_task_by_field(PATHS.db_set, 'sensInLine_sets_plant', 'idCtrl', 'value')
    idMoistline = res1[0]
    idMoistline = idMoistline['value']

    # così utilizzo 'import time' che è già utitizzata senza dover aggiungere 'import datetime'
    seconds = time.time()
    result = time.localtime(seconds)
    #date = str(result.tm_year) + str('%02d' % result.tm_mon) + str('%02d' % result.tm_mday) + str('%02d' % result.tm_hour) + str('%02d' % result.tm_min) + str('%02d' % result.tm_sec)ù
    # HHMMSS not necessary cause one backup per day
    date = str(result.tm_year) + str('%02d' % result.tm_mon) + str('%02d' % result.tm_mday)
    fileBackup ='ML' + str(idMoistline) + '_' + date + '_bkup' + '.db'

    if not os.path.exists(PATHS.DB_BACKUP_D):
        os.makedirs(PATHS.DB_BACKUP_D)
    # Eventualmente con funzioni  - High-level file operations (come fatto per funzione copySrcToDst)
    # Uso subprocess invece di os.system per evitare command injection
    subprocess.run(['sudo', 'cp', str(PATHS.db_set), str(PATHS.DB_BACKUP_D / fileBackup)], check=True)

    print(fileBackup, "file is a new backup")


# =============================================================================================================================
def copy_zip_file(source_file, destination_folder):
    """ Copies a single ZIP file to the destination folder, replacing it if it already exists. """
    
    # Ensure destination directory exists
    os.makedirs(destination_folder, exist_ok=True)
    
    # Define destination file path
    destination_file = os.path.join(destination_folder, os.path.basename(source_file))

    # If the file already exists, remove it
    if os.path.exists(destination_file):
        os.remove(destination_file)

    # Copy the file
    shutil.copy2(source_file, destination_file)
    print(f"📂 Copied: {source_file} -> {destination_file}")
    return destination_file


# =============================================================================================================================
def find_json_into_zip(path):
    # Find all ZIP files matching the pattern (e.g., "/home/pi/*.zip")
    zip_files = glob.glob(f'{path}/*.zip')

    if not zip_files:
        print("❌ No ZIP files found.")
        return None
    
    for zip_path in zip_files:
        zip_path = Path(zip_path)  # Convert to Path object
        info_json_found = False

        # !! SOLO PER DEBUG: /opt/... dovrebbe essere root oppure system user !!
        # Uso subprocess invece di os.system per evitare command injection
        subprocess.run(['sudo', 'chown', '-R', f'{user}:{user}', str(zip_path)], check=False)

        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                # 🔍 Cerca `info.json` dentro `LDC-100` (!! non deve essere zippata !!)
                for file in z.namelist():
                    if f"{work_dir_name}/" in file and file.endswith("info.json"):
                        info_json_found = True
                        print(f"📜 Found info.json inside {file} in {zip_path.name}")

                if not info_json_found:
                    print(f"❌ Skipping {zip_path.name} because info.json is missing inside LDC-100.")
                    continue

                # ✅ Terminare il ciclo dopo la prima estrazione valida
                return zip_path

        except zipfile.BadZipFile:
            print(f"❌ Error: {zip_path} is not a valid ZIP file or is corrupted.")
        except Exception as e:
            print(f"❌ Unexpected error with {zip_path}: {e}")

    # Return None solo se nessun file ZIP valido è stato trovato (fuori dal loop!)
    return None


# =============================================================================================================================
def process_zip(zip_path):

    if not zip_path:
        #print("❌ No ZIP files found.")
        return False

    zip_path = Path(zip_path)  # Convert to Path object
    parent_dir = zip_path.parent  # Get the parent directory
    roll_back_path = f'{parent_dir}/rollback'

    try:
        print(f"📦 Extracting {zip_path} to {parent_dir}")
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(parent_dir)

        # # Delete the original ZIP after processing
        # zip_path.unlink()
        # print(f"🗑️ Deleted ZIP file: {zip_path}")

        """Sposta lo zip in roll_back_path."""
        # Ensure rollback directory exists
        Path(roll_back_path).mkdir(parents=True, exist_ok=True)

        # Remove all previous ZIP files in roll_back_path
        for old_zip in Path(roll_back_path).glob("*.zip"):
            old_zip.unlink()
            print(f"🗑️ Deleted old ZIP file from rollback: {old_zip}")

        # Move ZIP file to roll_back_path instead of deleting it
        new_zip_path = Path(roll_back_path) / zip_path.name
        shutil.move(str(zip_path), str(new_zip_path))
        print(f"📂 Moved ZIP file to rollback directory: {new_zip_path}")


        """Sposta tutte le cartelle e decomprime eventuali ZIP al livello superiore."""
        # !! ATTENZIONE: non funziona se si è modificato il nome del file zip (ad es. in Windows) !!
        source_dir = Path(parent_dir / zip_path.stem)
        destination_dir = Path(parent_dir)

        for item in source_dir.iterdir():
            target_path = destination_dir / item.name

            if target_path.exists():
                print(f"🗑️ Removing existing folder {target_path} before moving the new one.")
                shutil.rmtree(target_path)  # Elimina la cartella esistente

            # 📂 Se è una cartella, spostala al livello superiore
            if item.is_dir():
                print(f"🚀 Moving folder {item} to {destination_dir}")
                shutil.move(str(item), str(target_path))

            # 📦 Se è un file ZIP, estrailo
            elif item.suffix == ".zip":
                print(f"📦 Unzipping {item} into {destination_dir}")
                with zipfile.ZipFile(item, 'r') as z:
                    z.extractall(destination_dir)
                item.unlink()  # Rimuove il file ZIP dopo l'estrazione

        # 🧹 Eliminare la cartella originale se è vuota
        if not any(source_dir.iterdir()):
            source_dir.rmdir()


    except zipfile.BadZipFile:
        print(f"❌ Error: {zip_path} is not a valid ZIP file or is corrupted.")
    except Exception as e:
        print(f"❌ Unexpected error with {zip_path}: {e}")


# #=============================================================================================================================
# def isFileZip (path):
#     zip_path = f"{path}.zip"  # ZIP file corresponding to the folder

#     # Check if the ZIP file exists
#     if os.path.exists(zip_path):
#         print(f"🔍 ZIP file detected: {zip_path}. Preparing for extraction...")

#         # If the folder already exists, delete it before extraction
#         if os.path.exists(path):
#             print(f"🗑️ Deleting existing folder: {path}")
#             shutil.rmtree(path)  # Delete the folder and all its contents

#         # Extract the ZIP file
#         print(f"📂 Extracting {zip_path} to {os.path.dirname(path)}...")
#         with zipfile.ZipFile(zip_path, 'r') as zip_ref:
#             zip_ref.extractall(os.path.dirname(path))

#         print("✅ Extraction completed.")

#         # Delete the ZIP file after extraction
#         print(f"🗑️ Deleting the ZIP file: {zip_path}")
#         os.remove(zip_path)
#     else:
#         print(f"📂 The ZIP file {zip_path} does not exist. No extraction needed.")


#=============================================================================================================================
def create_backupZip(foldToBackup, backup_dir):

    # Ensure rollback directory exists
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    # Remove all contents of the rollback directory
    for item in os.listdir(backup_dir):
        full_path = os.path.join(backup_dir, item)
        
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)  # Remove directories
        else:
            os.remove(full_path)  # Remove files

    # Create timestamp using time module
    #timestamp = time.strftime("%Y%m%d%H%M%S")  # Format: yyyymmddhhmmss
    #backup_name = os.path.basename(foldToBackup) + "_" + timestamp
    backup_name = os.path.basename(foldToBackup)
    backup_path = os.path.join(backup_dir, backup_name)

    # Make a backup of the destination folder before copying
    if os.path.exists(foldToBackup):
        # shutil.copytree(foldToBackup, backup_path)
        copySrcToDst(foldToBackup, backup_path) # così ho progress bar
        print("")
        # print(f"🔄 Backup created: {backup_path}")

        # # Compress the backup folder into a ZIP file
        # zip_path = backup_path + ".zip"
        # with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        #     for root, _, files in os.walk(backup_path):
        #         for file in files:
        #             file_path = os.path.join(root, file)
        #             arcname = os.path.relpath(file_path, backup_path)  # Maintain folder structure
        #             zipf.write(file_path, arcname)

        # Gestione zip con progress bar
        zip_path = backup_path + ".zip"

        file_list = []
        for root, _, files in os.walk(backup_path):
            for file in files:
                file_path = os.path.join(root, file)
                # arcname serve a mantenere la struttura della cartella all'interno dello zip
                arcname = os.path.relpath(file_path, backup_path)
                file_list.append((file_path, arcname))

        # Usa tqdm per visualizzare il progresso
        total_files = len(file_list)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path, arcname in tqdm(file_list, total=total_files, desc="Compressing files"):
                zipf.write(file_path, arcname)

        # Remove the original backup folder after zipping
        shutil.rmtree(backup_path)
        # !! privacy: non visualizzo percorso !!
        #print(f"📦 Backup compressed and saved as {zip_path}")
    else:
        print(f"⚠️ Folder to backup {foldToBackup} does not exist, skipping backup.")


#=============================================================================================================================
def copySrcToDst (sourFold, destFold, syncDb=False):

    # Conta il totale dei file da copiare
    total_files = sum(len(files) for _, _, files in os.walk(sourFold))

    # Crea la progress bar
    with tqdm(total=total_files, desc="Copying files", unit="file") as pbar:
        for src_dir, dirs, files in os.walk(sourFold):
            dst_dir = src_dir.replace(sourFold, destFold, 1)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
            for file_ in files:
                src_file = os.path.join(src_dir, file_)
                dst_file = os.path.join(dst_dir, file_)

                # !! EVENTUALMENTE UTILIZZARE FUNZIONI UTILITY _sqlite.py MA VERIFICARE SE VIENE CHIUSO DB CON with
                if syncDb:
                    # global dbSyncConfigs
                    # If file_ matches a DB in JSON config, perform sync
                    cfg = dbSyncConfigs.get(file_)
                    if cfg is not None:
                        exclude_tables = {tbl for tbl, act in cfg.items() if act.lower()=='exclude'}
                        fullcopy_tables = {tbl for tbl, act in cfg.items() if act.lower()=='fullcopy'}
                        colsfield_tables = {tbl for tbl, act in cfg.items() if act.lower()=='ncolfield'}
                        fullsync_tables = {tbl for tbl, act in cfg.items() if act.lower()=='fullsync'}
                        fullfield_tables = {tbl for tbl, act in cfg.items() if act.lower()=='fullfield'}
                        # print(f"[INFO] Syncing DB '{file_}' with config: exclude={exclude_tables}, fullcopy={fullcopy_tables}, ncolfield={colsfield_tables}, fullsync={fullsync_tables}, fullfield={fullfield_tables}")
                        with sqlite3.connect(src_file) as src_conn, sqlite3.connect(dst_file) as dst_conn:
                            # syncdb.sync_tables(src_conn, dst_conn, exclude_tables, fullcopy_tables)
                            syncdb.sync_tables(src_conn, dst_conn, exclude_tables, fullcopy_tables, colsfield_tables, fullsync_tables, fullfield_tables)
                        # print(f"[INFO] Completed DB sync: {src_file} -> {dst_file}")
                        continue

                # Standard file copy
                if os.path.exists(dst_file):
                    os.remove(dst_file)
                # shutil.copy(src_file, dst_dir)
                shutil.copy(src_file, dst_file)
                
                # # !! privacy: non visualizzo percorso !!
                # # print(f"📂 Copied: {src_file} -> {dst_file}")   
                # print(f"📂 Copied: {file_}") 
                
                # Aggiorna la progress bar per ogni file copiato
                pbar.update(1)
    


#=============================================================================================================================
def transfNewFile ():

    global swSrcDir

    if swSrcDir != None:
        print("--------------------------------------------------------------------------------------------------------------------------------")
        print(" ROLLBACK FILES")
        # create_backupZip(work_dir, rollback_dir)
        print("--------------------------------------------------------------------------------------------------------------------------------")
        print(" COPY FILES")
        copySrcToDst(swSrcDir, work_dir, syncDb=True)  # syncDb=True per sincronizzare i database se configurato


#=============================================================================================================================
def getLocalInfo ():
    global swRevCurr
    
    try:
        print(f'1 - Read info.json in {work_dir}/info.json')
        with open(f'{work_dir}/info.json') as f:
            data = json.load(f)

            #GET SOFTWARE VERSION FROM JSON FILE
            #  File json con chiave "swRev" (new)
            if "swRev" in data and isinstance(data["swRev"], dict):
                for k, v in data["swRev"].items():
                    swRevCurr.append((k, v))
            else:
                for k in ("globalSwRev", "bootSwRev", "guiSwRev", "coreSwRev"): # omessi socketSwRev e cloudSwRev
                    if k in data:
                        swRevCurr.append((k, data[k]))

            #GET OTHER INFO FROM JSON FILE

            # applications
            # # con percorso completo
            # dir = data.get('swToRun') 
            # global swToRunDict
            # swToRunDict = dir
            # con percorso parziale
            dir_ = data.get('swToRun', {})
            global swToRunDict
            swToRunDict = {f"{root_dir}" + path: value for path, value in dir_.items()}

            # process name
            dir = data.get('procToKill') 
            global procNameDict
            procNameDict = dir

            return 1
    except IOError:
        print("File not accessible")
        swRevCurr = []

        return 0


#=============================================================================================================================
# check if a upgrade is required
def isUpgrade ():
    usbName = ""
    usbErr = False

    swRevNew = []   # new software versions from usb or download folder
    
    # get local info
    getLocalInfo()

    # if necessary find the directory with .vfat because mount drive use to mount usb drive doens't return univoc path (on raspberry used "udev-media-automount")
    try:
        for a in os.listdir('/media'):
            if fnmatch.fnmatch(a, '*.vfat'):
                usbName = a
    except IOError:
        usbErr = True
        print("Usb drive not mount")

    if usbName == "":
        usbErr = True
        print("Usb drive not accessible")

    global swSrcDir
    global dbSyncConfigs

    # get usb driver versions
    try:
        if usbErr:
          raise IOError("")  
        global info_path_usb
        if info_path_usb == None:                       # !! se già verificato json e anche il resto nella chiavetta non ripeto perchè il file zip permane (lavoro in usbkey_dir) !!
            usbkey_dir = f'/media/{usbName}'
            zip_path = find_json_into_zip(usbkey_dir)
            if zip_path == None:
                raise IOError("")
            else:
                process_zip(copy_zip_file(zip_path, usb_dir))      # prima di con process_zip(), copio in locale perchè sulla chiavetta sta molto tempo

        info_path_usb = os.path.join(f'{usb_dir}/{work_dir_name}', "info.json")

        with open(info_path_usb) as f:
            print(f'2 - Read info.json in {info_path_usb}')     # dopo verifica apertura 
            data = json.load(f)

            #  File json con chiave "swRev" (new)
            if "swRev" in data and isinstance(data["swRev"], dict):
                for k, v in data["swRev"].items():
                    swRevNew.append((k, v))
            else:
                for k in ("globalSwRev", "bootSwRev", "guiSwRev", "coreSwRev"): # omessi socketSwRev e cloudSwRev
                    if k in data:
                        swRevNew.append((k, data[k]))

            # source folder
            swSrcDir = os.path.join(f'{usb_dir}', f"{work_dir_name}")
            
            # read DB-sync configurations
            dbSyncConfigs = data.get('dbSyncConfigs', {})
    except IOError:
        try:
            info_path_usb = None
            
            process_zip(find_json_into_zip(download_dir))

            info_path = os.path.join(f'{download_dir}/{work_dir_name}', "info.json")

            print(f'3 - Read info.json in {info_path}')
            with open(info_path) as f:
                data = json.load(f)

                #  File json con chiave "swRev" (new)
                if "swRev" in data and isinstance(data["swRev"], dict):
                    for k, v in data["swRev"].items():
                        swRevNew.append((k, v))
                else:
                    for k in ("globalSwRev", "bootSwRev", "guiSwRev", "coreSwRev"): # omessi socketSwRev e cloudSwRev
                        if k in data:
                            swRevNew.append((k, data[k]))

                # source folder
                swSrcDir = os.path.join(f'{download_dir}', f"{work_dir_name}")
                
                # read DB-sync configurations
                dbSyncConfigs = data.get('dbSyncConfigs', {})
        except IOError:
            print("❌ info.json file not accessible")
            swSrcDir = None
            return -1

    # Trasformo swRevCurr in dizionario per lookup O(1)
    dictCurr = dict(swRevCurr)

    for key_new, val_new in swRevNew:
        # Se la chiave non esiste in swRevCurr → ritorno 1
        if key_new not in dictCurr:
            return 1
        
        # Prendo il valore “corrente” associato
        val_curr = dictCurr[key_new]
        
        if val_new is None or not isinstance(val_new, (int, float)):
            # Salto questo elemento se val_new non è valido
            continue
        
        if val_curr is None or not isinstance(val_curr, (int, float)):
            # Se curr non esiste o non valido considero update
            return 1

        if val_new > val_curr:
            # update
            return 1

    return 0


#=============================================================================================================================
# Kill running process
def killProcess ():

    killed = False
    
    # for proc in psutil.process_iter():
    #     global procNameList
    #     for x in procNameList:
    #         if proc.name() == x:
    #             print(x)
    #             proc.kill()
    #             killed = True

    # global procNameList
    global procNameDict
    # for x in procNameList:
    for x in procNameDict:
        # Uso subprocess invece di os.system per evitare command injection
        subprocess.run(['sudo', 'killall', x], check=False)

    os.system('cls||clear')
    print("================================================================================================================================")
    print(" KILL PROCESS")
    print("--------------------------------------------------------------------------------------------------------------------------------")
    print(" Check if all applications have been released...")
    while isAllProcessStop() == True:
        print("- Waiting for all applications to be released...")
    
    time.sleep(1)
    print("--------------------------------------------------------------------------------------------------------------------------------")
    print(" Vacuum database...") # to merge temperary database (ex. -wall, -shm)
    _sqlite.update_task_by_query(PATHS.db_set, "VACUUM")
    print(f"- Vacuum {PATHS.db_set}")
    _sqlite.update_task_by_query(PATHS.db_rtd, "VACUUM")
    print(f"- Vacuum {PATHS.db_rtd}")
    _sqlite.update_task_by_query(PATHS.db_lan, "VACUUM")
    print(f"- Vacuum {PATHS.db_lan}")
    _sqlite.update_task_by_query(PATHS.DB_PRG_D, "VACUUM")
    print(f"- Vacuum {PATHS.DB_PRG_D}")
    time.sleep(1)
        
    killed = True
    return killed


#=============================================================================================================================
# launch proccess

def launchProccess (swPath, proc):
    
    swDelay = swToRunDict.get(swPath)
    time.sleep(swDelay)
    try:
        if isProcessRunning(proc, False) == False: 
            #subprocess.Popen(["sudo", swToRunList[x]])
            
            subprocess.Popen(["sudo", swPath])
            # subprocess.Popen(["sudo", "-E", swPath]) # per lanciare script python con ambientui diversi pi/boot visto che uso sudo

            #subprocess.call(["sudo", x])
            #subprocess.run(["sudo", x])
            #os.system("sudo " + x + "&")
            #os.spawnl(os.P_NOWAIT, "sudo" + x, x, "--startup")
            #os.popen("sudo " + x + "&")
        return 1
    except:
        return 0

def launchAllProccess ():
    idxProc = 0

    if getLocalInfo():
        #for x in range (len(swToRunList)):
        for x in swToRunDict:
            if launchProccess(x, list(procNameDict.keys())[idxProc]) == 0:
                print("- Error to load application ---------------------------------------------------------------------")
            idxProc = idxProc + 1 
        return 1
    else: # try to load default
        return 0


#=============================================================================================================================
# Check if process's running

def isProcessRunning (proc, watchdogCtrl):
    ret = True

    # se non abilitato controllo watchdog
    watchdog = procNameDict.get(proc)
    # if watchdog == 0:
    #     if toKiwatchdogll:
    #         return False
    #     else:
    #         return True    
    if watchdog == 0 and watchdogCtrl == True:
        return True 

    #cmd = 'pidof ' + proc         non intercetta se l'applicazione è tipo in sleep (come il core)
    cmd = 'pidof -z ' + proc
    #cmd = 'pgrep -f ' + proc      eventualmente provare questo 
    try:
        # outputStr = os.popen(cmd).read() 
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = result.stdout.decode()  # Get standard output
        error_output = result.stderr.decode()  # Get error output
        if output == "" and error_output == "": 
            ret = False
    except subprocess.CalledProcessError as e:
        # !! NO print perchè quando chiamata da launchProccess è normale che non trovi il processo !!
        #print(f"Command failed with error code {e.returncode}")
        #print(f"Error output: {e.stderr.decode()}")     # se opzione comando non gestita da raspbian si arriva qui
        if e.stderr.decode() == "":
            ret = False                                 # !! se applicazione non in run in verità si arriva qui !!
    except:
        print("Error system command")

    return ret


#=============================================================================================================================
# Check if all process're running and relaunch the application that not running

def isAllProcessRunning ():
    idxProc = 0
    ret = True

    # global procNameList
    global procNameDict
    # for proc in procNameList:
    for proc in procNameDict:
        try:
            if isProcessRunning(proc, True) == False: 
                ret = False
                
                print("- Process " + proc + " is not running: try to lauch again ------------------------------------------")
                if proc == GUI_PROCCESS:
                    print("- " + GUI_PROCCESS + " process need to relauch all application ----------------------------------" )
                    killProcess()
                    time.sleep(2)
                    launchAllProccess()
                else:
                    # launchProccess(idxProc)
                    launchProccess(list(swToRunDict.keys())[idxProc], proc)
        except:
            print("Error")
        
        idxProc = idxProc + 1 


#=============================================================================================================================
# Check if all process're shut down
def isAllProcessStop ():
    ret = True

    # global procNameList
    global procNameDict
    # for proc in procNameList:
    for proc in procNameDict:
        try:
            if isProcessRunning(proc, False) == True:
                ret = False
        except:
            print("Error")

    return ret


#=============================================================================================================================
def keyPressed (init):
    keyPress = False

    try:
        if keyboard.is_pressed('Esc'):  # if key 'ESC' is pressed 
            if init == 0:               # no application is running
                keyPress = True                 
            else:
                #Evito di gestire file in continuazione #getLocalInfo()          # refresh kill application list
                keyPress = True
    except:
        return keyPress
    
    return keyPress


#=============================================================================================================================
#=============================================================================================================================
if __name__ == '__main__': 

    update = False
    backup = False

    time.sleep(2)

    print("")
    print("================================================================================================================================")
    print("LDC-100 BOOT SOFTWARE by LOGICA H&S Srl. Version: ", SW_VERSION)
    print("================================================================================================================================")
    # !! Meglio mantenere riservata questa informazione !!
    #print('Press ESC key to stop all applications')
    time.sleep(2)

    try:
        if keyPressed(0) == True:
            #sys.exit()
            raise KeyboardInterrupt

        # refresh privilegi/permessi
        # Uso subprocess invece di os.system per evitare command injection
        subprocess.run(['sudo', 'chown', '-R', f'{user}:{user}', str(work_dir)], check=False)
        subprocess.run(['sudo', 'chmod', '-R', '+rwx', str(work_dir)], check=False)
        # try:
        #     subprocess.run(['sudo', 'chown', '-R', 'lg58:lg58', f'{work_dir}'], check=True)
        #     subprocess.run(['sudo', 'chmod', '-R', 'rwx', f'{work_dir}'], check=True)
        #     print("✅ Permessi aggiornati con successo!")
        # except subprocess.CalledProcessError as e:
        #     print(f"❌ Errore durante l'aggiornamento dei permessi: {e}")

        time.sleep(1)

        # scrivi versione applicazione così feedback per gui
        _sqlite.update_task_by_field(PATHS.db_set, 'system_status', 'upgSwVer', 'value', SW_VERSION)
        # !! per sicurezza resetto aggiornamento
        _sqlite.update_task_by_field(PATHS.db_set, 'system_ctrl', 'guiUpdtCtrl', 'value', UCC_IDLE)
        
        time.sleep(1)

        if launchAllProccess() == 0:
            #exit(1)        #debug
            sys.exit()     #release

        time.sleep(5)      # attendo che applicativi si inizializzino

        while True:
            print("Update software in idle ...")
            # verifica se sono nella schermata update (così limito lettura su db)
            
            # # 20241016: non più utilizzato updtEnb ma screen/screenPc
            # #res1 = _sqlite.select_task_by_field(PATHS.db_set, 'system_status', 'updtEnb', 'value')
            # #res = res1[0]
            
            # res1 = _sqlite.select_task_by_query(PATHS.db_set, "SELECT value FROM gui_status WHERE ID IN ('screen', 'screenPc') ORDER BY ID")
            # screen = res1[0]
            # screen = screen['value']
            # screenPc = res1[1]
            # screenPc = screenPc['value']

            # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! per ora forzo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            screen = screenPc ='info_Screen'

            #if res['value'] == 1:
            if screen == 'info_Screen' or screenPc == 'info_Screen':

                res = isUpgrade()
                if res == 1:
                    print("- Found upgrade ---------------------------------------------------------------------------------")
                    res1 = _sqlite.select_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value')
                    res = res1[0]
                    if res['value'] != USV_UPG_AVAILABLE:
                        _sqlite.update_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value', USV_UPG_AVAILABLE)


                    res1 = _sqlite.select_task_by_field(PATHS.db_set, 'system_ctrl', 'guiUpdtCtrl', 'value')
                    res = res1[0]
                    if res['value'] == UCC_START_UPGRADE:

                        # reset
                        _sqlite.update_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value', USV_IDLE)
                        _sqlite.update_task_by_field(PATHS.db_set, 'system_ctrl', 'guiUpdtCtrl', 'value', UCC_IDLE)

                        # start update
                        update = True
                        break
                elif res == 0:
                    print("Software version is already updated -------------------------------------------------------------")
                    res1 = _sqlite.select_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value')
                    res = res1[0]
                    if res['value'] != USV_NO_NEW_VER:
                        _sqlite.update_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value', USV_NO_NEW_VER)
                else:
                    print("Source directory not found")
                    res1 = _sqlite.select_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value')
                    res = res1[0]
                    if res['value'] != USV_NO_JSON:
                        _sqlite.update_task_by_field(PATHS.db_set, 'system_status', 'guiUpdtSts', 'value', USV_NO_JSON)

            elif screen == 'backup_Screen' or screenPc == 'backup_Screen':
                res1 = _sqlite.select_task_by_field(PATHS.db_set, 'system_ctrl', 'usrCmdBoot', 'value')
                usrCmd = res1[0]
                usrCmd = usrCmd['value']
                if usrCmd == UCBOOT_DO_BACKUP:
                    _sqlite.update_task_by_field(PATHS.db_set, 'system_ctrl', 'usrCmdBoot', 'value', UCBOOT_RESET)
                    backup = True
                    break

            
            
            # print("- List of folder/file ------------------------------------------------------------------------------------")
            # rootdir = '/media'
            # for file in os.listdir(rootdir):
            #     d = os.path.join(rootdir, file)
            #     if os.path.isdir(d):
            #         print(d)

            if keyPressed(1) == True:
                #sys.exit()
                raise KeyboardInterrupt
            else:
                isAllProcessRunning()
            
            time.sleep(10)

        if update:
            os.system('cls||clear')
            killProcess() 
            os.system('cls||clear')
            print("================================================================================================================================")
            print(" START UPGRADE")
            transfNewFile()
            time.sleep(2)
            print("================================================================================================================================")
            print(" UPGRADE DONE")
            # refresh privilegi/permessi (perchè se scaricati da aws s3 non viene settata la flag exe)
            # Uso subprocess invece di os.system per evitare command injection
            subprocess.run(['sudo', 'chown', '-R', f'{user}:{user}', str(work_dir)], check=False)
            subprocess.run(['sudo', 'chmod', '-R', '+rwx', str(work_dir)], check=False)
            time.sleep(2)
            print("================================================================================================================================")
            print(" REBOOT SYSTEM")
            time.sleep(2)
            os.system('sudo reboot')

        if backup:
            os.system('cls||clear')
            killProcess()
            print("================================================================================================================================")
            print(" START BACKUP")
            doBackup()
            time.sleep(2)
            print("================================================================================================================================")
            print(" REBOOT SYSTEM")
            time.sleep(2)
            os.system('sudo reboot')

    except KeyboardInterrupt:
        os.system('cls||clear')
        killProcess()
        print('ESC key pressed: stopped all applications')
        sys.exit()