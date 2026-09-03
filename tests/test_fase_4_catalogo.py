"""
Pruebas de la Fase 4: validacion de cuentas contra el catalogo de CONTPAQi (caso E).

Las pruebas puras construyen un cuentas.txt pequeno de ANCHO FIJO. La de
aceptacion usa tu catalogo real en stuff/cuentas.txt (carpeta ignorada por git;
si no existe, esas pruebas se saltan).
"""
import os
import sys

import pytest

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

import db
from excepciones import ColectorDeExcepciones
from reglas_contables import aplicar_reglas
from catalogo_contpaqi import (normalizar_cuenta, leer_catalogo, leer_catalogo_si_es_valido,
                               cuentas_acumulativas, validar_cuenta, advertencia_de_espejo,
                               catalogo_a_tabla)

EMPRESA = "EEA251205CR8"


def linea_de_cuenta(cuenta, nombre, mayor, agrupador, tipo="G", nivel="2"):
    """Arma una linea 'C  ...' con las MISMAS posiciones que el cuentas.txt real."""
    return ("C  " + cuenta.ljust(31) + nombre.ljust(51) + "".ljust(51) + mayor.ljust(31)
            + f"{tipo} 0 {nivel} 0 20260213 11    1    0 0    0  0 {agrupador}")


@pytest.fixture
def archivo_catalogo(tmp_path):
    lineas = [
        "F  10200000",   # encabezado: se ignora
        linea_de_cuenta("60000000", "Gastos", "00000000", "600", nivel="3"),
        linea_de_cuenta("60300000", "Gastos de administracion", "60000000", "603", nivel="1"),
        linea_de_cuenta("60350000", "Telefono, internet", "60300000", "603.50"),
        linea_de_cuenta("60040001", "Telmex", "60040000", "601.50"),
        linea_de_cuenta("60450000", "Telefono fabricacion", "60400000", "604.48"),
        linea_de_cuenta("50010000", "Materiales de obra", "50000000", "501"),
        linea_de_cuenta("20101000", "Proveedores nacionales", "20100000", "201.01"),
        linea_de_cuenta("20101999", "Proveedores Varios", "20101000", "201.01"),
        "R  algo que no es cuenta",
    ]
    ruta = tmp_path / "cuentas.txt"
    ruta.write_text("\r\n".join(lineas) + "\r\n", encoding="latin1")
    return str(ruta)


def reglas_de(archivo, retiradas=()):
    catalogo = leer_catalogo(archivo)
    return catalogo, cuentas_acumulativas(catalogo), list(retiradas)


# --- Lectura del archivo de ancho fijo --------------------------------------
def test_normalizar_cuenta_quita_guiones_y_espacios():
    assert normalizar_cuenta("603-50-000") == "60350000" and normalizar_cuenta(" 60350000 ") == "60350000"


def test_leer_catalogo_solo_toma_lineas_de_cuenta_y_sus_campos(archivo_catalogo):
    catalogo = leer_catalogo(archivo_catalogo)
    assert set(catalogo) == {"60000000", "60300000", "60350000", "60040001", "60450000", "50010000",
                             "20101000", "20101999"}
    assert catalogo["60350000"] == {"nombre": "Telefono, internet", "cuenta_mayor": "60300000",
                                    "tipo": "G", "nivel": "2", "agrupador": "603.50"}


def test_archivo_que_no_es_un_catalogo_se_rechaza(tmp_path):
    malo = tmp_path / "otro.txt"
    malo.write_text("cuenta\tnombre\n60350000\tTelefono\n", encoding="latin1")
    with pytest.raises(ValueError):
        leer_catalogo(str(malo))
    catalogo, mensaje = leer_catalogo_si_es_valido(str(malo))
    assert catalogo is None and "no es un cuentas.txt" in mensaje


def test_catalogo_faltante_devuelve_mensaje_no_error():
    catalogo, mensaje = leer_catalogo_si_es_valido("C:/no/existe/cuentas.txt")
    assert catalogo is None and "No se encontro" in mensaje


# --- Validacion de cuentas --------------------------------------------------
def test_cuenta_valida_pasa(archivo_catalogo):
    catalogo, acumulativas, retiradas = reglas_de(archivo_catalogo)
    assert validar_cuenta("603-50-000", catalogo, acumulativas, retiradas) is None


def test_cuenta_inexistente_se_rechaza(archivo_catalogo):
    catalogo, acumulativas, retiradas = reglas_de(archivo_catalogo)
    assert validar_cuenta("99999999", catalogo, acumulativas, retiradas)[0] == "NO_EXISTE"


def test_cuenta_acumulativa_se_rechaza(archivo_catalogo):
    catalogo, acumulativas, retiradas = reglas_de(archivo_catalogo)
    assert validar_cuenta("60300000", catalogo, acumulativas, retiradas)[0] == "ACUMULATIVA"
    assert validar_cuenta("60000000", catalogo, acumulativas, retiradas)[0] == "ACUMULATIVA"


def test_cuenta_retirada_se_rechaza_aunque_este_en_el_catalogo(archivo_catalogo):
    catalogo, acumulativas, retiradas = reglas_de(archivo_catalogo, retiradas=["60040001"])
    assert validar_cuenta("60040001", catalogo, acumulativas, retiradas)[0] == "RETIRADA"
    assert validar_cuenta("60040001", catalogo, acumulativas, [])  is None   # sin la lista, pasa


def test_agrupador_de_nivel_1_se_rechaza(archivo_catalogo):
    catalogo, acumulativas, retiradas = reglas_de(archivo_catalogo)
    assert validar_cuenta("50010000", catalogo, acumulativas, retiradas)[0] == "AGRUPADOR_NIVEL_1"


def test_espejo_es_solo_una_advertencia_y_no_bloquea(archivo_catalogo):
    catalogo, acumulativas, retiradas = reglas_de(archivo_catalogo)
    assert advertencia_de_espejo("60350000", catalogo) is None           # 603.50 espeja 603-50
    assert "604.48" in advertencia_de_espejo("60450000", catalogo)       # cuenta legitima que no espeja
    assert validar_cuenta("60450000", catalogo, acumulativas, retiradas) is None   # y NO se rechaza


# --- Integracion con las reglas --------------------------------------------
def fila_compra(cuenta, uuid="U1", tipo="I"):
    return {"uuid": uuid, "tipo": tipo, "cuenta": cuenta, "rfc_emisor": "TME840315KT6",
            "fecha": "2026-08-14T10:00:00", "metodo_pago": "PPD", "estado_sat": "VIGENTE",
            "serie": "", "folio": "F1", "total": 100.0, "forma_pago": ""}


@pytest.fixture
def carpeta_aislada(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db.init_db(EMPRESA)
    return tmp_path


def correr_reglas(filas, catalogo, config=None):
    colector = ColectorDeExcepciones()
    config = {"cuentas_default": {}, **(config or {})}
    aplicar_reglas(filas, config, colector, empresa_rfc=EMPRESA, tipo_operacion="egresos", catalogo=catalogo)
    return colector


def test_cuenta_principal_invalida_queda_pendiente_con_excepcion_bloqueante(carpeta_aislada, archivo_catalogo):
    filas = [fila_compra("60040001")]
    colector = correr_reglas(filas, leer_catalogo(archivo_catalogo), {"cuentas_retiradas": ["60040001"]})
    assert filas[0]["cuenta"] == "PENDIENTE" and filas[0]["cuenta_rechazada"] == "60040001"
    invalidas = [e for e in colector.todas() if e.codigo == "CUENTA_INVALIDA"]
    assert len(invalidas) == 1 and invalidas[0].severidad == "bloqueante"
    assert "retiradas" in invalidas[0].mensaje


def test_cuenta_principal_valida_no_se_toca(carpeta_aislada, archivo_catalogo):
    filas = [fila_compra("60350000")]
    colector = correr_reglas(filas, leer_catalogo(archivo_catalogo))
    assert filas[0]["cuenta"] == "60350000" and "cuenta_rechazada" not in filas[0]
    assert not [e for e in colector.todas() if e.codigo == "CUENTA_INVALIDA"]


def test_cuenta_de_tercero_mal_capturada_tambien_se_rechaza(carpeta_aislada, archivo_catalogo):
    db.ensure_alias(EMPRESA, "TME840315KT6", "TELMEX", "TELMEX", tipo="P")
    db.set_alias_cuenta(EMPRESA, "TME840315KT6", "99999999")
    filas = [fila_compra("60350000")]
    colector = correr_reglas(filas, leer_catalogo(archivo_catalogo))
    assert filas[0]["cuenta_tercero"] == "PENDIENTE"
    assert any("cuenta_tercero" in e.mensaje for e in colector.todas() if e.codigo == "CUENTA_INVALIDA")


def test_el_espejo_solo_avisa_cuando_la_empresa_lo_pide(carpeta_aislada, archivo_catalogo):
    catalogo = leer_catalogo(archivo_catalogo)
    sin_pedir = correr_reglas([fila_compra("60450000")], catalogo)
    pidiendo = correr_reglas([fila_compra("60450000")], catalogo, {"catalogo_espejo_agrupador": True})
    assert "CUENTA_FUERA_DE_ESPEJO" not in [e.codigo for e in sin_pedir.todas()]
    assert "CUENTA_FUERA_DE_ESPEJO" in [e.codigo for e in pidiendo.todas()]


def test_sin_catalogo_se_avisa_que_no_se_valido(carpeta_aislada):
    filas = [fila_compra("60040001")]
    colector = correr_reglas(filas, None)
    assert filas[0]["cuenta"] == "60040001"   # no se toca
    assert "CATALOGO_NO_DISPONIBLE" in [e.codigo for e in colector.todas()]


def test_cuentas_de_las_lineas_de_un_rep_tambien_se_validan(carpeta_aislada, archivo_catalogo):
    import json
    rep = {"uuid": "REP1", "tipo": "P", "cuenta": "10201001", "rfc_emisor": "CFE370814QI0", "fecha": "2026-08-02T00:00:00",
           "estado_sat": "VIGENTE", "total": 100.0, "serie": "", "folio": "",
           "pagos_json": json.dumps([{"fecha_pago": "2026-08-02T00:00:00", "forma_pago": "03", "monto": 100.0,
                                      "documentos": [{"id_documento": "DOC", "imp_pagado": 100.0, "imp_saldo_insoluto": 0}]}])}
    db.ensure_alias(EMPRESA, "CFE370814QI0", "CFE", "CFE", tipo="P")
    db.set_alias_cuenta(EMPRESA, "CFE370814QI0", "99999999")
    correr_reglas([rep], leer_catalogo(archivo_catalogo))
    assert json.loads(rep["aplicaciones_pago"])[0]["cuenta"] == "PENDIENTE"


# --- Base de datos: cuenta de gasto fija y limpieza de la IA ----------------
def test_cuenta_de_gasto_fija_por_proveedor(carpeta_aislada):
    db.ensure_alias(EMPRESA, "TME840315KT6", "TELMEX", "TELMEX", tipo="P")
    db.set_alias_cuenta_gasto(EMPRESA, "TME840315KT6", "603-50-000".replace("-", ""))
    assert db.get_cuentas_gasto(EMPRESA) == {"TME840315KT6": "60350000"}


def test_la_ia_olvida_lo_que_aprendio_hacia_una_cuenta_rechazada(carpeta_aislada):
    db.upsert_etiqueta(EMPRESA, "u1", "60040001", "")
    db.upsert_etiqueta(EMPRESA, "u2", "600-40-001", "")   # mismo numero escrito con guiones
    db.upsert_etiqueta(EMPRESA, "u3", "60350000", "")
    assert db.borrar_etiquetas_de_cuentas(EMPRESA, {"60040001"}) == 2
    conn = db.get_conn(EMPRESA)
    restantes = [r[0] for r in conn.execute("SELECT uuid FROM etiquetas")]
    conn.close()
    assert restantes == ["u3"]
    assert db.borrar_etiquetas_de_cuentas(EMPRESA, set()) == 0


def test_main_prefiere_la_cuenta_de_gasto_fija_a_la_ia(carpeta_aislada, monkeypatch):
    import main
    monkeypatch.setattr(main, "validar", lambda *a: "VIGENTE")
    monkeypatch.setattr(main, "predict", lambda *a: "60040001")   # la IA propone la cuenta retirada
    fila = {"uuid": "u1", "tipo": "I", "rfc_emisor": "TME840315KT6", "rfc_receptor": EMPRESA, "total": 1.0,
            "concepto": "Servicio", "nombre_emisor": "Telmex", "cp": "45000", "fecha": "2026-08-14T00:00:00",
            "nombre_receptor": "ECA", "subtotal": 1.0, "iva_16": 0.0}
    log = {"nominas": 0, "pagos": 0, "cancelados": 0}
    con_alias = main.clasificar_y_validar_filas([dict(fila)], "egresos", EMPRESA, None, {}, log,
                                                {"TME840315KT6": "60350000"})
    sin_alias = main.clasificar_y_validar_filas([dict(fila)], "egresos", EMPRESA, None, {}, log, {})
    assert con_alias[0]["cuenta"] == "60350000"
    assert sin_alias[0]["cuenta"] == "60040001"   # sin alias manda la IA (luego las reglas la rechazan)


# --- Aceptacion con TU catalogo real ----------------------------------------
CATALOGO_REAL = os.path.join(RAIZ_REPO, "stuff", "cuentas.txt")
requiere_catalogo_real = pytest.mark.skipif(not os.path.exists(CATALOGO_REAL),
                                            reason="Falta stuff/cuentas.txt (catalogo real de EEA)")


@requiere_catalogo_real
def test_aceptacion_catalogo_real_de_eea():
    catalogo = leer_catalogo(CATALOGO_REAL)
    acumulativas = cuentas_acumulativas(catalogo)
    retiradas = ["60040001"]
    veredicto = lambda cuenta: (validar_cuenta(cuenta, catalogo, acumulativas, retiradas) or ("OK",))[0]

    assert veredicto("60350000") == "OK"            # 603-50-000 Telefono, internet
    assert veredicto("60326000") == "OK"            # 603-26-000 Cuotas al IMSS
    assert veredicto("20101002") == "OK"            # 201-01-002 CFE (cuenta nueva)
    assert veredicto("20501002") == "OK"            # 205-01-002 Reembolsos socio (cuenta nueva)
    assert veredicto("20101999") == "OK" and veredicto("10201001") == "OK"
    assert veredicto("60040001") == "RETIRADA"      # Telmex viejo
    assert veredicto("60000000") == "ACUMULATIVA"   # la cuenta "general" es un mayor
    assert veredicto("60300000") == "ACUMULATIVA"
    assert veredicto("50010000") == "AGRUPADOR_NIVEL_1"
    assert veredicto("12345678") == "NO_EXISTE"
    assert advertencia_de_espejo("60040001", catalogo) is not None   # 601.50 vs 600.40


@requiere_catalogo_real
def test_aceptacion_la_tabla_del_catalogo_sirve_a_las_sugerencias_y_a_validar_cuenta_vs_sat():
    import pandas as pd
    from config import validar_cuenta_vs_sat
    tabla = pd.DataFrame(catalogo_a_tabla(leer_catalogo(CATALOGO_REAL)),
                         columns=["cuenta", "nombre", "cuenta_mayor", "tipo", "nivel", "agrupador"])
    assert validar_cuenta_vs_sat("603-50-000", tabla).startswith("OK")
    assert validar_cuenta_vs_sat("99999999", tabla).startswith("⚠️")


# --- Aceptacion de agosto: Telmex con alias de gasto vs IA que propone la cuenta vieja ---
BOVEDA = os.environ.get("BOVEDA_CFDI", "")
AGOSTO = os.path.join(BOVEDA, EMPRESA, "Recibidas", "2026", "08")
requiere_todo = pytest.mark.skipif(
    not (BOVEDA and os.path.isdir(AGOSTO) and os.path.exists(CATALOGO_REAL)),
    reason="Requiere BOVEDA_CFDI y stuff/cuentas.txt")


@requiere_todo
def test_aceptacion_agosto_telmex_va_a_603_50_y_la_cuenta_vieja_se_rechaza(carpeta_aislada, monkeypatch):
    import main
    from xml_processor import load_folder
    monkeypatch.setattr(main, "validar", lambda *a: "VIGENTE")
    monkeypatch.setattr(main, "predict", lambda *a: "60040001")   # la IA sigue creyendo en la cuenta vieja
    db.ensure_alias(EMPRESA, "TME840315KT6", "TELMEX", "TELMEX", tipo="P")
    db.set_alias_cuenta_gasto(EMPRESA, "TME840315KT6", "60350000")
    config = {"cuentas_default": {"bancos": "10201001", "gastos_generales": "60000000"},
              "cuentas_retiradas": ["60040001"], "catalogo_espejo_agrupador": True}

    filas = main.clasificar_y_validar_filas(load_folder(AGOSTO), "egresos", EMPRESA, None,
                                            config["cuentas_default"],
                                            {"nominas": 0, "pagos": 0, "cancelados": 0},
                                            db.get_cuentas_gasto(EMPRESA))
    colector = ColectorDeExcepciones()
    aplicar_reglas(filas, config, colector, empresa_rfc=EMPRESA, tipo_operacion="egresos",
                   catalogo=leer_catalogo(CATALOGO_REAL))
    por = {f["uuid"][:8].lower(): f for f in filas}

    assert por["d66001ab"]["cuenta"] == "60350000"            # Telmex: la cuenta fija le gana a la IA
    assert "cuenta_rechazada" not in por["d66001ab"]
    # El IMSS no tiene cuenta fija: manda la IA, que propone la cuenta vieja -> queda PENDIENTE y bloqueada.
    assert por["e7e5db0a"]["cuenta"] == "PENDIENTE" and por["e7e5db0a"]["cuenta_rechazada"] == "60040001"
    assert any(e.uuid == por["e7e5db0a"]["uuid"] and e.severidad == "bloqueante" for e in colector.todas())
