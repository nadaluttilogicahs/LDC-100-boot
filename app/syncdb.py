import json
import os
import sqlite3
import argparse

"""
I database possono venir sincronizzati piuttosto che copiati, per non perdere alcune informazioni, riportando il nome del database sotto l'oggetto json dbSyncConfigs nel file json. In questo modo tutte le tabelle varranno sincronizzare, aggiungendo ed eliminando le colonne, con il db sorgente e quindi con gli eventuali DEFAULT. E' possibile inoltre gestire delle eccezioni per le tabelle riportando il nome della stessa come key e il value uguale a:

fullcopy: se si desidera copiare interamente la tabella

exclude: escludere dalla copia una particolare tabella

ncolfield: vengono inoltre copiati i valori nelle nuove colonne

fullsync: vengono allineate (aggiunte, eliminate) anche le righe con il campo ID e i rimanenti campi con il DEFAULT se previsto nello schema. ATTENZIONE: se un campo diverso da ID è impostato NOT NULL occorre ci sia anche il DEFAULT 

fullfield: fullsync + copiati i valori nelle nuove righe piuttosto che impostare il DEFAULT  (questa modalità utile se non previsto il default)

Su tutte le tabelle con il nome *sets* viene eseguito sempre un fullfield + sovrascritti tutti i campi, anche nelle righe non nuove, tranne per la colonna "value" (questo serve per allineare eventuali min, Max, ecc))

⚠️In nessun caso il sincronismo dei database riporta eventuali aggiunto allo schema per colonne già esistenti (ad esempio l'aggiunta di un DEFAULT )
"""                                                                                                         
"""
Sincronizza due DB SQLite con opzioni:
    - exclude_tables: tabelle da ignorare
    - fullcopy_tables: tabelle da full-copy (schema + dati)
    - colsfield_tables: schema + update valori colonne
    - fullsync_tables: insert righe nuove con solo ID (colonne default)
    - fullfield_tables: insert righe nuove con ID + tutti i valori
    - default: schema-only (aggiunge/rimuove colonne)
"""

def get_tables(conn):
    """Return a dict of table_name -> CREATE TABLE SQL."""
    #print("[INFO] Retrieving table list from database...")
    cursor = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    )
    tables = {row[0]: row[1] for row in cursor.fetchall()}
    #print(f"[INFO] Found tables: {list(tables.keys())}")
    return tables


def get_columns(conn, table):
    """Return a dict of column_name -> pragma info row."""
    #print(f"[INFO] Retrieving columns for table '{table}'...")
    cursor = conn.execute(f"PRAGMA table_info('{table}');")
    cols = {row[1]: row for row in cursor.fetchall()}
    #print(f"[INFO] Columns in '{table}': {list(cols.keys())}")
    return cols


def drop_extraneous_columns(conn, tbl, keep_cols):
    """
    Drop columns not in keep_cols by rebuilding the table.
    """
    #print(f"[INFO] Dropping extraneous columns for table '{tbl}'")
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;", (tbl,)
    )
    create_sql = cursor.fetchone()[0]
    tmp_tbl = f"{tbl}_backup"
    #print(f"[DEBUG] Renaming '{tbl}' to '{tmp_tbl}'")
    conn.execute(f"ALTER TABLE '{tbl}' RENAME TO '{tmp_tbl}';")

    cols_def = create_sql[create_sql.find('(')+1:create_sql.rfind(')')]
    new_cols_def = []
    for col_def in cols_def.split(','):
        col_name = col_def.strip().split()[0].strip('"\'"')
        if col_name in keep_cols:
            new_cols_def.append(col_def)
    #print(f"[DEBUG] Keeping columns: {keep_cols}")
    cols_defs_sql = ','.join(new_cols_def)

    #print(f"[DEBUG] Creating new table '{tbl}' with kept columns")
    conn.execute(f"CREATE TABLE '{tbl}' ({cols_defs_sql});")

    cols_list = ','.join([f"'{c}'" for c in keep_cols])
    #print(f"[DEBUG] Copying data for columns: {keep_cols}")
    conn.execute(
        f"INSERT OR REPLACE INTO '{tbl}' ({cols_list}) SELECT {cols_list} FROM '{tmp_tbl}';"
    )
    #print(f"[DEBUG] Dropping backup table '{tmp_tbl}'")
    conn.execute(f"DROP TABLE '{tmp_tbl}';")
    conn.commit()
    #print(f"[INFO] Dropped extraneous columns and rebuilt '{tbl}' successfully")


# Helper: applica solo modifiche di schema (aggiunge/rimuove colonne)
# Ora restituisce la lista delle colonne appena aggiunte
# ⚠️In nessun caso il sincronismo dei database riporta eventuali aggiunto allo schema per colonne già esistenti 
# (ad esempio l'aggiunta di un DEFAULT), perchè occorre ricostruire la tabella
def apply_schema_changes(source_conn, dest_conn, tbl):
    src_cols = get_columns(source_conn, tbl)
    dst_cols = get_columns(dest_conn, tbl)
    new_cols = []
    # Aggiungi nuove colonne mancanti
    for col, info in src_cols.items():
        if col not in dst_cols:
            col_type, default = info[2], info[4]
            sql = f"ALTER TABLE '{tbl}' ADD COLUMN '{col}' {col_type}"
            if default is not None:
                sql += f" DEFAULT {default}"
            dest_conn.execute(sql)
            new_cols.append(col)
    dest_conn.commit()
    # Rimuovi colonne extra ricostruendo la tabella
    extra = [c for c in dst_cols if c not in src_cols]
    if extra:
        drop_extraneous_columns(dest_conn, tbl, list(src_cols.keys()))
    return new_cols


# Helper: popola i valori solo per le colonne appena create
def apply_data_new_columns(source_conn, dest_conn, tbl, cols):
    if not cols:
        return
    # Prendi tutti gli ID esistenti
    ids = [r[0] for r in source_conn.execute(f"SELECT ID FROM '{tbl}';")]
    if not ids:
        return
    qm = ','.join(['?' for _ in ids])
    # Copia solo i valori delle colonne specificate
    for col in cols:
        rows = source_conn.execute(
            f"SELECT ID, {col} FROM '{tbl}' WHERE ID IN ({qm});", tuple(ids)
        ).fetchall()
        data = [(v, i) for i, v in rows]
        dest_conn.executemany(
            f"UPDATE '{tbl}' SET '{col}'=? WHERE ID=?;", data
        )
    dest_conn.commit()
    
    
# # Helper: allinea valori di tutte le colonne basandosi su ID
# def apply_data_col_changes(source_conn, dest_conn, tbl):
#     src_cols = get_columns(source_conn, tbl)
#     if 'ID' not in src_cols:
#         return
#     ids = [r[0] for r in source_conn.execute(f"SELECT ID FROM '{tbl}';")]
#     if not ids:
#         return
#     qm = ','.join(['?' for _ in ids])
#     for col in src_cols.keys():
#         rows = source_conn.execute(
#             f"SELECT ID, {col} FROM '{tbl}' WHERE ID IN ({qm});", tuple(ids)
#         ).fetchall()
#         data = [(v, i) for i, v in rows]
#         dest_conn.executemany(
#             f"UPDATE '{tbl}' SET '{col}'=? WHERE ID=?;", data
#         )
#     dest_conn.commit()


def sync_tables(source_conn, dest_conn,
                exclude_tables=None,
                fullcopy_tables=None,
                ncolfield_tables=None,
                fullsync_tables=None,
                fullfield_tables=None):
    
    # Prepara i set per membership efficiente
    exclude_tables   = set(exclude_tables   or [])
    fullcopy_tables  = set(fullcopy_tables  or [])
    ncolfield_tables   = set(ncolfield_tables   or [])
    fullsync_tables  = set(fullsync_tables  or [])
    fullfield_tables = set(fullfield_tables or [])

    source_tables = get_tables(source_conn)
    dest_tables   = get_tables(dest_conn)

    # STEP 1: crea o full-copy tabelle mancanti
    for tbl, create_sql in source_tables.items():
        if tbl in exclude_tables:
            continue
        if tbl not in dest_tables:
            dest_conn.execute(create_sql)
            dest_conn.commit()
            rows = source_conn.execute(f"SELECT * FROM '{tbl}';").fetchall()
            if rows:
                ph = ','.join(['?' for _ in rows[0]])
                dest_conn.executemany(
                    f"INSERT INTO '{tbl}' VALUES ({ph});", rows
                )
                dest_conn.commit()
            continue
        if tbl in fullcopy_tables:
            dest_conn.execute(f"DROP TABLE '{tbl}';")
            dest_conn.execute(create_sql)
            dest_conn.commit()
            rows = source_conn.execute(f"SELECT * FROM '{tbl}';").fetchall()
            if rows:
                ph = ','.join(['?' for _ in rows[0]])
                dest_conn.executemany(
                    f"INSERT INTO '{tbl}' VALUES ({ph});", rows
                )
                dest_conn.commit()
            continue

    # Aggiorna schema-only e dati secondari
    for tbl in source_tables:
        if tbl in exclude_tables or tbl not in get_tables(dest_conn) or tbl in fullcopy_tables:
            continue

        # schema-only di default
        new_cols = apply_schema_changes(source_conn, dest_conn, tbl)

        # schema+data colonne
        if tbl in ncolfield_tables:
            apply_data_new_columns(source_conn, dest_conn, tbl, new_cols)
            continue

        # ⚠️ salta gestione righe se non c'è la colonna ID
        dst_cols = get_columns(dest_conn, tbl)
        if 'ID' not in dst_cols:
            continue
        
        # prepara ins/del righe
        src_ids = {r[0] for r in source_conn.execute(f"SELECT ID FROM '{tbl}';")}
        dst_ids = {r[0] for r in dest_conn.execute(f"SELECT ID FROM '{tbl}';")}
        to_ins = src_ids - dst_ids
        to_del = dst_ids - src_ids

        # fullsync o fullfield o presenza 'sets'
        if tbl in fullsync_tables or tbl in fullfield_tables or 'sets' in tbl:
            # fullsync: solo ID nuove, default per le altre colonne
            if tbl in fullsync_tables:
                if to_ins:
                    # inserisci solo ID, le altre colonne prendono il DEFAULT
                    dest_conn.executemany(
                        f"INSERT INTO '{tbl}' (ID) VALUES (?);",
                        [(i,) for i in to_ins]
                    )
            else:
                # fullfield o sets: righe nuove
                if to_ins:
                    cols = list(get_columns(source_conn, tbl).keys())
                    ph = ','.join(['?' for _ in cols])
                    qm_all = ','.join(['?' for _ in to_ins])
                    rows_all = source_conn.execute(
                        f"SELECT {','.join(cols)} FROM '{tbl}' WHERE ID IN ({qm_all});", tuple(to_ins)
                    ).fetchall()
                    dest_conn.executemany(
                        f"INSERT INTO '{tbl}' ({','.join(cols)}) VALUES ({ph});", rows_all
                    )
            # elimina righe mancanti
            if to_del:
                qm_del = ','.join(['?' for _ in to_del])
                dest_conn.execute(
                    f"DELETE FROM '{tbl}' WHERE ID IN ({qm_del});", tuple(to_del)
                )
            # special-case 'sets': full-field sync tranne ID e value
            if 'sets' in tbl:
                # !! dst_ids riaggiornato perchè potrebbero essere state aggiunte righe
                dst_ids = {r[0] for r in dest_conn.execute(f"SELECT ID FROM '{tbl}';")}
                common = src_ids & dst_ids
                if common:
                    qm_comm = ','.join(['?' for _ in common])
                    cols_except = [c for c in get_columns(source_conn, tbl) if c not in ('ID','value')]
                    for col in cols_except:
                        vals = source_conn.execute(
                            f"SELECT ID, {col} FROM '{tbl}' WHERE ID IN ({qm_comm});", tuple(common)
                        ).fetchall()
                        dest_conn.executemany(
                            f"UPDATE '{tbl}' SET {col}=? WHERE ID=?;", [(v,i) for i,v in vals]
                        )
            dest_conn.commit()
            
            
            
            
            
# def sync_tables(source_conn, dest_conn, exclude_tables, fullcopy_tables):
#     #print("[INFO] Starting database synchronization...")
#     source_tables = get_tables(source_conn)
#     dest_tables = get_tables(dest_conn)

#     # Step 1: Create missing or full-copy tables
#     for tbl, create_sql in source_tables.items():
#         if tbl not in dest_tables:
#             #print(f"[ACTION] Creating missing table '{tbl}'")
#             dest_conn.execute(create_sql)
#             dest_conn.commit()
#             rows = source_conn.execute(f"SELECT * FROM '{tbl}';").fetchall()
#             if rows:
#                 ph = ",".join(["?" for _ in rows[0]])
#                 #print(f"[ACTION] Inserting {len(rows)} rows into new table '{tbl}'")
#                 dest_conn.executemany(f"INSERT INTO '{tbl}' VALUES ({ph});", rows)
#                 dest_conn.commit()
#         elif tbl in fullcopy_tables:
#             #print(f"[ACTION] Full-copying table '{tbl}'")
#             dest_conn.execute(f"DROP TABLE '{tbl}';")
#             dest_conn.execute(create_sql)
#             dest_conn.commit()
#             rows = source_conn.execute(f"SELECT * FROM '{tbl}';").fetchall()
#             if rows:
#                 ph = ",".join(["?" for _ in rows[0]])
#                 #print(f"[ACTION] Inserting {len(rows)} rows for full-copy '{tbl}'")
#                 dest_conn.executemany(f"INSERT INTO '{tbl}' VALUES ({ph});", rows)
#                 dest_conn.commit()

#     dest_tables = get_tables(dest_conn)

#     # Step 2: Sync partial and drop extra columns
#     for tbl in source_tables:
#         if tbl in exclude_tables or tbl not in dest_tables or tbl in fullcopy_tables:
#             # if tbl in exclude_tables:
#                 #print(f"[INFO] Skipping excluded table '{tbl}'")
#             continue

#         #print(f"[INFO] Syncing table '{tbl}'")
#         src_cols = get_columns(source_conn, tbl)
#         dst_cols = get_columns(dest_conn, tbl)

#         # Track newly added columns
#         new_cols = []
#         for col, info in src_cols.items():
#             if col not in dst_cols:
#                 col_type = info[2]
#                 default = info[4]
#                 #print(f"[ACTION] Adding column '{col}' to '{tbl}'")
#                 sql = f"ALTER TABLE '{tbl}' ADD COLUMN '{col}' {col_type}"
#                 if default is not None:
#                     sql += f" DEFAULT {default}"
#                 dest_conn.execute(sql)
#                 dest_conn.commit()
#                 new_cols.append(col)

#         # Populate new columns with source data
#         if new_cols and 'ID' in src_cols:
#             #print(f"[ACTION] Populating new columns {new_cols} in '{tbl}'")
#             ids = [r[0] for r in source_conn.execute(f"SELECT ID FROM '{tbl}';")]
#             qm = ",".join(["?" for _ in ids])
#             for col in new_cols:
#                 #print(f"[DEBUG] Fetching and updating column '{col}'")
#                 q = f"SELECT ID, {col} FROM '{tbl}' WHERE ID IN ({qm});"
#                 rows = source_conn.execute(q, tuple(ids)).fetchall()
#                 data = [(val, id_) for id_, val in rows]
#                 dest_conn.executemany(f"UPDATE '{tbl}' SET {col}=? WHERE ID=?;", data)
#             dest_conn.commit()

#         # Drop extra columns
#         extra = [c for c in dst_cols if c not in src_cols]
#         if extra:
#             #print(f"[ACTION] Dropping extra columns {extra} from '{tbl}'")
#             keep = list(src_cols.keys())
#             drop_extraneous_columns(dest_conn, tbl, keep)

#         # Sync rows
#         if 'ID' in src_cols:
#             #print(f"[ACTION] Syncing rows for '{tbl}'")
#             src_ids = {r[0] for r in source_conn.execute(f"SELECT ID FROM '{tbl}';")}
#             dst_ids = {r[0] for r in dest_conn.execute(f"SELECT ID FROM '{tbl}';")}
#             to_ins = src_ids - dst_ids
#             if to_ins:
#                 #print(f"[DEBUG] Inserting {len(to_ins)} new rows into '{tbl}'")
#                 cols = list(src_cols.keys())
#                 ph = ",".join(["?" for _ in cols])
#                 qm = ",".join(["?" for _ in to_ins])
#                 q = f"SELECT {','.join(cols)} FROM '{tbl}' WHERE ID IN ({qm});"
#                 rows = source_conn.execute(q, tuple(to_ins)).fetchall()
                
#                 # dest_conn.executemany(
#                 #     f"INSERT INTO '{tbl}' ({','.join([f"'{c}'" for c in cols])}) VALUES ({ph});",
#                 #     rows
#                 # )
#                 # 1) Costruisco una stringa con i nomi delle colonne quotati con apici singoli
#                 cols_part = ",".join("'" + c + "'" for c in cols)
#                 #    se cols = ['name', 'age', 'city'], cols_part diventa: "'name','age','city'"

#                 # 2) Composizione della query senza annidare f-string
#                 sql = f"INSERT INTO '{tbl}' ({cols_part}) VALUES ({ph});"
#                 #    se tbl = 'users' e ph = '?,?,?', sql diventa:
#                 #    "INSERT INTO 'users' ('name','age','city') VALUES (?,?,?);"

#                 # 3) Chiamo executemany con la query già pronta
#                 dest_conn.executemany(sql, rows)

#                 dest_conn.commit()
#             to_del = dst_ids - src_ids
#             if to_del:
#                 #print(f"[DEBUG] Deleting {len(to_del)} rows from '{tbl}'")
#                 qm = ",".join(["?" for _ in to_del])
#                 dest_conn.execute(f"DELETE FROM '{tbl}' WHERE ID IN ({qm});", tuple(to_del))
#                 dest_conn.commit()

#         # 'sets' full-field sync
#         if 'sets' in tbl:
#             #print(f"[ACTION] Full-field copying data for 'sets' table '{tbl}'")
#             common = src_ids & dst_ids
#             cols = [c for c in src_cols if c not in ('ID', 'value')]
#             qm = ",".join(["?" for _ in common])
#             for col in cols:
#                 #print(f"[DEBUG] Updating column '{col}' in '{tbl}'")
#                 q = f"SELECT ID, {col} FROM '{tbl}' WHERE ID IN ({qm});"
#                 rows = source_conn.execute(q, tuple(common)).fetchall()
#                 data = [(val, id_) for id_, val in rows]
#                 dest_conn.executemany(f"UPDATE '{tbl}' SET {col}=? WHERE ID=?;", data)
#             dest_conn.commit()


# ====================================================================================
#  da file json
def main():
    parser = argparse.ArgumentParser(
        description="SQLite synchronization utility reading config from JSON"
    )
    parser.add_argument('source', help='Path to source SQLite DB')
    parser.add_argument('dest', help='Path to destination SQLite DB')
    parser.add_argument(
        '--json-config', required=True,
        help="JSON config file containing dbSync configurations"
    )
    args = parser.parse_args()

    with open(args.json_config, 'r') as jf:
        data = json.load(jf)

    # dbSyncConfigs maps DB filenames to table actions
    dbSyncConfigs = data.get('dbSyncConfigs', {})

    # Determine config for this source DB by base filename
    src_db_name = os.path.basename(args.source)
    cfg = dbSyncConfigs.get(src_db_name, {})

    exclude_tables = {tbl for tbl, act in cfg.items() if act.lower() == 'exclude'}
    fullcopy_tables = {tbl for tbl, act in cfg.items() if act.lower() == 'fullcopy'}
    colsfield_tables = {tbl for tbl, act in cfg.items() if act.lower() == 'ncolfield'}
    fullsync_tables = {tbl for tbl, act in cfg.items() if act.lower() == 'fullsync'}
    fullfield_tables = {tbl for tbl, act in cfg.items() if act.lower() == 'fullfield'}
    
    print(f"[INFO] Using config for '{src_db_name}': exclude={exclude_tables}, fullcopy={fullcopy_tables}")
    print(f"[INFO] colsfield={colsfield_tables}, fullsync={fullsync_tables}, fullfield={fullfield_tables}")

    src_conn = sqlite3.connect(args.source)
    dst_conn = sqlite3.connect(args.dest)
    try:
        sync_tables(src_conn, dst_conn, exclude_tables, fullcopy_tables, colsfield_tables, fullsync_tables, fullfield_tables)
    finally:
        src_conn.close()
        dst_conn.close()


# if __name__ == '__main__':
#     main()

