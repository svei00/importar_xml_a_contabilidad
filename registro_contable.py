"""
registro_contable.py - La MEMORIA de la app: que ya se contabilizo y en que cuenta.

Vive en la misma base de datos de cada empresa (empresas/<RFC>/conta_ml.db), en
tablas NUEVAS. La tabla vieja `facturas` no se toca: esa se escribe al PARSEAR y
alimenta el modelo ML; esta se escribe al CONTABILIZAR.

Tablas:
  lotes                      una fila por corrida (o por siembra de historial)
  documentos_contabilizados  una fila por CFDI de cada lote, con su resultado
  pagos_aplicados            que factura cancelo cada pago (REP)

Ciclo de vida de un lote (idempotencia):
  Cada corrida crea un lote nuevo. Los lotes anteriores del MISMO tipo y
  periodo pasan a 'reemplazado'. Asi, correr agosto dos veces no marca los CFDI
  de agosto como duplicados de la corrida anterior.
  Para buscar duplicados solo cuentan los lotes 'vigente' y 'historico'.
"""
import datetime
from db import get_conn

ESTADO_VIGENTE = "vigente"
ESTADO_HISTORICO = "historico"          # sembrado a mano desde XML de meses anteriores
ESTADO_SIN_MOVIMIENTOS = "sin_movimientos"
ESTADO_REEMPLAZADO = "reemplazado"

# Lotes cuyos documentos SI cuentan como "ya contabilizado".
_ESTADOS_QUE_CUENTAN = (ESTADO_VIGENTE, ESTADO_HISTORICO)

COLUMNAS_DOCUMENTO = (
    "uuid", "lote_id", "llave_negocio", "tipo_cfdi", "metodo_pago", "forma_pago",
    "rfc_tercero", "serie", "folio", "total", "fecha_cfdi", "fecha_poliza",
    "tipo_poliza", "numero_poliza_en_lote", "cuenta_principal", "cuenta_tercero",
    "cuenta_contrapartida", "resultado", "documento_original_uuid",
)


def crear_tablas(empresa_rfc):
    """Crea las tablas del registro si no existen (no destructivo)."""
    conn = get_conn(empresa_rfc)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS lotes (
        lote_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo_operacion  TEXT NOT NULL,
        periodo         TEXT NOT NULL,
        carpeta_origen  TEXT,
        archivo_txt     TEXT,
        generado_en     TEXT NOT NULL,
        estado          TEXT NOT NULL
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS documentos_contabilizados (
        uuid                     TEXT NOT NULL,
        lote_id                  INTEGER NOT NULL,
        llave_negocio            TEXT,
        tipo_cfdi                TEXT,
        metodo_pago              TEXT,
        forma_pago               TEXT,
        rfc_tercero              TEXT,
        serie                    TEXT,
        folio                    TEXT,
        total                    REAL,
        fecha_cfdi               TEXT,
        fecha_poliza             TEXT,
        tipo_poliza              TEXT,
        numero_poliza_en_lote    INTEGER,
        cuenta_principal         TEXT,
        cuenta_tercero           TEXT,
        cuenta_contrapartida     TEXT,
        resultado                TEXT NOT NULL,
        documento_original_uuid  TEXT,
        PRIMARY KEY (uuid, lote_id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_doc_llave ON documentos_contabilizados(llave_negocio)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_doc_uuid ON documentos_contabilizados(uuid)")
    c.execute("""
    CREATE TABLE IF NOT EXISTS pagos_aplicados (
        uuid_pago          TEXT NOT NULL,
        lote_id            INTEGER NOT NULL,
        id_documento       TEXT NOT NULL,
        imp_pagado         REAL,
        imp_saldo_insoluto REAL,
        cuenta_cancelada   TEXT,
        PRIMARY KEY (uuid_pago, lote_id, id_documento)
    )""")
    conn.commit()
    conn.close()


def crear_lote(empresa_rfc, tipo_operacion, periodo, carpeta_origen, estado, archivo_txt=""):
    """
    Abre un lote nuevo y devuelve su lote_id. Los lotes anteriores del mismo
    (tipo_operacion, periodo) que estaban activos pasan a 'reemplazado'.
    """
    conn = get_conn(empresa_rfc)
    c = conn.cursor()
    c.execute("""UPDATE lotes SET estado=?
                 WHERE tipo_operacion=? AND periodo=? AND estado IN (?,?,?)""",
              (ESTADO_REEMPLAZADO, tipo_operacion, periodo,
               ESTADO_VIGENTE, ESTADO_HISTORICO, ESTADO_SIN_MOVIMIENTOS))
    c.execute("""INSERT INTO lotes (tipo_operacion, periodo, carpeta_origen, archivo_txt, generado_en, estado)
                 VALUES (?,?,?,?,?,?)""",
              (tipo_operacion, periodo, carpeta_origen, archivo_txt,
               datetime.datetime.now().isoformat(timespec="seconds"), estado))
    lote_id = c.lastrowid
    conn.commit()
    conn.close()
    return lote_id


def guardar_documentos(empresa_rfc, lote_id, documentos):
    """Guarda la lista de diccionarios (una clave por columna) en el lote indicado."""
    filas = []
    for doc in documentos:
        doc = dict(doc, lote_id=lote_id)
        filas.append(tuple(doc.get(columna) for columna in COLUMNAS_DOCUMENTO))
    marcas = ",".join("?" * len(COLUMNAS_DOCUMENTO))
    conn = get_conn(empresa_rfc)
    conn.executemany(
        f"INSERT OR REPLACE INTO documentos_contabilizados ({','.join(COLUMNAS_DOCUMENTO)}) VALUES ({marcas})",
        filas)
    conn.commit()
    conn.close()


def guardar_pagos_aplicados(empresa_rfc, lote_id, uuid_pago, aplicaciones):
    """Guarda que factura cancelo cada linea de un REP (aplicaciones = lista de dicts)."""
    conn = get_conn(empresa_rfc)
    for ap in aplicaciones:
        if not ap.get("id_documento"):
            continue   # la linea residual no apunta a ninguna factura
        conn.execute(
            "INSERT OR REPLACE INTO pagos_aplicados VALUES (?,?,?,?,?,?)",
            (uuid_pago, lote_id, ap["id_documento"], ap.get("imp_pagado"),
             ap.get("imp_saldo_insoluto"), ap.get("cuenta")))
    conn.commit()
    conn.close()


def _consulta_documento_previo(empresa_rfc, condicion, parametro, tipo_operacion, periodo):
    """
    Busca un documento 'contabilizado' en lotes que cuentan, EXCLUYENDO el lote
    de la corrida actual (mismo tipo y periodo, porque ese se va a reemplazar).
    Devuelve el mas antiguo como diccionario, o None.
    """
    marcas_estados = ",".join("?" * len(_ESTADOS_QUE_CUENTAN))
    conn = get_conn(empresa_rfc)
    fila = conn.execute(f"""
        SELECT d.uuid, d.fecha_cfdi, d.cuenta_tercero, l.periodo, l.tipo_operacion
        FROM documentos_contabilizados d JOIN lotes l ON l.lote_id = d.lote_id
        WHERE {condicion} AND d.resultado = 'contabilizado'
          AND l.estado IN ({marcas_estados})
          AND NOT (l.tipo_operacion = ? AND l.periodo = ?)
        ORDER BY d.fecha_cfdi ASC, d.uuid ASC LIMIT 1""",
        (parametro, *_ESTADOS_QUE_CUENTAN, tipo_operacion, periodo)).fetchone()
    conn.close()
    if fila is None:
        return None
    return {"uuid": fila[0], "fecha_cfdi": fila[1], "cuenta_tercero": fila[2],
            "periodo": fila[3], "tipo_operacion": fila[4]}


def buscar_documento_por_uuid(empresa_rfc, uuid, tipo_operacion, periodo):
    """Documento ya contabilizado con ese UUID en otro lote (o None)."""
    return _consulta_documento_previo(empresa_rfc, "UPPER(d.uuid) = ?",
                                      str(uuid).upper(), tipo_operacion, periodo)


def buscar_documento_por_llave(empresa_rfc, llave, tipo_operacion, periodo):
    """Documento ya contabilizado con esa llave de negocio en otro lote (o None)."""
    return _consulta_documento_previo(empresa_rfc, "d.llave_negocio = ?",
                                      llave, tipo_operacion, periodo)


def buscar_cuenta_de_documento(empresa_rfc, uuid):
    """
    Para la regla A. Devuelve (conocido, cuenta):
      conocido = True si el UUID esta en el registro (en un lote que cuenta)
      cuenta   = la cuenta de tercero que se uso al contabilizarlo (o None si
                 el documento fue sembrado sin cuenta)
    A diferencia de la busqueda de duplicados, aqui SI cuenta el lote del mismo
    periodo (una factura PPD y su REP pueden ser del mismo mes).
    """
    marcas_estados = ",".join("?" * len(_ESTADOS_QUE_CUENTAN))
    conn = get_conn(empresa_rfc)
    fila = conn.execute(f"""
        SELECT d.cuenta_tercero
        FROM documentos_contabilizados d JOIN lotes l ON l.lote_id = d.lote_id
        WHERE UPPER(d.uuid) = ? AND d.resultado = 'contabilizado' AND l.estado IN ({marcas_estados})
        ORDER BY (d.cuenta_tercero IS NULL), d.fecha_cfdi ASC LIMIT 1""",
        (str(uuid).upper(), *_ESTADOS_QUE_CUENTAN)).fetchone()
    conn.close()
    if fila is None:
        return False, None
    return True, (fila[0] or None)
