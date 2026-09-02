"""
Pruebas de la Fase 3: fecha de la poliza (caso C) y forma de pago (caso B).

Las pruebas puras usan datos inventados; la de aceptacion usa tus XML reales de
agosto 2026 (requiere BOVEDA_CFDI, igual que las de las fases anteriores).
"""
import os
import sys
import json

import pytest

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

from excepciones import ColectorDeExcepciones
from fecha_de_poliza import (extraer_datos_folio_imss, decidir_fecha_poliza,
                             avisar_si_el_pago_es_de_otro_periodo, avisar_saldo_insoluto)
from formas_de_pago import (forma_de_pago_de_la_fila, necesita_contrapartida,
                            decidir_contrapartida, CUENTA_PENDIENTE)

IMSS = {"IMS421231I45"}
BANCO = "10201001"
FORMAS_EEA = {"04": {"cuenta": "20501002", "tipo_poliza": "Diario"},
              "28": {"cuenta": "20501002", "tipo_poliza": "Diario"}}


def pagos_json(fecha="2026-08-03T00:01:00", forma="04", extra=None):
    pagos = [{"fecha_pago": fecha, "forma_pago": forma, "monto": 388.99,
              "documentos": [{"id_documento": "ABC", "imp_pagado": 388.99, "imp_saldo_insoluto": 0.0}]}]
    return json.dumps(pagos + (extra or []))


def rep(fecha="2026-08-03T00:01:00", forma="04", emision="2026-08-05T01:39:10", extra=None, total=388.99):
    return {"uuid": "REP1", "tipo": "P", "fecha": emision, "total": total,
            "pagos_json": pagos_json(fecha, forma, extra)}


def factura_imss(serie="A", folio="202607-H6729812105-06082026-349460", emision="2026-08-12T13:48:09"):
    return {"uuid": "IMSS1", "tipo": "I", "metodo_pago": "PUE", "forma_pago": "03",
            "rfc_emisor": "IMS421231I45", "serie": serie, "folio": folio, "fecha": emision,
            "concepto": "Cuotas obrero patronales", "total": 2108.78}


# --- Caso C: fecha de poliza ------------------------------------------------
def test_rep_usa_la_fecha_de_pago_no_la_de_emision():
    assert decidir_fecha_poliza(rep(), IMSS, ColectorDeExcepciones()) == "2026-08-03"


def test_factura_normal_usa_la_fecha_de_emision():
    fila = {"uuid": "F1", "tipo": "I", "rfc_emisor": "TME840315KT6", "fecha": "2026-08-14T23:50:00"}
    assert decidir_fecha_poliza(fila, IMSS, ColectorDeExcepciones()) == "2026-08-14"


def test_folio_del_imss_trae_fecha_de_pago_y_linea_sipare():
    datos = extraer_datos_folio_imss("A", "202607-H6729812105-06082026-349460")
    assert datos == {"fecha_pago": "2026-08-06", "periodo_cuota": "2026-07", "linea_sipare": "349460"}


def test_folio_que_no_es_del_imss_o_con_fecha_imposible_no_se_interpreta():
    assert extraer_datos_folio_imss("", "PP347188") is None
    assert extraer_datos_folio_imss("A", "202607-H6729812105-31022026-349460") is None


def test_poliza_del_imss_usa_su_fecha_de_pago_y_expone_la_linea_sipare():
    fila = factura_imss()
    assert decidir_fecha_poliza(fila, IMSS, ColectorDeExcepciones()) == "2026-08-06"
    assert fila["concepto"].startswith("Cuotas IMSS 2026-07 SIPARE 349460")


def test_folio_ilegible_del_imss_usa_emision_y_avisa():
    colector = ColectorDeExcepciones()
    fecha = decidir_fecha_poliza(factura_imss(folio="RARO"), IMSS, colector)
    assert fecha == "2026-08-12"
    assert colector.todas()[0].codigo == "FOLIO_IMSS_ILEGIBLE"


def test_infonavit_no_se_toca_aunque_tambien_sea_cuota():
    fila = {"uuid": "I1", "tipo": "I", "rfc_emisor": "INF7205011ZA", "serie": "", "folio": "PP347188",
            "fecha": "2026-08-07T19:17:09"}
    colector = ColectorDeExcepciones()
    assert decidir_fecha_poliza(fila, IMSS, colector) == "2026-08-07"
    assert colector.cuantas() == 0


def test_rep_con_pagos_de_distinta_fecha_es_bloqueante():
    extra = [{"fecha_pago": "2026-08-20T00:00:00", "forma_pago": "03", "monto": 10, "documentos": []}]
    colector = ColectorDeExcepciones()
    decidir_fecha_poliza(rep(extra=extra), IMSS, colector)
    assert [(e.codigo, e.severidad) for e in colector.todas()] == [("REP_CON_VARIOS_PAGOS", "bloqueante")]


def test_pago_de_un_mes_anterior_avisa():
    colector = ColectorDeExcepciones()
    avisar_si_el_pago_es_de_otro_periodo({"uuid": "X", "fecha_poliza": "2026-07-30"}, "2026-08", colector)
    avisar_si_el_pago_es_de_otro_periodo({"uuid": "Y", "fecha_poliza": "2026-08-03"}, "2026-08", colector)
    assert [e.uuid for e in colector.todas()] == ["X"]


def test_saldo_insoluto_positivo_avisa_y_cero_no():
    colector = ColectorDeExcepciones()
    avisar_saldo_insoluto(rep(), colector)
    assert colector.cuantas() == 0
    parcial = rep()
    parcial["pagos_json"] = parcial["pagos_json"].replace('"imp_saldo_insoluto": 0.0', '"imp_saldo_insoluto": 50.5')
    avisar_saldo_insoluto(parcial, colector)
    assert [e.codigo for e in colector.todas()] == ["SALDO_INSOLUTO"]


# --- Caso B: forma de pago --------------------------------------------------
def test_tarjeta_del_socio_va_a_la_cuenta_del_socio_y_la_poliza_es_diario():
    fila, colector = rep(forma="04"), ColectorDeExcepciones()
    decidir_contrapartida(fila, FORMAS_EEA, BANCO, colector)
    assert fila["cuenta_contrapartida"] == "20501002" and fila["tipo_poliza"] == "Diario"
    assert [e.codigo for e in colector.todas()] == ["FORMA_PAGO_ADVERTIDA"]


def test_transferencia_va_a_banco_en_egreso_sin_excepciones():
    fila, colector = rep(forma="03"), ColectorDeExcepciones()
    decidir_contrapartida(fila, FORMAS_EEA, BANCO, colector)
    assert fila["cuenta_contrapartida"] == BANCO and fila["tipo_poliza"] == "Egreso"
    assert colector.cuantas() == 0


def test_forma_por_definir_va_a_banco_pero_avisa():
    fila, colector = rep(forma="99"), ColectorDeExcepciones()
    decidir_contrapartida(fila, FORMAS_EEA, BANCO, colector)
    assert fila["cuenta_contrapartida"] == BANCO
    assert [e.codigo for e in colector.todas()] == ["FORMA_PAGO_ADVERTIDA"]


def test_forma_sin_mapeo_deja_la_contrapartida_pendiente_y_bloquea():
    fila, colector = rep(forma="01"), ColectorDeExcepciones()
    decidir_contrapartida(fila, FORMAS_EEA, BANCO, colector)
    assert fila["cuenta_contrapartida"] == CUENTA_PENDIENTE
    assert [(e.codigo, e.severidad) for e in colector.todas()] == [("FORMA_PAGO_SIN_MAPEO", "bloqueante")]


def test_el_mapa_de_la_empresa_gana_sobre_los_valores_por_defecto():
    fila = rep(forma="03")
    decidir_contrapartida(fila, {"03": {"cuenta": "10201002", "tipo_poliza": "Egreso"}}, BANCO, ColectorDeExcepciones())
    assert fila["cuenta_contrapartida"] == "10201002"


def test_tarjeta_mayor_a_2000_agrega_la_nota_del_requisito_de_deduccion():
    colector = ColectorDeExcepciones()
    decidir_contrapartida(rep(forma="04", total=2500.0), FORMAS_EEA, BANCO, colector)
    assert "LISR 27" in colector.todas()[0].mensaje


def test_forma_de_pago_se_lee_del_rep_o_de_la_factura_y_solo_pue_y_rep_mueven_dinero():
    assert forma_de_pago_de_la_fila(rep(forma="04")) == "04"
    assert forma_de_pago_de_la_fila(factura_imss()) == "03"
    assert necesita_contrapartida(rep()) and necesita_contrapartida(factura_imss())
    assert not necesita_contrapartida({"tipo": "I", "metodo_pago": "PPD"})
    assert not necesita_contrapartida({"tipo": "E", "metodo_pago": "PUE"})


# --- Generacion de polizas con lo decidido ----------------------------------
def test_poliza_del_rep_en_diario_contra_la_cuenta_del_socio_y_con_fecha_de_pago(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.chdir(tmp_path)
    from export import generar_polizas
    df = pd.DataFrame([{
        "uuid": "REP1", "tipo": "P", "metodo_pago": "PPD", "concepto": "REP", "referencia": "X",
        "rfc_emisor": "TME840315KT6", "nombre_emisor": "Telmex", "rfc_receptor": "EEA251205CR8",
        "nombre_receptor": "ECA", "fecha": "2026-08-05T01:39:10", "cuenta": "10201001", "total": 388.99,
        "iva_16": 53.65, "iva_8": 0.0, "ret_isr": 0.0, "ret_iva": 0.0, "ieps": 0.0, "subtotal": 0.0,
        "departamento": "General", "cuenta_tercero": "20101999",
        "fecha_poliza": "2026-08-03", "tipo_poliza": "Diario", "cuenta_contrapartida": "20501002"}])
    polizas = generar_polizas(df, is_egresos=True)
    assert set(polizas["Tipo"]) == {"Diario"} and set(polizas["Fecha"]) == {"2026-08-03"}
    assert (polizas["Cuenta"] == "20501002").any() and not (polizas["Cuenta"] == "10201001").any()
    assert round(polizas["Debe"].sum(), 2) == round(polizas["Haber"].sum(), 2)


def test_el_orden_de_las_polizas_sigue_la_fecha_de_pago(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.chdir(tmp_path)
    from export import ordenar_por_fecha
    df = pd.DataFrame([
        {"uuid": "A", "fecha": "2026-08-05T00:00:00", "fecha_poliza": "2026-08-03"},
        {"uuid": "B", "fecha": "2026-08-02T00:00:00", "fecha_poliza": "2026-08-10"}])
    assert list(ordenar_por_fecha(df)["uuid"]) == ["A", "B"]


# --- Aceptacion con los XML reales de agosto 2026 ---------------------------
BOVEDA = os.environ.get("BOVEDA_CFDI", "")
AGOSTO = os.path.join(BOVEDA, "EEA251205CR8", "Recibidas", "2026", "08")
requiere_xml_reales = pytest.mark.skipif(
    not (BOVEDA and os.path.isdir(AGOSTO)), reason="Define BOVEDA_CFDI para la aceptacion con XML reales")


@requiere_xml_reales
def test_aceptacion_agosto_fechas_y_contrapartidas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import db, registro_contable
    from xml_processor import load_folder
    from reglas_contables import aplicar_reglas
    db.init_db("EEA251205CR8")
    registro_contable.crear_tablas("EEA251205CR8")
    filas = load_folder(AGOSTO)
    for f in filas:
        f["estado_sat"] = "VIGENTE"
    config = {"cuentas_default": {"bancos": BANCO}, "formas_pago": FORMAS_EEA,
              "rfcs_con_fecha_en_folio": ["IMS421231I45"]}
    aplicar_reglas(filas, config, ColectorDeExcepciones(), empresa_rfc="EEA251205CR8", tipo_operacion="egresos")
    por = {f["uuid"][:8].lower(): f for f in filas}

    assert por["4295eff7"]["fecha_poliza"] == "2026-08-02"           # REP CFE (transferencia)
    assert por["4295eff7"]["cuenta_contrapartida"] == BANCO and por["4295eff7"]["tipo_poliza"] == "Egreso"
    assert por["fad179f3"]["fecha_poliza"] == "2026-08-03"           # REP Telmex: pago 03/08, emitido 05/08
    assert por["fad179f3"]["cuenta_contrapartida"] == "20501002" and por["fad179f3"]["tipo_poliza"] == "Diario"
    assert por["e7e5db0a"]["fecha_poliza"] == "2026-08-06"           # IMSS: fecha de pago en el folio
    assert "SIPARE 349460" in por["e7e5db0a"]["concepto"]
    assert por["d66001ab"]["fecha_poliza"] == "2026-08-14"           # factura PPD de Telmex: emision
    assert "cuenta_contrapartida" not in por["d66001ab"]            # PPD no mueve dinero
