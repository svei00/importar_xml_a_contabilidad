"""
polizas_para_txt.py - Decide QUE polizas entran al TXT de CONTPAQi y cuales se quedan fuera.

Problema (bug de la auditoria): antes, si una poliza tenia una cuenta PENDIENTE, el
TXT se escribia SIN esa linea y la poliza llegaba descuadrada a CONTPAQi, que la
rechaza o crea una "cuenta de cuadre". Ahora una poliza queda FUERA del TXT completa
(aparece en el Excel, marcada) cuando:
  * alguna de sus lineas tiene una cuenta sin asignar (PENDIENTE, vacia, 0...), o
  * su CFDI tiene una excepcion BLOQUEANTE (algo que Svei debe decidir primero).

Sin Tkinter ni archivos: recibe tablas de pandas y devuelve decisiones.
"""
import pandas as pd

ESTADO_EN_TXT = "Si"
ESTADO_BLOQUEADA = "No: excepcion bloqueante"
ESTADO_CUENTA_PENDIENTE = "No: cuenta sin asignar"

_SIN_CUENTA = ("PENDIENTE", "NAN", "0", "")


def cuenta_sin_asignar(cuenta):
    """True si la cuenta no sirve para escribirla en el TXT (pendiente, vacia, texto raro)."""
    texto = str(cuenta).strip().upper()
    if texto in _SIN_CUENTA or "FALTA" in texto:
        return True
    return not texto.replace("-", "").isdigit()


def numeros_con_cuenta_sin_asignar(polizas_df):
    """Numeros de poliza que tienen al menos una linea con la cuenta sin asignar."""
    mascara = polizas_df["Cuenta"].apply(cuenta_sin_asignar)
    return set(polizas_df.loc[mascara, "Numero"])


def numeros_de_polizas_bloqueadas(polizas_df, uuids_bloqueados):
    """Numeros de poliza cuyo UUID tiene una excepcion bloqueante."""
    bloqueados = {str(u).strip().upper() for u in uuids_bloqueados if str(u).strip()}
    uuids = polizas_df["UUID"].astype(str).str.strip().str.upper()
    return set(polizas_df.loc[uuids.isin(bloqueados), "Numero"])


def estado_de_cada_poliza(polizas_df, uuids_bloqueados):
    """{numero: texto} con 'Si' o el motivo por el que la poliza NO entra al TXT."""
    bloqueadas = numeros_de_polizas_bloqueadas(polizas_df, uuids_bloqueados)
    pendientes = numeros_con_cuenta_sin_asignar(polizas_df)
    estados = {}
    for numero in polizas_df["Numero"].unique():
        if numero in bloqueadas:
            estados[numero] = ESTADO_BLOQUEADA
        elif numero in pendientes:
            estados[numero] = ESTADO_CUENTA_PENDIENTE
        else:
            estados[numero] = ESTADO_EN_TXT
    return estados


def numeros_que_no_entran(polizas_df, uuids_bloqueados):
    """Numeros de poliza que se quedan fuera del TXT (por cualquiera de los dos motivos)."""
    return {n for n, estado in estado_de_cada_poliza(polizas_df, uuids_bloqueados).items()
            if estado != ESTADO_EN_TXT}


def agregar_columna_en_txt(polizas_df, uuids_bloqueados):
    """Copia de la tabla con la columna 'EnTXT' (Si / No: motivo) para que Svei lo vea en el Excel."""
    copia = polizas_df.copy()
    estados = estado_de_cada_poliza(copia, uuids_bloqueados)
    copia["EnTXT"] = copia["Numero"].map(estados)
    return copia
