"""
texto_contpaqi.py - Limpia textos para que CONTPAQi los importe sin problemas.

Regla H del proyecto: los conceptos van al TXT en ASCII puro (sin acentos, sin
enie, sin simbolos raros). Antes el TXT se escribia en cp1252 con
errors="replace", lo que convertia cualquier caracter no soportado en "?" sin
avisar. ASCII nunca falla, y las Referencias ya eran ASCII.

El Excel conserva los acentos; solo el TXT para CONTPAQi se normaliza.
"""
import unicodedata

# Simbolos "bonitos" que no son ASCII pero tienen un equivalente razonable.
_EQUIVALENTES = {
    "–": "-",   # guion corto tipografico
    "—": "-",   # guion largo
    "‘": "'",   # comilla simple izquierda
    "’": "'",   # comilla simple derecha
    "“": '"',   # comilla doble izquierda
    "”": '"',   # comilla doble derecha
    " ": " ",   # espacio duro
}


def a_ascii(texto):
    """
    Convierte un texto a ASCII imprimible.
    Ejemplo: 'Reclasificacion de IVA - Munoz' queda igual;
             'Reclasificación Muñoz' -> 'Reclasificacion Munoz'.
    """
    texto = str(texto)
    for original, reemplazo in _EQUIVALENTES.items():
        texto = texto.replace(original, reemplazo)

    # NFD separa la letra de su acento (a + tilde); luego tiramos los acentos.
    descompuesto = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")

    # Lo que aun no sea ASCII imprimible (32 a 126) se elimina.
    return "".join(c for c in sin_acentos if 32 <= ord(c) <= 126)
