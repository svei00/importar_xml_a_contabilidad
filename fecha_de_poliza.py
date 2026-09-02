"""
fecha_de_poliza.py - Caso C: la fecha de la poliza es la del PAGO, no la de emision.

Reglas:
  * REP (complemento de pago): fecha de poliza = FechaPago del REP. Nunca la de
    emision ni la de timbrado. Ejemplo real: el REP de Telmex se emitio el 05/08
    pero el pago fue el 03/08.
  * CFDI del IMSS: el folio trae embebida la fecha de pago y la linea SIPARE:
        A-AAAAMM-REGISTROPATRONAL-DDMMAAAA-LINEA
        A-202607-H6729812105-06082026-349460   (pago el 06/08/2026, linea 349460)
    La fecha de poliza es esa fecha de pago, y el concepto expone la linea SIPARE.
  * Todo lo demas: la fecha de emision (como siempre).

Sin base de datos ni ventanas: datos adentro, datos afuera.
"""
import re
import datetime
import excepciones as exc

# Patron del folio del IMSS (serie 'A' + '-' + folio). Los grupos tienen nombre
# para que el codigo se lea solo.
PATRON_FOLIO_IMSS = re.compile(
    r"^A-(?P<periodo_cuota>\d{6})-(?P<registro_patronal>[A-Z0-9]{11})"
    r"-(?P<fecha_pago>\d{8})-(?P<linea_sipare>\d+)$")


def _fecha_de_emision(fila):
    """'2026-08-14T23:50:00' -> '2026-08-14'."""
    return str(fila.get("fecha", ""))[:10]


def _solo_fecha(texto):
    """'2026-08-03T00:01:00' -> '2026-08-03'."""
    return str(texto or "")[:10]


def extraer_datos_folio_imss(serie, folio):
    """
    Si serie+folio tienen la forma del IMSS devuelve un diccionario con
    fecha_pago (AAAA-MM-DD), periodo_cuota (AAAA-MM) y linea_sipare; si no, None.
    """
    texto = f"{str(serie or '').strip()}-{str(folio or '').strip()}".upper()
    coincidencia = PATRON_FOLIO_IMSS.match(texto)
    if coincidencia is None:
        return None
    try:
        fecha = datetime.datetime.strptime(coincidencia["fecha_pago"], "%d%m%Y").date()
    except ValueError:
        return None   # 8 digitos pero no es una fecha real (p.ej. 31022026)
    periodo = coincidencia["periodo_cuota"]
    return {"fecha_pago": fecha.isoformat(),
            "periodo_cuota": f"{periodo[:4]}-{periodo[4:]}",
            "linea_sipare": coincidencia["linea_sipare"]}


def leer_pagos_del_rep(fila):
    """Los pagos del REP vienen como texto JSON en pagos_json (los deja el parser)."""
    import json
    try:
        return json.loads(fila.get("pagos_json") or "[]")
    except (TypeError, ValueError):
        return []


def _fecha_de_pago_del_rep(fila, colector):
    """FechaPago del REP; si trae varios pagos distintos se avisa (bloqueante)."""
    pagos = leer_pagos_del_rep(fila)
    if not pagos:
        return _fecha_de_emision(fila)
    distintos = {(_solo_fecha(p.get("fecha_pago")), p.get("forma_pago")) for p in pagos}
    if len(distintos) > 1:
        colector.agregar(
            exc.REP_CON_VARIOS_PAGOS, exc.BLOQUEANTE, fila.get("uuid", ""),
            "El REP trae varios pagos con distinta fecha o forma de pago; una sola poliza no puede representarlos.",
            "Decide a mano como registrarlo (una poliza por pago).")
    return _solo_fecha(pagos[0].get("fecha_pago")) or _fecha_de_emision(fila)


def _fecha_del_folio_imss(fila, colector):
    """Fecha de pago embebida en el folio del IMSS; si no se puede leer, la de emision."""
    datos = extraer_datos_folio_imss(fila.get("serie"), fila.get("folio"))
    if datos is None:
        colector.agregar(
            exc.FOLIO_IMSS_ILEGIBLE, exc.INFORMATIVA, fila.get("uuid", ""),
            f"El folio '{fila.get('serie', '')}-{fila.get('folio', '')}' del IMSS no tiene la forma "
            "A-AAAAMM-REGPATRONAL-DDMMAAAA-LINEA: se uso la fecha de emision.",
            "Verifica la fecha real de pago en el comprobante SIPARE.")
        return _fecha_de_emision(fila)
    fila["concepto"] = f"Cuotas IMSS {datos['periodo_cuota']} SIPARE {datos['linea_sipare']} - {fila.get('concepto', '')}"
    return datos["fecha_pago"]


def decidir_fecha_poliza(fila, rfcs_con_fecha_en_folio, colector):
    """Devuelve la fecha de poliza (AAAA-MM-DD) de una fila segun el tipo de comprobante."""
    if fila.get("tipo") == "P":
        return _fecha_de_pago_del_rep(fila, colector)
    emisor = str(fila.get("rfc_emisor", "")).strip().upper()
    if fila.get("tipo") == "I" and emisor in rfcs_con_fecha_en_folio:
        return _fecha_del_folio_imss(fila, colector)
    return _fecha_de_emision(fila)


def avisar_si_el_pago_es_de_otro_periodo(fila, periodo_lote, colector):
    """Un pago de un mes anterior mueve el IVA y la DIOT de ESE mes, no del lote."""
    fecha = fila.get("fecha_poliza", "")
    if fecha and periodo_lote and fecha[:7] < periodo_lote:
        colector.agregar(
            exc.PAGO_DE_PERIODO_ANTERIOR, exc.INFORMATIVA, fila.get("uuid", ""),
            f"La fecha de poliza ({fecha}) es de un mes anterior al lote ({periodo_lote}).",
            "Ese IVA y esa DIOT corresponden al mes del pago.")


def avisar_saldo_insoluto(fila, colector):
    """Si el REP deja saldo pendiente en alguna factura se avisa (pago parcial)."""
    for pago in leer_pagos_del_rep(fila):
        for doc in pago.get("documentos", []):
            if float(doc.get("imp_saldo_insoluto", 0) or 0) > 0:
                colector.agregar(
                    exc.SALDO_INSOLUTO, exc.INFORMATIVA, fila.get("uuid", ""),
                    f"El pago de {str(doc.get('id_documento', ''))[:8]} deja saldo insoluto "
                    f"{doc['imp_saldo_insoluto']:.2f} (pago parcial).",
                    "La factura sigue abierta en la cuenta del proveedor.")
