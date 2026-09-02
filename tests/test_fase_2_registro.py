"""
Pruebas de la Fase 2: registro de lo contabilizado, reexpediciones (caso D) y
cuenta de tercero / pagos (caso A).

Las pruebas con base de datos corren dentro de una carpeta temporal (tmp_path),
asi que NUNCA tocan empresas/ ni settings.json reales.
La prueba de aceptacion usa los XML reales y requiere BOVEDA_CFDI (ver Fase 1).
"""
import os
import sys
import json

import pytest

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

import db
import registro_contable as registro
from excepciones import ColectorDeExcepciones
from llave_negocio import construir_llave, llave_es_utilizable
from detector_reexpediciones import detectar_reexpediciones
from cuenta_de_tercero import (resolver_cuenta_de_documento, armar_aplicaciones_pago,
                               ORIGEN_ALIAS, ORIGEN_DEFAULT, ORIGEN_REGISTRO, ORIGEN_ESTA_CORRIDA)

EMPRESA = "EEA251205CR8"


@pytest.fixture
def carpeta_aislada(tmp_path, monkeypatch):
    """Cada prueba corre en una carpeta vacia: su propia empresas/ y su propio settings.json."""
    monkeypatch.chdir(tmp_path)
    db.init_db(EMPRESA)
    registro.crear_tablas(EMPRESA)
    return tmp_path


def doc(uuid, llave="", resultado="contabilizado", fecha="2026-07-15", cuenta=None):
    return {"uuid": uuid, "llave_negocio": llave, "tipo_cfdi": "I", "total": 100.0,
            "fecha_cfdi": fecha, "resultado": resultado, "cuenta_tercero": cuenta}


# --- Llave de negocio -------------------------------------------------------
def test_llave_normaliza_mayusculas_espacios_y_decimales():
    assert construir_llave("inf7205011za", "", " pp 347188 ", 495.8) == "INF7205011ZA||PP347188|495.80"


def test_llave_sin_serie_ni_folio_no_es_utilizable():
    assert not llave_es_utilizable(construir_llave("AAA010101AAA", "", "", 100))
    assert llave_es_utilizable(construir_llave("AAA010101AAA", "", "77", 100))


# --- Registro: ciclo de vida del lote ---------------------------------------
def test_un_lote_nuevo_reemplaza_al_anterior_del_mismo_periodo(carpeta_aislada):
    primero = registro.crear_lote(EMPRESA, "egresos", "2026-08", "c", registro.ESTADO_VIGENTE)
    segundo = registro.crear_lote(EMPRESA, "egresos", "2026-08", "c", registro.ESTADO_VIGENTE)
    conn = db.get_conn(EMPRESA)
    estados = dict(conn.execute("SELECT lote_id, estado FROM lotes").fetchall())
    conn.close()
    assert estados[primero] == registro.ESTADO_REEMPLAZADO
    assert estados[segundo] == registro.ESTADO_VIGENTE


def test_duplicado_se_busca_en_otros_periodos_no_en_el_propio(carpeta_aislada):
    julio = registro.crear_lote(EMPRESA, "egresos", "2026-07", "c", registro.ESTADO_HISTORICO)
    registro.guardar_documentos(EMPRESA, julio, [doc("AAA", llave="L1")])
    agosto = registro.crear_lote(EMPRESA, "egresos", "2026-08", "c", registro.ESTADO_VIGENTE)
    registro.guardar_documentos(EMPRESA, agosto, [doc("BBB", llave="L2", fecha="2026-08-10")])

    # Desde agosto, lo de julio SI cuenta como previo; lo de agosto mismo NO.
    assert registro.buscar_documento_por_uuid(EMPRESA, "aaa", "egresos", "2026-08")["uuid"] == "AAA"
    assert registro.buscar_documento_por_llave(EMPRESA, "L1", "egresos", "2026-08")["periodo"] == "2026-07"
    assert registro.buscar_documento_por_uuid(EMPRESA, "BBB", "egresos", "2026-08") is None


def test_documentos_cancelados_u_omitidos_no_cuentan_como_contabilizados(carpeta_aislada):
    julio = registro.crear_lote(EMPRESA, "egresos", "2026-07", "c", registro.ESTADO_VIGENTE)
    registro.guardar_documentos(EMPRESA, julio, [doc("CCC", llave="L9", resultado="cancelado")])
    assert registro.buscar_documento_por_uuid(EMPRESA, "CCC", "egresos", "2026-08") is None
    assert registro.buscar_documento_por_llave(EMPRESA, "L9", "egresos", "2026-08") is None


def test_lote_reemplazado_ya_no_cuenta(carpeta_aislada):
    viejo = registro.crear_lote(EMPRESA, "egresos", "2026-07", "c", registro.ESTADO_VIGENTE)
    registro.guardar_documentos(EMPRESA, viejo, [doc("DDD", llave="L5")])
    registro.crear_lote(EMPRESA, "egresos", "2026-07", "c", registro.ESTADO_VIGENTE)  # lo reemplaza
    assert registro.buscar_documento_por_uuid(EMPRESA, "DDD", "egresos", "2026-08") is None


def test_buscar_cuenta_de_documento_distingue_conocido_sin_cuenta(carpeta_aislada):
    lote = registro.crear_lote(EMPRESA, "egresos", "2026-07", "c", registro.ESTADO_HISTORICO)
    registro.guardar_documentos(EMPRESA, lote, [doc("SIN", cuenta=None), doc("CON", cuenta="20101002")])
    assert registro.buscar_cuenta_de_documento(EMPRESA, "sin") == (True, None)
    assert registro.buscar_cuenta_de_documento(EMPRESA, "con") == (True, "20101002")
    assert registro.buscar_cuenta_de_documento(EMPRESA, "otro") == (False, None)


# --- Detector de reexpediciones (con busquedas falsas, sin base de datos) ---
def fila_cfdi(uuid, folio="PP1", total=100.0, fecha="2026-08-07T10:00:00", tipo="I"):
    return {"uuid": uuid, "tipo": tipo, "rfc_emisor": "INF7205011ZA", "serie": "", "folio": folio,
            "total": total, "fecha": fecha, "omitir": False, "motivo_omision": ""}


def sin_previo(_):
    return None


def test_reexpedicion_por_uuid_ya_registrado():
    filas = [fila_cfdi("U1")]
    previo = {"uuid": "U1", "fecha_cfdi": "2026-07-15", "periodo": "2026-07"}
    colector = ColectorDeExcepciones()
    detectar_reexpediciones(filas, "2026-08", lambda u: previo, sin_previo, colector)
    assert filas[0]["omitir"] and filas[0]["motivo_omision"] == "reexpedicion"
    assert colector.todas()[0].codigo == "REEXPEDICION"


def test_reexpedicion_por_llave_de_negocio_con_otro_uuid():
    filas = [fila_cfdi("NUEVO", folio="PP347188", total=495.86)]
    previo = {"uuid": "ORIGINAL", "fecha_cfdi": "2026-07-15", "periodo": "2026-07"}
    colector = ColectorDeExcepciones()
    detectar_reexpediciones(filas, "2026-08", sin_previo, lambda llave: previo, colector)
    assert filas[0]["omitir"] and filas[0]["documento_original_uuid"] == "ORIGINAL"
    assert "ORIGINAL" in colector.todas()[0].mensaje


def test_misma_llave_dentro_del_lote_gana_la_mas_antigua():
    filas = [fila_cfdi("TARDE", fecha="2026-08-09T10:00:00"), fila_cfdi("TEMPRANO", fecha="2026-08-02T10:00:00")]
    detectar_reexpediciones(filas, "2026-08", sin_previo, sin_previo, ColectorDeExcepciones())
    por_uuid = {f["uuid"]: f for f in filas}
    assert not por_uuid["TEMPRANO"]["omitir"]
    assert por_uuid["TARDE"]["omitir"] and por_uuid["TARDE"]["documento_original_uuid"] == "TEMPRANO"


def test_comprobantes_sin_serie_ni_folio_no_se_confunden_entre_si():
    filas = [fila_cfdi("A", folio=""), fila_cfdi("B", folio="")]
    detectar_reexpediciones(filas, "2026-08", sin_previo, lambda llave: pytest.fail("no debe buscar"),
                            ColectorDeExcepciones())
    assert not filas[0]["omitir"] and not filas[1]["omitir"]


def test_un_rep_solo_se_compara_por_uuid():
    filas = [fila_cfdi("REP1", tipo="P")]
    detectar_reexpediciones(filas, "2026-08", sin_previo, lambda llave: pytest.fail("no debe buscar"),
                            ColectorDeExcepciones())
    assert not filas[0]["omitir"]


# --- Caso A: cuenta de tercero ---------------------------------------------
def resolver_con(corrida=None, registro_dato=(False, None), alias=None):
    return lambda id_doc: resolver_cuenta_de_documento(
        id_doc, "CFE370814QI0", corrida or {}, lambda uuid: registro_dato, alias or {}, "20101999")


def test_orden_de_resolucion_corrida_registro_alias_default():
    assert resolver_con(corrida={"X": "20101005"})("x") == ("20101005", ORIGEN_ESTA_CORRIDA, True)
    assert resolver_con(registro_dato=(True, "20101003"))("x") == ("20101003", ORIGEN_REGISTRO, True)
    assert resolver_con(alias={"CFE370814QI0": "20101002"})("x") == ("20101002", ORIGEN_ALIAS, False)
    assert resolver_con()("x") == ("20101999", ORIGEN_DEFAULT, False)


def fila_rep(documentos, total):
    pagos = [{"fecha_pago": "2026-08-02T00:02:51", "forma_pago": "03", "monto": total, "documentos": documentos}]
    return {"uuid": "REP1", "tipo": "P", "total": total, "pagos_json": json.dumps(pagos)}


def doc_pagado(id_documento, importe, saldo=0.0):
    return {"id_documento": id_documento, "imp_pagado": importe, "imp_saldo_insoluto": saldo}


def test_rep_cancela_la_cuenta_donde_vive_su_factura():
    fila = fila_rep([doc_pagado("B4CB3AFC", 3907.00, 0.58)], 3907.00)
    resolver = resolver_con(alias={"CFE370814QI0": "20101002"})
    aplicaciones = armar_aplicaciones_pago(fila, resolver, "20101999", ColectorDeExcepciones())
    assert [(a["cuenta"], a["imp_pagado"]) for a in aplicaciones] == [("20101002", 3907.00)]


def test_rep_con_varias_facturas_se_reparte_por_documento():
    fila = fila_rep([doc_pagado("D1", 100.0), doc_pagado("D2", 50.0)], 150.0)
    registros = {"D1": (True, "20101002"), "D2": (True, "20101003")}
    resolver = lambda id_doc: resolver_cuenta_de_documento(
        id_doc, "X", {}, lambda uuid: registros[uuid], {}, "20101999")
    aplicaciones = armar_aplicaciones_pago(fila, resolver, "20101999", ColectorDeExcepciones())
    assert [(a["cuenta"], a["imp_pagado"]) for a in aplicaciones] == [("20101002", 100.0), ("20101003", 50.0)]


def test_documento_desconocido_avisa_pero_documento_sembrado_sin_cuenta_no():
    colector = ColectorDeExcepciones()
    armar_aplicaciones_pago(fila_rep([doc_pagado("RARO", 10.0)], 10.0), resolver_con(), "20101999", colector)
    assert [e.codigo for e in colector.todas()] == ["PAGO_DE_DOCUMENTO_NO_REGISTRADO"]

    colector2 = ColectorDeExcepciones()
    armar_aplicaciones_pago(fila_rep([doc_pagado("SEMBRADO", 10.0)], 10.0),
                            resolver_con(registro_dato=(True, None)), "20101999", colector2)
    assert colector2.cuantas() == 0


def test_pago_menor_al_monto_deja_linea_residual_a_la_cuenta_default():
    fila = fila_rep([doc_pagado("D1", 90.0)], 100.0)
    aplicaciones = armar_aplicaciones_pago(fila, resolver_con(), "20101999", ColectorDeExcepciones())
    assert round(sum(a["imp_pagado"] for a in aplicaciones), 2) == 100.0
    assert aplicaciones[-1]["cuenta"] == "20101999" and aplicaciones[-1]["imp_pagado"] == 10.0


def test_pago_mayor_al_monto_cae_a_una_sola_linea_y_avisa():
    colector = ColectorDeExcepciones()
    fila = fila_rep([doc_pagado("D1", 150.0)], 100.0)
    aplicaciones = armar_aplicaciones_pago(fila, resolver_con(), "20101999", colector)
    assert [(a["cuenta"], a["imp_pagado"]) for a in aplicaciones] == [("20101999", 100.0)]
    assert "PAGO_DESCUADRADO_CON_DOCUMENTOS" in [e.codigo for e in colector.todas()]


# --- generar_polizas lee las lineas del pago --------------------------------
def test_poliza_del_rep_carga_la_cuenta_de_cada_factura_y_cuadra(carpeta_aislada):
    import pandas as pd
    from export import generar_polizas
    aplicaciones = [{"id_documento": "B4CB3AFC", "imp_pagado": 3907.0, "cuenta": "20101002"}]
    df = pd.DataFrame([{
        "uuid": "REP1", "tipo": "P", "metodo_pago": "PPD", "concepto": "Complemento de Pago (REP)",
        "referencia": "B4CB3AFC", "rfc_emisor": "CFE370814QI0", "nombre_emisor": "CFE",
        "rfc_receptor": EMPRESA, "nombre_receptor": "ECA", "fecha": "2026-08-02T00:02:51",
        "cuenta": "10201001", "total": 3907.0, "iva_16": 538.98, "iva_8": 0.0, "ret_isr": 0.0,
        "ret_iva": 0.0, "ieps": 0.0, "subtotal": 0.0, "departamento": "General",
        "aplicaciones_pago": json.dumps(aplicaciones), "cuenta_tercero": "20101002"}])
    polizas = generar_polizas(df, is_egresos=True)
    assert (polizas["Cuenta"] == "20101002").any()
    assert polizas.loc[polizas["Cuenta"] == "20101002", "Debe"].iloc[0] == 3907.0
    assert round(polizas["Debe"].sum(), 2) == round(polizas["Haber"].sum(), 2)
    assert not (polizas["Cuenta"] == "20101999").any()


def test_rep_sin_columna_de_aplicaciones_se_comporta_como_antes(carpeta_aislada):
    import pandas as pd
    from export import generar_polizas
    df = pd.DataFrame([{
        "uuid": "REP2", "tipo": "P", "metodo_pago": "PPD", "concepto": "REP", "referencia": "X",
        "rfc_emisor": "TME840315KT6", "nombre_emisor": "Telmex", "rfc_receptor": EMPRESA,
        "nombre_receptor": "ECA", "fecha": "2026-08-05", "cuenta": "10201001", "total": 100.0,
        "iva_16": 0.0, "iva_8": 0.0, "ret_isr": 0.0, "ret_iva": 0.0, "ieps": 0.0, "subtotal": 0.0,
        "departamento": "General"}])
    polizas = generar_polizas(df, is_egresos=True)
    assert polizas.iloc[0]["Cuenta"] == "20101999" and polizas.iloc[0]["Debe"] == 100.0


# --- Aceptacion con los XML REALES: siembra julio, corre agosto -------------
BOVEDA = os.environ.get("BOVEDA_CFDI", "")
JULIO = os.path.join(BOVEDA, EMPRESA, "Recibidas", "2026", "07")
AGOSTO = os.path.join(BOVEDA, EMPRESA, "Recibidas", "2026", "08")
requiere_xml_reales = pytest.mark.skipif(
    not (BOVEDA and os.path.isdir(JULIO) and os.path.isdir(AGOSTO)),
    reason="Define BOVEDA_CFDI para correr la aceptacion con XML reales")


def _correr_agosto():
    """Simula una corrida de agosto (sin SAT) y devuelve (filas, colector)."""
    from xml_processor import load_folder
    from reglas_contables import aplicar_reglas
    filas = load_folder(AGOSTO)
    for f in filas:
        f["estado_sat"] = "VIGENTE"
    colector = ColectorDeExcepciones()
    aplicar_reglas(filas, {"cuentas_default": {}}, colector, empresa_rfc=EMPRESA, tipo_operacion="egresos")
    return filas, colector


@requiere_xml_reales
def test_aceptacion_infonavit_es_reexpedicion_y_cfe_cancela_su_cuenta(carpeta_aislada):
    from sembrar_historial import sembrar_desde_carpeta
    resumen = sembrar_desde_carpeta(JULIO, "egresos")
    assert resumen["periodo"] == "2026-07" and resumen["sembrados"] == 6

    db.ensure_alias(EMPRESA, "CFE370814QI0", "COMISION FEDERAL DE ELECTRICIDAD", "CFE", tipo="P")
    db.set_alias_cuenta(EMPRESA, "CFE370814QI0", "20101002")

    filas, colector = _correr_agosto()
    por_uuid = {f["uuid"][:8].lower(): f for f in filas}

    # Caso D: el INFONAVIT de agosto es reexpedicion del de julio; no genera poliza.
    infonavit = por_uuid["fac86dcb"]
    assert infonavit["omitir"] and infonavit["motivo_omision"] == "reexpedicion"
    assert infonavit["documento_original_uuid"].lower().startswith("5f09f69b")
    # Las otras 4 siguen siendo contabilizables.
    assert sorted(k for k, f in por_uuid.items() if not f["omitir"]) == [
        "4295eff7", "d66001ab", "e7e5db0a", "fad179f3"]

    # Caso A: el REP de CFE cancela 201-01-002; el de Telmex (sin alias) queda en la cuenta varios.
    cfe = json.loads(por_uuid["4295eff7"]["aplicaciones_pago"])
    assert [(a["cuenta"], a["imp_pagado"]) for a in cfe] == [("20101002", 3907.0)]
    telmex = json.loads(por_uuid["fad179f3"]["aplicaciones_pago"])
    assert [(a["cuenta"], a["imp_pagado"]) for a in telmex] == [("20101999", 388.99)]


@requiere_xml_reales
def test_aceptacion_correr_agosto_dos_veces_da_lo_mismo(carpeta_aislada):
    from sembrar_historial import sembrar_desde_carpeta
    from registrar_corrida import registrar_lote
    sembrar_desde_carpeta(JULIO, "egresos")

    filas1, _ = _correr_agosto()
    registrar_lote(EMPRESA, "egresos", "2026-08", AGOSTO, filas1, registro.ESTADO_VIGENTE)

    filas2, _ = _correr_agosto()   # segunda corrida del mismo mes
    omitidas = lambda filas: sorted(f["uuid"][:8].lower() for f in filas if f["omitir"])
    assert omitidas(filas1) == omitidas(filas2) == ["fac86dcb"]
