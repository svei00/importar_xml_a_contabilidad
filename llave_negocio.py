"""
llave_negocio.py - La "huella" de un comprobante, independiente de su UUID.

Problema (caso D): el mismo pago puede llegar timbrado varias veces, cada una con
un UUID distinto (reexpedicion). Ejemplo real: INFONAVIT folio PP347188, mismo
emisor, mismo importe 495.86, tres UUID. Comparar solo UUID no lo detecta.

La llave de negocio es:  RFC_EMISOR | SERIE | FOLIO | TOTAL
Ejemplo:                 INF7205011ZA||PP347188|495.86
"""


def _mayusculas_sin_espacios(texto):
    """'  pp 3471 88 ' -> 'PP347188'."""
    return "".join(str(texto or "").split()).upper()


def construir_llave(rfc_emisor, serie, folio, total):
    """Arma la llave de negocio con todos sus datos normalizados."""
    rfc = _mayusculas_sin_espacios(rfc_emisor)
    serie_limpia = _mayusculas_sin_espacios(serie)
    folio_limpio = _mayusculas_sin_espacios(folio)
    try:
        total_texto = f"{float(total):.2f}"
    except (TypeError, ValueError):
        total_texto = "0.00"
    return f"{rfc}|{serie_limpia}|{folio_limpio}|{total_texto}"


def llave_es_utilizable(llave):
    """
    Una llave sin folio NI serie no identifica nada (muchos comprobantes no
    traen folio); compararlas produciria falsas reexpediciones.
    """
    partes = llave.split("|")
    return len(partes) == 4 and bool(partes[0]) and (bool(partes[1]) or bool(partes[2]))
