"""
balanza_contpaqi.py - Lee la BALANZA DE COMPROBACION que Svei exporta de CONTPAQi.

La necesita la regla F (cuotas del IMSS/INFONAVIT): antes de cargar un pago a la
cuenta de pasivo ("IMSS por pagar") hay que saber si esa cuenta tiene saldo que
cancelar. Esa informacion solo esta en la balanza (la app no tiene acceso al
SQL de CONTPAQi).

Formato (verificado el 2026-10-08 con Balanza de Comprobacion 07-2026.xlsx y
08-2026.xlsx): Excel exportado de CONTPAQi, UNA hoja, 8 columnas (base 0):
    0 cuenta con guiones '211-01-000'      1 nombre
    2 saldo inicial deudor                 3 saldo inicial acreedor
    4 cargos                               5 abonos
    6 saldo actual deudor                  7 saldo actual acreedor
La fila 1 dice 'Balanza de comprobacion al 31/Jul/2026' (fecha de corte). Las
filas de datos son las que traen una cuenta con la forma NNN-NN-NNN; las dos
filas finales ('Sumas Iguales') no la traen y se ignoran.

Sin Tkinter: solo lee el archivo y contesta preguntas.
"""
import re
import warnings
import datetime
import pandas as pd

from catalogo_contpaqi import normalizar_cuenta

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
         "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}

_PATRON_CUENTA_CON_GUIONES = re.compile(r"^\d{3}-\d{2}-\d{3}$")
_PATRON_FECHA_DE_CORTE = re.compile(r"al\s+(\d{1,2})/([A-Za-z]{3})/(\d{4})")

COLUMNAS_DE_SALDOS = {2: "inicial_deudor", 3: "inicial_acreedor", 4: "cargos",
                      5: "abonos", 6: "actual_deudor", 7: "actual_acreedor"}


def _numero(valor):
    """Una celda de saldo como numero; las celdas vacias valen 0."""
    try:
        return 0.0 if pd.isna(valor) else float(valor)
    except (TypeError, ValueError):
        return 0.0


def _fecha_de_corte(tabla):
    """Busca 'al 31/Jul/2026' en las primeras filas del archivo; None si no aparece."""
    for texto in tabla.iloc[:6, 0].astype(str):
        coincidencia = _PATRON_FECHA_DE_CORTE.search(texto)
        if coincidencia:
            mes = MESES.get(coincidencia.group(2).lower())
            if mes:
                return datetime.date(int(coincidencia.group(3)), mes, int(coincidencia.group(1)))
    return None


def leer_balanza(ruta):
    """
    Devuelve {"fecha_corte": date | None, "cuentas": {cuenta: {columna: monto}}}.
    Lanza ValueError si el archivo no trae ninguna cuenta (no es una balanza).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # openpyxl se queja de que el Excel no trae estilo base: es inofensivo
        tabla = pd.read_excel(ruta, header=None)

    cuentas = {}
    for _, fila in tabla.iterrows():
        if not _PATRON_CUENTA_CON_GUIONES.match(str(fila[0]).strip()):
            continue
        cuentas[normalizar_cuenta(fila[0])] = {nombre: _numero(fila[indice])
                                               for indice, nombre in COLUMNAS_DE_SALDOS.items()}
    if not cuentas:
        raise ValueError("El archivo no trae cuentas con la forma NNN-NN-NNN: no es una balanza de CONTPAQi.")
    return {"fecha_corte": _fecha_de_corte(tabla), "cuentas": cuentas}


def saldo_acreedor(balanza, cuenta):
    """
    Saldo ACREEDOR actual de una cuenta de pasivo (acreedor - deudor). Una cuenta
    que no aparece en la balanza no tiene movimientos ni saldo: vale 0.
    """
    datos = balanza["cuentas"].get(normalizar_cuenta(cuenta))
    if datos is None:
        return 0.0
    return round(datos["actual_acreedor"] - datos["actual_deudor"], 2)


def fecha_de_cierre_del_mes_anterior(periodo):
    """'2026-08' -> 2026-07-31 (el ultimo dia del mes anterior)."""
    anio, mes = (int(parte) for parte in periodo.split("-"))
    return datetime.date(anio, mes, 1) - datetime.timedelta(days=1)


def es_cierre_del_mes_anterior(balanza, periodo):
    """True si la balanza esta cortada al ultimo dia del mes anterior al periodo."""
    return balanza["fecha_corte"] == fecha_de_cierre_del_mes_anterior(periodo)
