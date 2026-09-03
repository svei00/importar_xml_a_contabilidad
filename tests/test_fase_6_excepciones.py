"""
Pruebas de la Fase 6: que polizas entran al TXT, hoja MOVIMIENTOS_BANCO y textos de la
ventana de excepciones.

La ventana en si (Tkinter) se prueba a mano; aqui se prueba toda su logica.
"""
import os
import sys

import pandas as pd
import pytest

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_REPO)

import db
import registro_contable as registro
from excepciones import ColectorDeExcepciones, BLOQUEANTE, INFORMATIVA
from polizas_para_txt import (cuenta_sin_asignar, numeros_con_cuenta_sin_asignar,
                              estado_de_cada_poliza, numeros_que_no_entran, agregar_columna_en_txt)
from movimientos_banco import construir_movimientos_de_banco, es_cuenta_de_banco
from ventana_excepciones import (construir_texto_de_resumen, texto_del_boton_de_continuar,
                                 lineas_de_una_excepcion)

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"
UUID_C = "33333333-3333-3333-3333-333333333333"


def linea(numero, cuenta, debe, haber, uuid, fecha="2026-08-06", concepto="Concepto"):
    return {"Numero": numero, "Tipo": "Egreso", "Fecha": fecha, "Cuenta": cuenta, "Referencia": "REF",
            "Debe": debe, "Haber": haber, "Concepto": concepto, "UUID": uuid}


@pytest.fixture
def polizas():
    """Poliza 1 sana, poliza 2 con cuenta PENDIENTE, poliza 3 sana pero con UUID bloqueado."""
    return pd.DataFrame([
        linea(1, "60326000", 100.0, 0.0, UUID_A), linea(1, "10201001", 0.0, 100.0, UUID_A),
        linea(2, "PENDIENTE", 50.0, 0.0, UUID_B), linea(2, "10201001", 0.0, 50.0, UUID_B),
        linea(3, "60350000", 30.0, 0.0, UUID_C, fecha="2026-08-07"),
        linea(3, "10201001", 0.0, 30.0, UUID_C, fecha="2026-08-07"),
    ])


# --- Excepciones: agrupar ---------------------------------------------------
def test_colector_separa_uuids_bloqueados_y_agrupa_por_severidad():
    colector = ColectorDeExcepciones()
    colector.agregar("A", BLOQUEANTE, UUID_A, "m")
    colector.agregar("B", INFORMATIVA, UUID_B, "m")
    colector.agregar("C", BLOQUEANTE, "", "del lote")        # sin UUID: no bloquea a ninguna poliza en particular
    assert colector.uuids_bloqueados() == {UUID_A}
    agrupadas = colector.por_severidad()
    assert [e.codigo for e in agrupadas[BLOQUEANTE]] == ["A", "C"]
    assert [e.codigo for e in agrupadas[INFORMATIVA]] == ["B"]


# --- Que polizas entran al TXT ---------------------------------------------
def test_cuenta_sin_asignar():
    for mala in ("PENDIENTE", "", "nan", "0", "FALTA CUENTA", "abc"):
        assert cuenta_sin_asignar(mala)
    assert not cuenta_sin_asignar("60350000") and not cuenta_sin_asignar("603-50-000")


def test_poliza_con_cuenta_pendiente_queda_fuera(polizas):
    assert numeros_con_cuenta_sin_asignar(polizas) == {2}


def test_estado_de_cada_poliza(polizas):
    estados = estado_de_cada_poliza(polizas, {UUID_C})
    assert estados == {1: "Si", 2: "No: cuenta sin asignar", 3: "No: excepcion bloqueante"}
    assert numeros_que_no_entran(polizas, {UUID_C}) == {2, 3}
    assert numeros_que_no_entran(polizas, set()) == {2}


def test_la_columna_en_txt_se_agrega_sin_alterar_la_tabla_original(polizas):
    con_columna = agregar_columna_en_txt(polizas, {UUID_C})
    assert "EnTXT" not in polizas.columns
    assert list(con_columna["EnTXT"].unique()) == ["Si", "No: cuenta sin asignar", "No: excepcion bloqueante"]


def test_el_uuid_bloqueado_se_compara_sin_importar_mayusculas(polizas):
    assert numeros_que_no_entran(polizas, {UUID_A.lower()}) >= {1}


# --- El TXT ----------------------------------------------------------------
def escribir_txt(polizas, tmp_path, excluidos=None):
    from export import exportar_txt_contpaqi
    ruta = exportar_txt_contpaqi(polizas, str(tmp_path), "Polizas_EGRESOS_EEA251205CR8_2026_08.xlsx", excluidos)
    with open(ruta, encoding="windows-1252") as archivo:
        return archivo.read().splitlines()


def test_txt_omite_la_poliza_con_cuenta_pendiente_completa(polizas, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lineas = escribir_txt(polizas, tmp_path)
    cabeceras = [l for l in lineas if l.startswith("P ")]
    assert len(cabeceras) == 2                       # entran la 1 y la 3; la 2 (PENDIENTE) NO
    movimientos = [l for l in lineas if l.startswith("M1")]
    assert len(movimientos) == 4                      # 2 lineas por poliza, ninguna huerfana
    assert not any("PENDIENTE" in l for l in lineas)


def test_txt_omite_las_polizas_excluidas_por_excepcion_bloqueante(polizas, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lineas = escribir_txt(polizas, tmp_path, excluidos={3})
    assert len([l for l in lineas if l.startswith("P ")]) == 1   # solo la 1
    assert not any("60350000" in l for l in lineas)


def test_cada_poliza_que_entra_al_txt_cuadra(polizas, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lineas = escribir_txt(polizas, tmp_path)
    cargos = sum(float(l[3 + 31 + 31 + 2:].split()[0]) for l in lineas if l.startswith("M1") and l[3 + 31 + 31] == "0")
    abonos = sum(float(l[3 + 31 + 31 + 2:].split()[0]) for l in lineas if l.startswith("M1") and l[3 + 31 + 31] == "1")
    assert round(cargos, 2) == round(abonos, 2) == 130.0


# --- Hoja MOVIMIENTOS_BANCO -------------------------------------------------
def test_cuentas_de_banco():
    assert es_cuenta_de_banco("10201001") and es_cuenta_de_banco("102-02-001")
    assert not es_cuenta_de_banco("60350000")


def test_movimientos_de_banco_agrupa_por_dia_y_suma(polizas):
    extra = pd.DataFrame([linea(4, "60326000", 246.0, 0.0, UUID_A, fecha="2026-08-06"),
                          linea(4, "10201001", 0.0, 246.0, UUID_A, fecha="2026-08-06")])
    movimientos = construir_movimientos_de_banco(pd.concat([polizas, extra]), numeros_excluidos={2})
    dia_6 = movimientos[movimientos["Fecha"] == "2026-08-06"]
    detalle, total = dia_6.iloc[:-1], dia_6.iloc[-1]
    assert len(detalle) == 2                         # poliza 1 y poliza 4; la 2 (excluida) no aparece
    assert total["Concepto"].startswith("TOTAL DEL DIA") and total["Abono"] == 346.0 and total["Cargo"] == 0.0
    assert "neto -346.00" in total["Concepto"]


def test_movimientos_de_banco_vacio_si_no_hay_banco():
    solo_gasto = pd.DataFrame([linea(1, "60350000", 10.0, 0.0, UUID_A)])
    assert construir_movimientos_de_banco(solo_gasto).empty


# --- Textos de la ventana ---------------------------------------------------
def test_resumen_de_la_ventana():
    assert "3 de 5" in construir_texto_de_resumen(5, 2) and "FUERA del TXT" in construir_texto_de_resumen(5, 2)
    assert construir_texto_de_resumen(4, 0).startswith("Las 4 polizas se generaran")
    assert texto_del_boton_de_continuar(True) == "Generar TXT sin las bloqueadas"
    assert texto_del_boton_de_continuar(False) == "Generar archivos"


def test_lineas_de_una_excepcion():
    colector = ColectorDeExcepciones()
    colector.agregar("CUENTA_INVALIDA", BLOQUEANTE, UUID_A, "La cuenta X no sirve", "Corrigela")
    colector.agregar("REEXPEDICION", INFORMATIVA, "", "mensaje solo")
    con_sugerencia, sin_sugerencia = (lineas_de_una_excepcion(e) for e in colector.todas())
    assert con_sugerencia[0][0].startswith("CUENTA_INVALIDA  (11111111)")
    assert [etiqueta for _, etiqueta in con_sugerencia] == ["titulo", "mensaje", "sugerencia"]
    assert [etiqueta for _, etiqueta in sin_sugerencia] == ["titulo", "mensaje"]


# --- Registro: una poliza bloqueada no cuenta como contabilizada ------------
def test_poliza_bloqueada_se_registra_como_bloqueada_y_no_cuenta_para_duplicados(tmp_path, monkeypatch):
    from registrar_corrida import registrar_lote
    monkeypatch.chdir(tmp_path)
    db.init_db("EEA251205CR8")
    filas = [{"uuid": UUID_A, "tipo": "I", "fecha": "2026-08-06T10:00:00", "omitir": False, "total": 1.0,
              "rfc_emisor": "X", "rfc_receptor": "EEA251205CR8", "llave_negocio": "X||1|1.00"},
             {"uuid": UUID_B, "tipo": "I", "fecha": "2026-08-07T10:00:00", "omitir": False, "total": 2.0,
              "rfc_emisor": "X", "rfc_receptor": "EEA251205CR8", "llave_negocio": "X||2|2.00"}]
    registrar_lote("EEA251205CR8", "egresos", "2026-08", "c", filas, registro.ESTADO_VIGENTE,
                   uuids_bloqueados={UUID_A})
    conn = db.get_conn("EEA251205CR8")
    resultados = dict(conn.execute("SELECT uuid, resultado FROM documentos_contabilizados").fetchall())
    conn.close()
    assert resultados == {UUID_A: "bloqueado", UUID_B: "contabilizado"}
    # Desde septiembre, el bloqueado NO se considera ya contabilizado (nunca llego a CONTPAQi).
    assert registro.buscar_documento_por_uuid("EEA251205CR8", UUID_A, "egresos", "2026-09") is None
    assert registro.buscar_documento_por_uuid("EEA251205CR8", UUID_B, "egresos", "2026-09") is not None


# --- exportar completo: Excel + TXT -----------------------------------------
def test_exportar_deja_fuera_la_poliza_bloqueada_y_marca_el_excel(tmp_path, monkeypatch):
    import export
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(export, "cargar_catalogo", lambda: None)
    (tmp_path / "settings.json").write_text('{"cuentas_default": {"bancos": "10201001"}}', encoding="utf-8")

    def cfdi(uuid, cuenta, fecha):
        return {"uuid": uuid, "tipo": "I", "metodo_pago": "PUE", "concepto": "Servicio", "referencia": "F1",
                "rfc_emisor": "AAA010101AAA", "nombre_emisor": "Proveedor", "rfc_receptor": "EEA251205CR8",
                "nombre_receptor": "ECA", "fecha": fecha, "cuenta": cuenta, "total": 116.0, "iva_16": 16.0,
                "iva_8": 0.0, "ret_isr": 0.0, "ret_iva": 0.0, "ieps": 0.0, "subtotal": 100.0,
                "departamento": "General", "estado_sat": "VIGENTE"}

    df = pd.DataFrame([cfdi(UUID_A, "60350000", "2026-08-06T10:00:00"),
                       cfdi(UUID_C, "60326000", "2026-08-07T10:00:00")])
    colector = ColectorDeExcepciones()
    colector.agregar("CUENTA_INVALIDA", BLOQUEANTE, UUID_C, "bloqueada a proposito")

    ruta = export.exportar(df, None, str(tmp_path), "Polizas_EGRESOS_EEA251205CR8_2026_08.xlsx",
                           {"total": 2}, colector)
    hojas = pd.ExcelFile(ruta)
    assert {"POLIZAS_CONTPAQI", "EXCEPCIONES", "MOVIMIENTOS_BANCO"} <= set(hojas.sheet_names)
    polizas = pd.read_excel(hojas, "POLIZAS_CONTPAQI")
    assert set(polizas.loc[polizas["UUID"] == UUID_A, "EnTXT"]) == {"Si"}
    assert set(polizas.loc[polizas["UUID"] == UUID_C, "EnTXT"]) == {"No: excepcion bloqueante"}

    txt = (tmp_path / "Polizas_CONTPAQi_Polizas_EGRESOS_EEA251205CR8_2026_08.txt").read_text(encoding="windows-1252")
    assert UUID_A.upper() in txt and UUID_C.upper() not in txt
    movimientos = pd.read_excel(hojas, "MOVIMIENTOS_BANCO")
    assert UUID_C not in set(movimientos["UUID"])
