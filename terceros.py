"""
terceros.py — Normalización de nombres y construcción de la Referencia de pólizas.

La Referencia que se manda a CONTPAQi es la CLAVE consistente para filtrar el
reporte de Auxiliares cuando NO se abre una cuenta por cada proveedor. Formato:

    RFC-SHORTNAME      ej.  CFE370814QI0-LUZ   TME840315KT6-TELMEX

- El RFC va completo (12 = persona moral, 13 = persona física); nunca se recorta.
- El SHORTNAME es un apodo corto, consistente y SIN espacios (los espacios rompen
  el formato de ancho fijo de CONTPAQi). Por defecto se deriva del nombre del XML;
  el usuario puede sobreescribirlo (CFE -> LUZ, Teléfonos de México -> TELMEX, etc.).

Sin dependencias del resto de la app (solo stdlib) para evitar imports circulares.
"""
import re
import unicodedata

# Palabras de forma legal / ruido que NO aportan al apodo.
RUIDO_LEGAL = {
    "SA", "DE", "CV", "SAB", "RL", "SC", "SAPI", "SOFOM", "ENR",
    "SADECV", "S", "A", "C", "V", "Y", "EL", "LA", "LOS", "LAS",
}

MAX_SHORTNAME = 16   # cabe junto al RFC de 13 + "-" dentro de los 30 chars del campo
ANCHO_REFERENCIA = 30


def _sin_acentos_mayus(texto):
    """Mayúsculas y quita acentos. Excepción: AÑO -> ANIO (para no escribir 'ANO').
    Las demás ñ se vuelven N normalmente (Muñoz -> MUNOZ)."""
    s = str(texto).upper().replace("AÑO", "ANIO")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def limpiar_shortname(texto, max_len=MAX_SHORTNAME):
    """Sanea un apodo escrito por el usuario: sin acentos, sin espacios, solo A-Z0-9."""
    s = _sin_acentos_mayus(texto)
    s = re.sub(r"[^A-Z0-9]", "", s)   # fuera espacios y puntuación
    return s[:max_len]


def normalizar_shortname(nombre, max_len=MAX_SHORTNAME):
    """Apodo por defecto: primera palabra significativa del nombre del XML."""
    s = _sin_acentos_mayus(nombre)
    palabras = [p for p in re.split(r"[^A-Z0-9]+", s) if p and p not in RUIDO_LEGAL]
    base = palabras[0] if palabras else re.sub(r"[^A-Z0-9]", "", s)
    return base[:max_len]


# Partículas que van en minúscula dentro de un nombre propio en español.
_PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "E", "EN", "A"}
# Siglas de forma legal que conservan MAYÚSCULAS (se ven raras capitalizadas).
_SIGLAS_LEGAL = {"SA", "CV", "SAB", "RL", "SC", "SAPI", "SOFOM", "ENR", "SADECV"}


def titulo(texto):
    """Title Case en español para mostrar nombres que el XML trae EN MAYÚSCULAS.
    - Partículas (de, la, los, y…) en minúscula salvo si abren el nombre.
    - Siglas legales (SA, CV, RL…) se quedan en MAYÚSCULAS.
    - El RFC NO pasa por aquí: es una clave fiscal y va en mayúsculas."""
    s = str(texto).strip()
    if not s or s.lower() == "nan":
        return ""
    palabras = s.split()
    out = []
    for i, w in enumerate(palabras):
        clave = re.sub(r"[^A-ZÁÉÍÓÚÑ]", "", w.upper())
        if clave in _SIGLAS_LEGAL:
            out.append(w.upper())
        elif clave in _PARTICULAS and i != 0:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def construir_referencia(rfc, nombre, aliases=None):
    """
    Devuelve 'RFC-SHORTNAME' (<= 30 chars). Si no hay RFC válido devuelve ""
    para que el llamador use un respaldo (p.ej. el folio en nómina).
    """
    rfc = str(rfc).strip().upper()
    if not rfc or rfc == "NAN" or len(rfc) < 12:
        return ""

    short = (aliases or {}).get(rfc)
    if not short:
        short = normalizar_shortname(nombre)

    espacio = ANCHO_REFERENCIA - len(rfc) - 1   # -1 por el guion
    short = limpiar_shortname(short, max_len=max(0, espacio))
    return f"{rfc}-{short}" if short else rfc
