"""
Pruebas de la Fase 5 (caso F: pago de cuota sin provision) y de la ACEPTACION GLOBAL
de la Parte 1: las 4 polizas exactas de agosto 2026.

Las pruebas puras construyen balanzas pequenas en Excel. Las de aceptacion usan tus
archivos reales de la carpeta stuff/ (ignorada por git) y los XML de la boveda
(variable BOVEDA_CFDI); si faltan, se saltan.
"""
import os
import sys
import json
import datetime

import pytest
from openpyxl import Workbook

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

import db
from excepciones import ColectorDeExcepciones
from balanza_contpaqi import (leer_balanza, saldo_acreedor, es_cierre_del_mes_anterior,
                              fecha_de_cierre_del_mes_anterior)
from cuotas_patronales import aplicar_regla_de_cuotas, cuentas_por_rfc, es_pago_de_cuota
from reglas_contables import aplicar_reglas

EMPRESA = "EEA251205CR8"
CUOTAS = {"sin_balanza": "gasto_directo",
          "rfcs": {"IMS421231I45": {"cuenta_pasivo": "21101000", "cuenta_gasto": "60326000"},
                   "INF7205011ZA": {"cuenta_pasivo": "21103000", "cuenta_gasto": "60327000"}}}


def crear_balanza(tmp_path, cortes, filas):
    """Excel con el MISMO formato que exporta CONTPAQi. filas = [(cuenta, deudor, acreedor)] (saldos actuales)."""
    libro = Workbook()
    hoja = libro.active
    hoja.append(["CONTPAQ i", None, None, "Empresa de prueba", None, None, None, "Hoja: 1"])
    hoja.append([f"Balanza de comprobación al {cortes}", None, None, None, None, None, None, "Fecha: 08/Oct/2026"])
    for _ in range(5):
        hoja.append([None] * 8)
    for cuenta, deudor, acreedor in filas:
        hoja.append([cuenta, "Nombre", None, None, 0, 0, deudor, acreedor])
    hoja.append([None] * 8)
    hoja.append([None, "Sumas Iguales:", 1, None, 0, 0, 1, None])
    ruta = tmp_path / "balanza.xlsx"
    libro.save(ruta)
    return str(ruta)


def fila_imss(uuid="IMSS1", total=2108.78, fecha="2026-08-06", rfc="IMS421231I45"):
    return {"uuid": uuid, "tipo": "I", "metodo_pago": "PUE", "rfc_emisor": rfc, "total": total,
            "fecha_poliza": fecha, "fecha": fecha + "T10:00:00", "cuenta": "60000000", "omitir": False}


# --- Lectura de la balanza --------------------------------------------------
def test_leer_balanza_toma_fecha_de_corte_y_saldos(tmp_path):
    ruta = crear_balanza(tmp_path, "31/Jul/2026", [("211-01-000", None, 2040.75), ("102-01-001", 500.0, None)])
    balanza = leer_balanza(ruta)
    assert balanza["fecha_corte"] == datetime.date(2026, 7, 31)
    assert saldo_acreedor(balanza, "21101000") == 2040.75
    assert saldo_acreedor(balanza, "211-01-000") == 2040.75       # acepta guiones
    assert saldo_acreedor(balanza, "10201001") == -500.0          # deudor = saldo acreedor negativo
    assert saldo_acreedor(balanza, "99999999") == 0.0             # no aparece = sin saldo


def test_archivo_que_no_es_balanza_se_rechaza(tmp_path):
    libro = Workbook()
    libro.active.append(["hola", "mundo"])
    ruta = tmp_path / "otro.xlsx"
    libro.save(ruta)
    with pytest.raises(ValueError):
        leer_balanza(str(ruta))


def test_la_balanza_debe_ser_del_cierre_del_mes_anterior(tmp_path):
    julio = leer_balanza(crear_balanza(tmp_path, "31/Jul/2026", [("211-01-000", None, 1.0)]))
    assert es_cierre_del_mes_anterior(julio, "2026-08")
    assert not es_cierre_del_mes_anterior(julio, "2026-09")
    assert not es_cierre_del_mes_anterior(julio, "2026-07")


def test_cierre_del_mes_anterior_cruza_de_anio():
    assert fecha_de_cierre_del_mes_anterior("2027-01") == datetime.date(2026, 12, 31)


# --- Regla F ----------------------------------------------------------------
def balanza_con(tmp_path, acreedor_imss):
    return leer_balanza(crear_balanza(tmp_path, "31/Jul/2026", [("211-01-000", None, acreedor_imss)]))


def aplicar(filas, balanza, config=None):
    colector = ColectorDeExcepciones()
    aplicar_regla_de_cuotas(filas, {"cuotas_patronales": CUOTAS, **(config or {})}, balanza, colector)
    return colector


def test_sin_saldo_el_pago_va_directo_al_gasto_y_avisa(tmp_path):
    filas = [fila_imss()]
    colector = aplicar(filas, balanza_con(tmp_path, 0.0))
    assert filas[0]["cuenta"] == "60326000"
    assert [e.codigo for e in colector.todas()] == ["PASIVO_SIN_SALDO"]


def test_con_saldo_suficiente_cancela_la_provision(tmp_path):
    filas = [fila_imss(total=2108.78)]
    colector = aplicar(filas, balanza_con(tmp_path, 3000.0))
    assert filas[0]["cuenta"] == "21101000" and colector.cuantas() == 0


def test_saldo_exacto_tambien_cancela_la_provision(tmp_path):
    filas = [fila_imss(total=2108.78)]
    aplicar(filas, balanza_con(tmp_path, 2108.78))
    assert filas[0]["cuenta"] == "21101000"


def test_saldo_parcial_deja_la_poliza_pendiente_y_bloquea(tmp_path):
    filas = [fila_imss(total=2108.78)]
    colector = aplicar(filas, balanza_con(tmp_path, 1000.0))
    assert filas[0]["cuenta"] == "PENDIENTE"
    assert [(e.codigo, e.severidad) for e in colector.todas()] == [("PASIVO_SALDO_PARCIAL", "bloqueante")]


def test_el_segundo_pago_del_mes_ya_no_encuentra_la_provision_agotada(tmp_path):
    primero = fila_imss(uuid="A", total=1000.0, fecha="2026-08-05")
    segundo = fila_imss(uuid="B", total=1000.0, fecha="2026-08-20")
    aplicar([segundo, primero], balanza_con(tmp_path, 1000.0))   # se le pasa desordenado a proposito
    assert primero["cuenta"] == "21101000"      # el primero (05/08) cancela toda la provision
    assert segundo["cuenta"] == "60326000"      # al segundo ya no le queda nada: directo al gasto


def test_si_el_primer_pago_deja_solo_una_parte_el_segundo_queda_pendiente(tmp_path):
    primero = fila_imss(uuid="A", total=1000.0, fecha="2026-08-05")
    segundo = fila_imss(uuid="B", total=1000.0, fecha="2026-08-20")
    colector = aplicar([segundo, primero], balanza_con(tmp_path, 1200.0))
    assert primero["cuenta"] == "21101000"
    assert segundo["cuenta"] == "PENDIENTE"     # quedan 200 de 1,000: pago parcial, decide Svei
    assert [e.codigo for e in colector.todas()] == ["PASIVO_SALDO_PARCIAL"]


def test_sin_balanza_por_defecto_va_al_gasto_con_aviso():
    filas = [fila_imss()]
    colector = aplicar(filas, None)
    assert filas[0]["cuenta"] == "60326000"
    assert [(e.codigo, e.severidad) for e in colector.todas()] == [("BALANZA_NO_DISPONIBLE", "informativa")]


def test_sin_balanza_en_modo_pendiente_bloquea():
    filas = [fila_imss()]
    colector = aplicar(filas, None, {"cuotas_patronales": {**CUOTAS, "sin_balanza": "pendiente"}})
    assert filas[0]["cuenta"] == "PENDIENTE"
    assert colector.todas()[0].severidad == "bloqueante"


def test_infonavit_usa_sus_propias_cuentas(tmp_path):
    filas = [fila_imss(rfc="INF7205011ZA", total=495.86)]
    aplicar(filas, balanza_con(tmp_path, 0.0))
    assert filas[0]["cuenta"] == "60327000"


def test_lo_que_no_es_cuota_o_no_esta_pagado_no_se_toca(tmp_path):
    otro_emisor = fila_imss(rfc="TME840315KT6")
    ppd = dict(fila_imss(uuid="P"), metodo_pago="PPD")
    omitida = dict(fila_imss(uuid="O"), omitir=True)
    aplicar([otro_emisor, ppd, omitida], balanza_con(tmp_path, 0.0))
    assert otro_emisor["cuenta"] == ppd["cuenta"] == omitida["cuenta"] == "60000000"


def test_sin_configuracion_de_cuotas_no_hace_nada():
    filas = [fila_imss()]
    aplicar_regla_de_cuotas(filas, {}, None, ColectorDeExcepciones())
    assert filas[0]["cuenta"] == "60000000"
    assert cuentas_por_rfc({}) == {} and not es_pago_de_cuota(filas[0], {})


# --- Con tus archivos REALES de stuff/ --------------------------------------
STUFF = os.path.join(RAIZ_REPO, "stuff")
BALANZA_JULIO = os.path.join(STUFF, "Balanza de Comprobacion 07-2026.xlsx")
BALANZA_AGOSTO = os.path.join(STUFF, "Balanza de Comprobacion 08-2026.xlsx")
CATALOGO = os.path.join(STUFF, "cuentas.txt")
requiere_balanzas = pytest.mark.skipif(
    not (os.path.exists(BALANZA_JULIO) and os.path.exists(BALANZA_AGOSTO)),
    reason="Faltan las balanzas reales en stuff/")


@requiere_balanzas
def test_balanzas_reales_de_julio_y_agosto():
    julio, agosto = leer_balanza(BALANZA_JULIO), leer_balanza(BALANZA_AGOSTO)
    assert julio["fecha_corte"] == datetime.date(2026, 7, 31)
    assert agosto["fecha_corte"] == datetime.date(2026, 8, 31)
    assert saldo_acreedor(julio, "21101000") == 0.0          # IMSS por pagar cerro julio en cero
    assert saldo_acreedor(julio, "20101002") == 3907.87      # CFE: lo que se pago en agosto
    assert saldo_acreedor(agosto, "21101000") == 3129.15     # provision de agosto (CONTPAQi Nominas)
    assert es_cierre_del_mes_anterior(julio, "2026-08") and not es_cierre_del_mes_anterior(agosto, "2026-08")


# --- ACEPTACION GLOBAL de la Parte 1: las 4 polizas de agosto 2026 -----------
BOVEDA = os.environ.get("BOVEDA_CFDI", "")
JULIO_XML = os.path.join(BOVEDA, EMPRESA, "Recibidas", "2026", "07")
AGOSTO_XML = os.path.join(BOVEDA, EMPRESA, "Recibidas", "2026", "08")
requiere_todo = pytest.mark.skipif(
    not (BOVEDA and os.path.isdir(JULIO_XML) and os.path.isdir(AGOSTO_XML)
         and os.path.exists(BALANZA_JULIO) and os.path.exists(CATALOGO)),
    reason="Requiere BOVEDA_CFDI y los archivos reales de stuff/")


def poliza_como_tabla(polizas):
    """{numero: (fecha, tipo, {cuenta: debe}, {cuenta: haber})} para comparar contra la tabla objetivo."""
    tabla = {}
    for numero, grupo in polizas.groupby("Numero"):
        debe = {r["Cuenta"]: round(r["Debe"], 2) for _, r in grupo.iterrows() if r["Debe"] > 0}
        haber = {r["Cuenta"]: round(r["Haber"], 2) for _, r in grupo.iterrows() if r["Haber"] > 0}
        tabla[numero] = (grupo.iloc[0]["Fecha"], grupo.iloc[0]["Tipo"], debe, haber)
    return tabla


@requiere_todo
def test_aceptacion_global_las_4_polizas_exactas_de_agosto(tmp_path, monkeypatch):
    import pandas as pd
    import main
    from xml_processor import load_folder
    from catalogo_contpaqi import leer_catalogo
    from sembrar_historial import sembrar_desde_carpeta
    from export import ordenar_por_fecha, generar_polizas

    monkeypatch.chdir(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"cuentas_default": {"bancos": "10201001"}}), encoding="utf-8")
    monkeypatch.setattr(main, "validar", lambda *a: "VIGENTE")
    monkeypatch.setattr(main, "predict", lambda *a: "60040001")   # la IA sigue creyendo en la cuenta vieja de Telmex

    # Lo que Svei configura una sola vez: historial de julio, alias de CFE y de Telmex.
    db.init_db(EMPRESA)
    sembrar_desde_carpeta(JULIO_XML, "egresos")
    db.ensure_alias(EMPRESA, "CFE370814QI0", "COMISION FEDERAL DE ELECTRICIDAD", "CFE", tipo="P")
    db.set_alias_cuenta(EMPRESA, "CFE370814QI0", "20101002")
    db.ensure_alias(EMPRESA, "TME840315KT6", "TELEFONOS DE MEXICO", "TELMEX", tipo="P")
    db.set_alias_cuenta_gasto(EMPRESA, "TME840315KT6", "60350000")

    config = {"cuentas_default": {"bancos": "10201001"}, "cuentas_retiradas": ["60040001"],
              "formas_pago": {"04": {"cuenta": "20501002", "tipo_poliza": "Diario"}},
              "cuotas_patronales": CUOTAS, "rfcs_con_fecha_en_folio": ["IMS421231I45"]}

    filas = main.clasificar_y_validar_filas(load_folder(AGOSTO_XML), "egresos", EMPRESA, None,
                                            config["cuentas_default"],
                                            {"nominas": 0, "pagos": 0, "cancelados": 0},
                                            db.get_cuentas_gasto(EMPRESA))
    colector = ColectorDeExcepciones()
    aplicar_reglas(filas, config, colector, empresa_rfc=EMPRESA, tipo_operacion="egresos",
                   catalogo=leer_catalogo(CATALOGO), balanza=leer_balanza(BALANZA_JULIO))

    activos = pd.DataFrame([f for f in filas if not f["omitir"]])
    polizas = generar_polizas(ordenar_por_fecha(activos), is_egresos=True)
    tabla = list(poliza_como_tabla(polizas).values())

    assert tabla == [
        ("2026-08-02", "Egreso", {"20101002": 3907.00, "11801000": 538.98},
                                 {"10201001": 3907.00, "11901000": 538.98}),
        ("2026-08-03", "Diario", {"20101999": 388.99, "11801000": 53.65},
                                 {"20501002": 388.99, "11901000": 53.65}),
        ("2026-08-06", "Egreso", {"60326000": 2108.78}, {"10201001": 2108.78}),
        ("2026-08-14", "Diario", {"60350000": 335.34, "11901000": 53.65}, {"20101999": 388.99}),
    ]
    # Ninguna de INFONAVIT, y nada bloqueante en pie.
    assert "fac86dcb" not in [f["uuid"][:8].lower() for f in filas if not f["omitir"]]
    assert colector.bloqueantes() == []
    assert round(polizas["Debe"].sum(), 2) == round(polizas["Haber"].sum(), 2)
