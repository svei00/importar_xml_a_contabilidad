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
    c.execute("""
    CREATE TABLE IF NOT EXISTS alias_terceros (
        rfc TEXT PRIMARY KEY,
        shortname TEXT,
        nombre_oficial TEXT,
        actualizado TEXT
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

def limpiar_etiquetas(rfc, prefijos_excluir):
    """Borra etiquetas cuya cuenta empieza con un prefijo no aprendible
    (banco/IVA/proveedor mal aprendidos en corridas previas). Devuelve cuántas borró."""
    conn = get_conn(rfc); c = conn.cursor()
    borradas = 0
    try:
        filas = c.execute("SELECT uuid, cuenta FROM etiquetas").fetchall()
        malas = [u for (u, cta) in filas if str(cta).strip()[:3] in set(prefijos_excluir)]
        for u in malas:
            c.execute("DELETE FROM etiquetas WHERE uuid=?", (u,))
        borradas = len(malas)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
    return borradas

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

# ---------------------------------------------------------------------------
# Alias de terceros (RFC -> apodo corto) para la Referencia de pólizas.
# Se guardan en la BD de CADA empresa (empresas/<RFC_EMPRESA>/conta_ml.db).
# ---------------------------------------------------------------------------
def _ensure_alias_table(c):
    c.execute("""
    CREATE TABLE IF NOT EXISTS alias_terceros (
        rfc TEXT PRIMARY KEY, shortname TEXT, nombre_oficial TEXT, actualizado TEXT
    )""")

def ensure_alias(empresa_rfc, tercero_rfc, nombre_oficial, default_short):
    """Inserta el alias por defecto solo si el RFC del tercero aún no existe."""
    tercero_rfc = str(tercero_rfc).strip().upper()
    if not tercero_rfc or tercero_rfc == "NAN" or len(tercero_rfc) < 12:
        return
    import datetime
    conn = get_conn(empresa_rfc); c = conn.cursor()
    _ensure_alias_table(c)
    c.execute("SELECT rfc FROM alias_terceros WHERE rfc=?", (tercero_rfc,))
    if c.fetchone() is None:
        c.execute("INSERT INTO alias_terceros VALUES (?,?,?,?)",
                  (tercero_rfc, default_short, str(nombre_oficial)[:200],
                   datetime.date.today().isoformat()))
    conn.commit(); conn.close()

def set_alias(empresa_rfc, tercero_rfc, shortname):
    """Guarda/actualiza el apodo elegido por el usuario."""
    import datetime
    tercero_rfc = str(tercero_rfc).strip().upper()
    conn = get_conn(empresa_rfc); c = conn.cursor()
    _ensure_alias_table(c)
    c.execute("""INSERT INTO alias_terceros (rfc, shortname, actualizado) VALUES (?,?,?)
                 ON CONFLICT(rfc) DO UPDATE SET shortname=excluded.shortname,
                 actualizado=excluded.actualizado""",
              (tercero_rfc, shortname, datetime.date.today().isoformat()))
    conn.commit(); conn.close()

def get_aliases(empresa_rfc):
    """Devuelve {rfc: shortname} para construir las Referencias."""
    conn = get_conn(empresa_rfc); c = conn.cursor()
    _ensure_alias_table(c)
    c.execute("SELECT rfc, shortname FROM alias_terceros")
    data = {r[0]: r[1] for r in c.fetchall() if r[1]}
    conn.close()
    return data

def get_aliases_full(empresa_rfc):
    """Devuelve [(rfc, shortname, nombre_oficial)] ordenado, para la GUI."""
    conn = get_conn(empresa_rfc); c = conn.cursor()
    _ensure_alias_table(c)
    c.execute("SELECT rfc, shortname, nombre_oficial FROM alias_terceros ORDER BY nombre_oficial")
    data = c.fetchall()
    conn.close()
    return data

def list_empresas():
    """Lista los RFC de empresa que ya tienen base de datos."""
    base = "empresas"
    if not os.path.exists(base):
        return []
    return sorted(d for d in os.listdir(base)
                  if os.path.exists(os.path.join(base, d, "conta_ml.db")))

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