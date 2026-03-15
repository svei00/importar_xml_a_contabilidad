# db.py
import sqlite3

DB = "empresas/empresa_1/conta_ml.db"

def get_conn():
    return sqlite3.connect(DB)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Facturas (ingresos/egresos/pagos)
    c.execute("""
    CREATE TABLE IF NOT EXISTS facturas (
        uuid TEXT PRIMARY KEY,
        fecha TEXT,
        tipo TEXT,
        rfc_emisor TEXT,
        rfc_receptor TEXT,
        nombre_emisor TEXT,
        nombre_receptor TEXT,
        concepto TEXT,
        subtotal REAL,
        iva REAL,
        total REAL,
        cp TEXT,
        estado_sat TEXT
    )
    """)

    # Etiquetas/decisiones contables (para ML)
    c.execute("""
    CREATE TABLE IF NOT EXISTS etiquetas (
        uuid TEXT,
        cuenta TEXT,
        centro_costo TEXT,
        PRIMARY KEY (uuid)
    )
    """)

    conn.commit()
    conn.close()

def upsert_factura(row):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO facturas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, row)
    conn.commit()
    conn.close()

def upsert_etiqueta(uuid, cuenta, centro):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO etiquetas VALUES (?,?,?)
    """, (uuid, cuenta, centro))
    conn.commit()
    conn.close()

def get_training_data():
    conn = get_conn()
    df = None
    try:
        import pandas as pd
        df = pd.read_sql_query("""
        SELECT f.concepto, f.nombre_emisor as proveedor, f.cp, e.cuenta, e.centro_costo
        FROM facturas f
        JOIN etiquetas e ON f.uuid = e.uuid
        """, conn)
    finally:
        conn.close()
    return df