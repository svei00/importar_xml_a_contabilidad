"""
catalogo_contpaqi.py - Lee el cuentas.txt de CONTPAQi y valida cuentas (caso E).

Problema: la app leia cuentas.txt como si fuera CSV con tabuladores, pero es de
ANCHO FIJO, asi que cualquier cuenta salia "no en catalogo". Ademas nadie
revisaba que la cuenta elegida (por el modelo de IA o por un mapeo viejo) fuera
una cuenta valida para registrar movimientos.

Formato (verificado el 2026-10-08 sobre el cuentas.txt real; indices base 0):
  linea[0:3]     'C  ' = cuenta   (otras letras: F = encabezado, R = rubro; se ignoran)
  linea[3:34]    numero de cuenta          '60350000'
  linea[34:85]   nombre en espanol
  linea[85:136]  nombre en ingles
  linea[136:167] cuenta de mayor (la cuenta "padre")
  linea[167:]    campos separados por espacios: tipo, bandera, nivel, ... y el
                 ULTIMO es el codigo agrupador del SAT ('603.50')
  Codificacion: latin1.

Una cuenta es valida para movimientos si:
  1. existe en el catalogo
  2. NO es acumulativa (ninguna otra cuenta la tiene como cuenta de mayor)
  3. NO esta en la lista de cuentas retiradas de la empresa
  4. su agrupador es de nivel subcuenta (lleva punto: '603.50', no '603')
Ademas, si la empresa lo pide, se ADVIERTE (sin bloquear) cuando el agrupador no
es el "espejo" del numero (603-50 -> 603.50). Es solo aviso porque en el
catalogo real hay cuentas legitimas que no lo cumplen (p. ej. 60450000 -> 604.48).

Sin Tkinter ni pandas: solo texto y diccionarios.
"""
import os

PREFIJO_CUENTA = "C  "

MOTIVO_NO_EXISTE = "NO_EXISTE"
MOTIVO_ACUMULATIVA = "ACUMULATIVA"
MOTIVO_RETIRADA = "RETIRADA"
MOTIVO_AGRUPADOR_NIVEL_1 = "AGRUPADOR_NIVEL_1"

_TEXTO_MOTIVO = {
    MOTIVO_NO_EXISTE: "no existe en el catalogo",
    MOTIVO_ACUMULATIVA: "es una cuenta acumulativa (tiene subcuentas); solo se registra en las subcuentas",
    MOTIVO_RETIRADA: "esta en la lista de cuentas retiradas de la empresa",
    MOTIVO_AGRUPADOR_NIVEL_1: "su codigo agrupador SAT es de nivel 1; las cuentas afectables necesitan nivel subcuenta",
}


def normalizar_cuenta(texto):
    """'603-50-000' o ' 60350000 ' -> '60350000'."""
    return "".join(ch for ch in str(texto) if ch.isalnum()).upper()


def _leer_linea_de_cuenta(linea):
    """Una linea 'C  ...' -> (numero_de_cuenta, diccionario con sus datos)."""
    campos = linea[167:].split()
    registro = {
        "nombre": linea[34:85].strip(),
        "cuenta_mayor": normalizar_cuenta(linea[136:167]),
        "tipo": campos[0] if campos else "",
        "nivel": campos[2] if len(campos) > 2 else "",
        "agrupador": campos[-1] if campos else "",
    }
    return normalizar_cuenta(linea[3:34]), registro


def leer_catalogo(ruta):
    """
    Devuelve {cuenta: datos} con todas las cuentas del archivo. Lanza ValueError
    si el archivo no parece un cuentas.txt de CONTPAQi (para no validar contra nada).
    """
    with open(ruta, encoding="latin1") as archivo:
        lineas = [l.rstrip("\r\n") for l in archivo if l.startswith(PREFIJO_CUENTA)]
    if not lineas:
        raise ValueError(f"'{os.path.basename(ruta)}' no trae lineas de cuenta ('C  ...'): "
                         "no es un cuentas.txt de CONTPAQi de ancho fijo.")
    return dict(_leer_linea_de_cuenta(l) for l in lineas)


def leer_catalogo_si_es_valido(ruta):
    """
    Para usar en la corrida: devuelve (catalogo, mensaje). Si el archivo falta o no
    es un cuentas.txt de ancho fijo, catalogo es None y el mensaje dice por que.
    """
    if not ruta or not os.path.exists(ruta):
        return None, f"No se encontro el catalogo de cuentas ({ruta or 'sin ruta configurada'})."
    try:
        return leer_catalogo(ruta), ""
    except (ValueError, OSError) as error:
        return None, str(error)


def cuentas_acumulativas(catalogo):
    """Cuentas que son 'padre' de otra: no aceptan movimientos."""
    return {dato["cuenta_mayor"] for dato in catalogo.values() if dato["cuenta_mayor"]}


def validar_cuenta(cuenta, catalogo, acumulativas, cuentas_retiradas):
    """
    Devuelve None si la cuenta sirve para movimientos; si no, (codigo, texto)
    con el PRIMER motivo que la descalifica.
    """
    numero = normalizar_cuenta(cuenta)
    dato = catalogo.get(numero)
    if dato is None:
        return MOTIVO_NO_EXISTE, _TEXTO_MOTIVO[MOTIVO_NO_EXISTE]
    if numero in acumulativas:
        return MOTIVO_ACUMULATIVA, _TEXTO_MOTIVO[MOTIVO_ACUMULATIVA]
    if numero in {normalizar_cuenta(c) for c in cuentas_retiradas}:
        return MOTIVO_RETIRADA, _TEXTO_MOTIVO[MOTIVO_RETIRADA]
    if "." not in dato["agrupador"]:
        return MOTIVO_AGRUPADOR_NIVEL_1, _TEXTO_MOTIVO[MOTIVO_AGRUPADOR_NIVEL_1]
    return None


def agrupador_espejo(cuenta):
    """'60350000' -> '603.50' (lo que tendria el agrupador si espejara el numero)."""
    numero = normalizar_cuenta(cuenta)
    return f"{numero[:3]}.{numero[3:5]}"


def advertencia_de_espejo(cuenta, catalogo):
    """Texto de aviso si el agrupador no espeja el numero de cuenta; None si coincide."""
    numero = normalizar_cuenta(cuenta)
    dato = catalogo.get(numero)
    if dato is None or dato["agrupador"] == agrupador_espejo(numero):
        return None
    return (f"el agrupador SAT es {dato['agrupador']} y por su numero se esperaria "
            f"{agrupador_espejo(numero)}")


def catalogo_a_tabla(catalogo):
    """
    Filas [(cuenta, nombre, cuenta_mayor, tipo, nivel, agrupador)] para armar el
    DataFrame que usan las sugerencias (la columna 0 es la cuenta, la 1 el nombre).
    """
    return [(c, d["nombre"], d["cuenta_mayor"], d["tipo"], d["nivel"], d["agrupador"])
            for c, d in catalogo.items()]
