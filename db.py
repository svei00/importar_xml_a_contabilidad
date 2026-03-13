import sqlite3

def init_db():
    conn = sqlite3.connect("data/contabilidad.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS facturas (
        uuid TEXT PRIMARY KEY,
        rfc_emisor TEXT,
        rfc_receptor TEXT,
        concepto TEXT,
        total REAL,
        iva REAL,
        cuenta TEXT,
        centro TEXT,
        estatus_sat TEXT
    )
    """)

    conn.commit()
    conn.close()