"""
Pruebas de la Fase 1 (cimientos y aviso de mes vacio).

Las pruebas "puras" usan datos inventados. La prueba de aceptacion usa los XML
REALES de agosto 2026 y solo corre si existe la variable de entorno BOVEDA_CFDI
(ejemplo: C:\\AdminXML\\BovedaCFDI). Los XML reales NUNCA se suben al repo.
"""
import os
import sys
import json
import xml.etree.ElementTree as ET

import pytest

# Permite importar los modulos que viven en la raiz del repo.
RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

from texto_contpaqi import a_ascii
from periodo_lote import determinar_periodo, filas_fuera_de_periodo, separar_anio_mes
from excepciones import ColectorDeExcepciones, BLOQUEANTE, INFORMATIVA
from reglas_contables import aplicar_reglas
from resumen_corrida import desglose_corrida, hay_algo_que_contabilizar, redactar_aviso_mes_vacio
from xml_processor import extraer_pagos


def fila(uuid, tipo="I", fecha="2026-08-10T10:00:00", estado="VIGENTE"):
    """Fila minima de CFDI para las pruebas."""
    return {"uuid": uuid, "tipo": tipo, "fecha": fecha, "estado_sat": estado}


# --- Regla H: ASCII ---------------------------------------------------------
def test_a_ascii_quita_acentos_y_enie():
    assert a_ascii("Reclasificación Muñoz") == "Reclasificacion Munoz"


def test_a_ascii_conserva_texto_ya_ascii():
    assert a_ascii("IVA acreditable 16%") == "IVA acreditable 16%"


def test_a_ascii_reemplaza_guion_largo_y_elimina_simbolos_raros():
    assert a_ascii("Pago – Telmex ✓") == "Pago - Telmex "


# --- Periodo del lote -------------------------------------------------------
def test_periodo_es_el_mes_mas_frecuente_no_el_del_primer_xml():
    filas = [fila("a", fecha="2026-07-15T00:00:00"),
             fila("b", fecha="2026-08-02T00:00:00"),
             fila("c", fecha="2026-08-05T00:00:00")]
    assert determinar_periodo(filas) == "2026-08"


def test_periodo_empate_gana_el_mes_mas_reciente():
    filas = [fila("a", fecha="2026-07-15T00:00:00"), fila("b", fecha="2026-08-02T00:00:00")]
    assert determinar_periodo(filas) == "2026-08"


def test_periodo_vacio_si_ninguna_fecha_sirve():
    assert determinar_periodo([fila("a", fecha=""), fila("b", fecha=None)]) == ""


def test_filas_fuera_de_periodo_lista_los_de_otro_mes():
    filas = [fila("a", fecha="2026-07-15T00:00:00"), fila("b", fecha="2026-08-02T00:00:00")]
    assert filas_fuera_de_periodo(filas, "2026-08") == [("a", "2026-07")]


def test_separar_anio_mes():
    assert separar_anio_mes("2026-08") == ("2026", "08")


# --- Reglas: cancelados y nomina -------------------------------------------
def test_cancelado_se_omite_y_se_registra_excepcion():
    colector = ColectorDeExcepciones()
    filas = [fila("x1", estado="CANCELADO"), fila("x2")]
    aplicar_reglas(filas, {}, colector)
    assert filas[0]["omitir"] is True and filas[0]["motivo_omision"] == "cancelado"
    assert filas[1]["omitir"] is False
    assert [e.codigo for e in colector.todas()] == ["CANCELADO"]


def test_nomina_se_omite_en_modo_contpaqi_por_defecto():
    filas = [fila("n1", tipo="N")]
    aplicar_reglas(filas, {}, ColectorDeExcepciones())
    assert filas[0]["omitir"] is True and filas[0]["motivo_omision"] == "nomina"


def test_nomina_se_conserva_en_modo_xml():
    filas = [fila("n1", tipo="N")]
    aplicar_reglas(filas, {"nomina_modo": "xml"}, ColectorDeExcepciones())
    assert filas[0]["omitir"] is False


def test_estatus_sat_desconocido_se_contabiliza_pero_se_avisa():
    colector = ColectorDeExcepciones()
    filas = [fila("e1", estado="ERROR")]
    aplicar_reglas(filas, {}, colector)
    assert filas[0]["omitir"] is False
    assert colector.todas()[0].codigo == "ESTATUS_SAT_DESCONOCIDO"
    assert colector.todas()[0].severidad == INFORMATIVA


def test_fuera_de_periodo_avisa_sin_omitir():
    colector = ColectorDeExcepciones()
    filas = [fila("a", fecha="2026-07-15T00:00:00"),
             fila("b", fecha="2026-08-02T00:00:00"),
             fila("c", fecha="2026-08-03T00:00:00")]
    aplicar_reglas(filas, {}, colector)
    assert not filas[0]["omitir"]
    assert [e.codigo for e in colector.todas()] == ["FUERA_DE_PERIODO"]


def test_colector_separa_bloqueantes():
    colector = ColectorDeExcepciones()
    colector.agregar("A", INFORMATIVA, "u1", "info")
    colector.agregar("B", BLOQUEANTE, "u2", "stop")
    assert [e.codigo for e in colector.bloqueantes()] == ["B"]
    assert colector.por_uuid("u2")[0].mensaje == "stop"


# --- Regla I: mes vacio -----------------------------------------------------
def test_ocho_nominas_no_hay_nada_que_contabilizar():
    filas = [fila(f"n{i}", tipo="N") for i in range(8)]
    aplicar_reglas(filas, {}, ColectorDeExcepciones())
    desglose = desglose_corrida(filas)
    assert desglose["nomina"] == 8 and desglose["total_xml"] == 8
    assert not hay_algo_que_contabilizar(desglose)


def test_aviso_de_mes_vacio_menciona_el_desglose():
    filas = [fila(f"n{i}", tipo="N") for i in range(8)]
    aplicar_reglas(filas, {}, ColectorDeExcepciones())
    titulo, mensaje = redactar_aviso_mes_vacio("EEA251205CR8", "2026-08", "ingresos", desglose_corrida(filas))
    assert "Sin ingresos que contabilizar" in titulo and "08/2026" in titulo
    assert "8 XML" in mensaje and "8 nomina" in mensaje
    assert "No se generó archivo de pólizas." in mensaje


def test_una_factura_si_hay_que_contabilizar():
    filas = [fila("f1"), fila("n1", tipo="N")]
    aplicar_reglas(filas, {}, ColectorDeExcepciones())
    assert hay_algo_que_contabilizar(desglose_corrida(filas))


# --- Parser: datos del REP --------------------------------------------------
XML_REP = """<Root xmlns:pago20="http://www.sat.gob.mx/Pagos20">
  <Complemento><pago20:Pagos>
    <pago20:Pago FechaPago="2026-08-03T00:01:00" FormaDePagoP="04" Monto="388.99">
      <pago20:DoctoRelacionado IdDocumento="UUID-ORIGINAL" Serie="CFDI" Folio="00"
         ImpPagado="388.99" ImpSaldoInsoluto="0.00"/>
    </pago20:Pago>
  </pago20:Pagos></Complemento>
</Root>"""


def test_extraer_pagos_lee_fecha_forma_y_documentos():
    pagos = extraer_pagos(ET.fromstring(XML_REP))
    assert len(pagos) == 1
    assert pagos[0]["fecha_pago"] == "2026-08-03T00:01:00"
    assert pagos[0]["forma_pago"] == "04"
    assert pagos[0]["documentos"][0]["id_documento"] == "UUID-ORIGINAL"
    assert pagos[0]["documentos"][0]["imp_pagado"] == 388.99
    json.dumps(pagos)  # debe poder guardarse como JSON en la hoja BASE


# --- Aceptacion con los XML REALES de agosto 2026 ---------------------------
BOVEDA = os.environ.get("BOVEDA_CFDI", "")
EMPRESA = "EEA251205CR8"
CARPETA_EMITIDAS = os.path.join(BOVEDA, EMPRESA, "Emitidas", "2026", "08")
CARPETA_RECIBIDAS = os.path.join(BOVEDA, EMPRESA, "Recibidas", "2026", "08")

requiere_xml_reales = pytest.mark.skipif(
    not (BOVEDA and os.path.isdir(CARPETA_EMITIDAS) and os.path.isdir(CARPETA_RECIBIDAS)),
    reason="Define BOVEDA_CFDI para correr la prueba de aceptacion con XML reales")


def _cargar_sin_sat(carpeta):
    """Carga los XML reales y simula que el SAT los marco VIGENTE (sin red)."""
    from xml_processor import load_folder
    filas = load_folder(carpeta)
    for f in filas:
        f["estado_sat"] = "VIGENTE"
    return filas


@requiere_xml_reales
def test_aceptacion_emitidas_agosto_son_8_nominas_y_no_se_genera_nada():
    filas = _cargar_sin_sat(CARPETA_EMITIDAS)
    periodo = aplicar_reglas(filas, {"nomina_modo": "contpaqi"}, ColectorDeExcepciones())
    desglose = desglose_corrida(filas)
    assert periodo == "2026-08"
    assert desglose["total_xml"] == 8 and desglose["nomina"] == 8
    assert not hay_algo_que_contabilizar(desglose)


@requiere_xml_reales
def test_aceptacion_recibidas_agosto_5_cfdi_contabilizables_y_datos_nuevos():
    filas = _cargar_sin_sat(CARPETA_RECIBIDAS)
    periodo = aplicar_reglas(filas, {}, ColectorDeExcepciones())
    desglose = desglose_corrida(filas)
    assert periodo == "2026-08"
    assert desglose["contabilizables"] == 5
    assert desglose["pagos_rep"] == 2 and desglose["facturas"] == 3
    # Los REP traen su FechaPago y forma de pago reales (casos B y C).
    reps = {f["uuid"][:8].lower(): json.loads(f["pagos_json"]) for f in filas if f["tipo"] == "P"}
    assert reps["fad179f3"][0]["fecha_pago"].startswith("2026-08-03")
    assert reps["fad179f3"][0]["forma_pago"] == "04"
    assert reps["4295eff7"][0]["fecha_pago"].startswith("2026-08-02")
    # Serie y folio ya viajan en cada fila (los usa la deteccion de reexpediciones).
    infonavit = [f for f in filas if f["rfc_emisor"] == "INF7205011ZA"][0]
    assert infonavit["folio"] == "PP347188"
