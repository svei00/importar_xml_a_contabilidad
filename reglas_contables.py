"""
reglas_contables.py - Orquestador de las reglas contables (corre ANTES de armar polizas).

Principio rector del proyecto: separar DECIDIR de ESCRIBIR.
  - Aqui se DECIDE (que filas se omiten, a que periodo pertenece cada una...).
  - export.generar_polizas solo ESCRIBE los asientos con lo ya decidido.

Cada fila (diccionario de un CFDI) sale de aqui con estas columnas nuevas:
  periodo          'AAAA-MM' propio del CFDI
  omitir           True si NO debe generar poliza ni DIOT
  motivo_omision   'cancelado' | 'nomina' | ''   (por que se omitio)

Fase 1 implementa: cancelados (B-11), nomina en modo CONTPAQi, periodo del lote
y estatus SAT desconocido. Las fases siguientes agregan sus reglas en
aplicar_reglas(), una despues de otra.

Sin Tkinter ni ventanas: solo datos adentro, datos afuera.
"""
import excepciones as exc
from periodo_lote import periodo_de_fecha, determinar_periodo, filas_fuera_de_periodo

MOTIVO_CANCELADO = "cancelado"
MOTIVO_NOMINA = "nomina"


def _marcar_cancelado(fila, colector):
    """Regla B-11: un CFDI cancelado NO entra a polizas ni a DIOT."""
    fila["omitir"] = True
    fila["motivo_omision"] = MOTIVO_CANCELADO
    colector.agregar(
        exc.CANCELADO, exc.INFORMATIVA, fila.get("uuid", ""),
        "CFDI cancelado en el SAT: se excluyo de polizas y DIOT.",
        "Si es un error, confirma el estatus en el portal del SAT y vuelve a correr el mes.")


def _marcar_nomina_si_corresponde(fila, config_empresa):
    """
    Con nomina_modo = 'contpaqi' (default) la poliza de nomina la hace CONTPAQi
    Nominas; esta app no la duplica. Con 'xml' si la arma.
    """
    modo = str(config_empresa.get("nomina_modo", "contpaqi")).lower()
    if fila.get("tipo") == "N" and modo != "xml":
        fila["omitir"] = True
        fila["motivo_omision"] = MOTIVO_NOMINA


def _avisar_estatus_desconocido(fila, colector):
    """Si el SAT no respondio, el CFDI se contabiliza pero se avisa."""
    if fila.get("estado_sat") in ("ERROR", "DESCONOCIDO"):
        colector.agregar(
            exc.ESTATUS_SAT_DESCONOCIDO, exc.INFORMATIVA, fila.get("uuid", ""),
            f"No se pudo confirmar el estatus en el SAT ({fila.get('estado_sat')}).",
            "Revisa manualmente que el CFDI siga vigente.")


def _avisar_fuera_de_periodo(filas, periodo, colector):
    """Avisa (sin omitir) los CFDI cuyo mes de emision no es el del lote."""
    for uuid, periodo_propio in filas_fuera_de_periodo(filas, periodo):
        colector.agregar(
            exc.FUERA_DE_PERIODO, exc.INFORMATIVA, uuid,
            f"Emitido en {periodo_propio}, pero el lote es de {periodo}.",
            "Verifica que corresponda a este mes; podria ser una reexpedicion.")


def aplicar_reglas(filas, config_empresa, colector):
    """
    Aplica, en orden, las reglas de decision a TODAS las filas (modifica los
    diccionarios en su lugar) y devuelve el periodo del lote ('AAAA-MM').
    """
    periodo_lote = determinar_periodo(filas)

    for fila in filas:
        fila["periodo"] = periodo_de_fecha(fila.get("fecha"))
        fila["omitir"] = False
        fila["motivo_omision"] = ""

        if fila.get("estado_sat") == "CANCELADO":
            _marcar_cancelado(fila, colector)
            continue

        _marcar_nomina_si_corresponde(fila, config_empresa)
        _avisar_estatus_desconocido(fila, colector)

    _avisar_fuera_de_periodo(filas, periodo_lote, colector)
    return periodo_lote
