"""
periodo_lote.py - Decide a que MES pertenece una corrida.

Bug que corrige: antes el periodo salia de la fecha del PRIMER XML de la
carpeta. Si ese primer archivo era una reexpedicion de julio, todo el lote (y
su DIOT) quedaba bautizado como julio.

Regla nueva: el periodo del lote es el AAAA-MM mas frecuente entre las fechas
de emision. Si hay empate gana el mes mas reciente. Los XML de otro mes se
reportan como FUERA_DE_PERIODO (aviso, no error).
"""
from collections import Counter


def periodo_de_fecha(fecha_iso):
    """'2026-08-14T23:50:00' -> '2026-08'. Devuelve '' si la fecha no sirve."""
    texto = str(fecha_iso or "")
    if len(texto) >= 7 and texto[4] == "-":
        return texto[:7]
    return ""


def determinar_periodo(filas):
    """
    Recibe la lista de diccionarios (uno por CFDI) y devuelve el periodo del
    lote como 'AAAA-MM'. Devuelve '' si ninguna fila trae fecha valida.
    """
    conteo = Counter(periodo_de_fecha(f.get("fecha")) for f in filas)
    conteo.pop("", None)   # las fechas invalidas no votan
    if not conteo:
        return ""
    # max por (cuantas veces aparece, el mes mismo): en empate gana el mas reciente.
    return max(conteo, key=lambda periodo: (conteo[periodo], periodo))


def filas_fuera_de_periodo(filas, periodo):
    """Lista de (uuid, periodo_propio) de los CFDI cuyo mes no es el del lote."""
    fuera = []
    for fila in filas:
        propio = periodo_de_fecha(fila.get("fecha"))
        if propio and propio != periodo:
            fuera.append((fila.get("uuid", ""), propio))
    return fuera


def separar_anio_mes(periodo):
    """'2026-08' -> ('2026', '08')."""
    anio, mes = periodo.split("-")
    return anio, mes
