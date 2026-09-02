"""
detector_reexpediciones.py - Caso D: mismo pago, UUID distinto.

Reglas (en este orden, solo para filas que aun no se omiten):
  1. El UUID ya esta contabilizado en un lote de OTRO periodo   -> reexpedicion.
  2. La llave de negocio (RFC+Serie+Folio+Total) ya esta contabilizada en un
     lote de OTRO periodo                                        -> reexpedicion.
  3. Dentro del mismo lote, varios CFDI con la misma llave: se contabiliza el de
     fecha de emision mas antigua; los demas son reexpediciones.

Una fila omitida NO genera poliza ni va a la DIOT; se avisa con la excepcion
REEXPEDICION para que Svei liga el XML al ADD de la poliza original.

Las busquedas en el registro se reciben como funciones (inyeccion de
dependencias) para que este archivo se pueda probar sin base de datos.
"""
import excepciones as exc
from llave_negocio import construir_llave, llave_es_utilizable

MOTIVO_REEXPEDICION = "reexpedicion"
_TIPOS_CON_LLAVE = ("I", "E")   # los REP (tipo P) se comparan solo por UUID


def _marcar_reexpedicion(fila, uuid_original, detalle, colector):
    """Omite la fila y deja constancia clara de a cual documento corresponde."""
    fila["omitir"] = True
    fila["motivo_omision"] = MOTIVO_REEXPEDICION
    fila["documento_original_uuid"] = uuid_original
    colector.agregar(
        exc.REEXPEDICION, exc.INFORMATIVA, fila.get("uuid", ""),
        f"UUID {fila.get('uuid', '')} es reexpedicion de {uuid_original} ({detalle}). "
        "No se genero poliza.",
        "Liga este XML con un AD a la poliza original en CONTPAQi.")


def _describir_previo(previo):
    """'poliza del 2026-07-15, lote 2026-07'."""
    return f"poliza del {str(previo['fecha_cfdi'])[:10]}, lote {previo['periodo']}"


def poner_llaves(filas):
    """Calcula y guarda la llave de negocio de cada fila (la usa tambien el registro)."""
    for fila in filas:
        fila["llave_negocio"] = construir_llave(
            fila.get("rfc_emisor"), fila.get("serie"), fila.get("folio"), fila.get("total"))


def _detectar_contra_el_registro(filas, buscar_por_uuid, buscar_por_llave, colector):
    """Reglas 1 y 2: comparar contra lo ya contabilizado en otros periodos."""
    for fila in filas:
        if fila.get("omitir"):
            continue
        previo = buscar_por_uuid(fila.get("uuid", ""))
        if previo is None and fila.get("tipo") in _TIPOS_CON_LLAVE \
                and llave_es_utilizable(fila["llave_negocio"]):
            previo = buscar_por_llave(fila["llave_negocio"])
        if previo is not None:
            _marcar_reexpedicion(fila, previo["uuid"], _describir_previo(previo), colector)


def _detectar_dentro_del_lote(filas, periodo_lote, colector):
    """Regla 3: misma llave repetida en la misma corrida; gana la mas antigua."""
    candidatas = [f for f in filas if not f.get("omitir")
                  and f.get("tipo") in _TIPOS_CON_LLAVE
                  and llave_es_utilizable(f["llave_negocio"])]
    # Orden estable: la fecha de emision mas antigua primero, y el UUID desempata.
    candidatas.sort(key=lambda f: (str(f.get("fecha", "")), str(f.get("uuid", ""))))

    primera_por_llave = {}
    for fila in candidatas:
        original = primera_por_llave.setdefault(fila["llave_negocio"], fila)
        if original is not fila:
            detalle = f"mismo lote {periodo_lote}, emitida el {str(original.get('fecha', ''))[:10]}"
            _marcar_reexpedicion(fila, original["uuid"], detalle, colector)


def detectar_reexpediciones(filas, periodo_lote, buscar_por_uuid, buscar_por_llave, colector):
    """
    Punto de entrada. Modifica las filas en su lugar:
      llave_negocio            siempre
      omitir / motivo_omision  si es reexpedicion
      documento_original_uuid  si es reexpedicion
    """
    poner_llaves(filas)
    _detectar_contra_el_registro(filas, buscar_por_uuid, buscar_por_llave, colector)
    _detectar_dentro_del_lote(filas, periodo_lote, colector)
