"""
config_empresa.py - Configuracion por EMPRESA (no global).

Problema (bug B-12 de la auditoria): settings.json es global, asi que una
segunda empresa heredaria en silencio las cuentas de la primera. Las llaves
NUEVAS del plan viven aqui, en settings["empresas"][<RFC>].

Lectura:  obtener_config_empresa(rfc) = config global + lo de la empresa encima
          (lo de la empresa GANA).
Escritura: guardar_valor_empresa(rfc, llave, valor) escribe SOLO en el bloque
          de esa empresa. Nunca copia cuentas de otra empresa.
"""
from config import load_settings, save_settings

# Valores por defecto de las llaves nuevas (si la empresa no define la suya).
VALORES_POR_DEFECTO = {
    "conceptos_ascii": True,   # regla H: conceptos del TXT en ASCII puro
}


def _limpiar_rfc(rfc):
    """El RFC de empresa siempre en mayusculas y sin espacios."""
    return "".join(str(rfc).split()).upper()


def obtener_config_empresa(rfc):
    """Devuelve la configuracion efectiva de UNA empresa (un diccionario nuevo)."""
    settings = load_settings()
    config_global = {k: v for k, v in settings.items() if k != "empresas"}
    bloque_empresa = settings.get("empresas", {}).get(_limpiar_rfc(rfc), {})
    return {**VALORES_POR_DEFECTO, **config_global, **bloque_empresa}


def guardar_valor_empresa(rfc, llave, valor):
    """Guarda UNA llave en el bloque de la empresa; crea el bloque vacio si falta."""
    settings = load_settings()
    empresas = settings.setdefault("empresas", {})
    empresas.setdefault(_limpiar_rfc(rfc), {})[llave] = valor
    save_settings(settings)
