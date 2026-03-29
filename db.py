import sqlite3
import os

def get_db_path(rfc):
    safe_rfc = "".join(c for c in str(rfc) if c.isalnum())
    db_dir = os.path.join("empresas", safe_rfc)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    return os.path.join(db_dir, "conta_ml.db")

def get_conn(rfc):
    return sqlite3.connect(get_db_path(rfc))

def init_db(rfc):
    conn = get_conn(rfc)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS facturas (
        uuid TEXT PRIMARY KEY, fecha TEXT, tipo TEXT,
        rfc_emisor TEXT, rfc_receptor TEXT,
        nombre_emisor TEXT, nombre_receptor TEXT,
        concepto TEXT, subtotal REAL, iva_16 REAL,
        total REAL, cp TEXT, estado_sat TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS etiquetas (
        uuid TEXT PRIMARY KEY, cuenta TEXT, centro_costo TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS historial_diot (
        mes TEXT, anio TEXT, consecutivo INTEGER,
        PRIMARY KEY (mes, anio)
    )
    """)
    conn.commit()
    conn.close()

def upsert_factura(rfc, row):
    conn = get_conn(rfc)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO facturas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
    conn.commit()
    conn.close()

# ¡LA FUNCIÓN QUE FALTABA!
def upsert_etiqueta(rfc, uuid, cuenta, centro):
    conn = get_conn(rfc)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO etiquetas VALUES (?,?,?)", (uuid, cuenta, centro))
    conn.commit()
    conn.close()

def get_training_data(rfc):
    conn = get_conn(rfc)
    df = None
    try:
        import pandas as pd
        df = pd.read_sql_query("""
        SELECT f.concepto, f.nombre_emisor as proveedor, f.cp, e.cuenta, e.centro_costo
        FROM facturas f
        JOIN etiquetas e ON f.uuid = e.uuid
        """, conn)
    except Exception:
        pass
    finally:
        conn.close()
    return df

def get_tipo_diot_automatico(rfc, mes, anio):
    conn = get_conn(rfc)
    c = conn.cursor()
    c.execute("SELECT consecutivo FROM historial_diot WHERE mes=? AND anio=?", (mes, anio))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO historial_diot VALUES (?,?,?)", (mes, anio, 0))
        tipo = "N"
    else:
        consecutivo = row[0] + 1
        c.execute("UPDATE historial_diot SET consecutivo=? WHERE mes=? AND anio=?", (consecutivo, mes, anio))
        tipo = f"C{consecutivo}"
    conn.commit()
    conn.close()
    return tipo