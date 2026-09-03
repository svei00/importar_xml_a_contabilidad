"""
registrar_corrida.py - Anota en el registro lo que una corrida decidio.

Se llama DESPUES de escribir los archivos con exito. Convierte cada fila (un
CFDI ya procesado por reglas_contables) en una fila de documentos_contabilizados
y guarda los pagos aplicados de cada REP.

resultado de cada documento:
  contabilizado   genero poliza
  cancelado       el SAT lo reporto cancelado
  omitido_nomina  nomina con nomina_modo = contpaqi
  reexpedicion    mismo pago ya contabilizado con otro UUID
"""
import json
import registro_contable as registro

RESULTADO_POR_MOTIVO = {
    "cancelado": "cancelado",
    "nomina": "omitido_nomina",
    "reexpedicion": "reexpedicion",
}


def _resultado_de_la_fila(fila, uuids_bloqueados=frozenset()):
    if not fila.get("omitir"):
        # Una poliza bloqueada NO se importo a CONTPAQi: no cuenta como contabilizada.
        bloqueado = str(fila.get("uuid", "")).strip().upper() in uuids_bloqueados
        return "bloqueado" if bloqueado else "contabilizado"
    return RESULTADO_POR_MOTIVO.get(fila.get("motivo_omision"), "omitido")


def _documento_desde_fila(fila, es_egresos, uuids_bloqueados=frozenset()):
    """Una fila de CFDI -> diccionario con las columnas de documentos_contabilizados."""
    fecha = str(fila.get("fecha", ""))[:10]
    return {
        "uuid": fila.get("uuid", ""),
        "llave_negocio": fila.get("llave_negocio", ""),
        "tipo_cfdi": fila.get("tipo", ""),
        "metodo_pago": fila.get("metodo_pago", ""),
        "forma_pago": fila.get("forma_pago", ""),
        "rfc_tercero": fila.get("rfc_emisor") if es_egresos else fila.get("rfc_receptor"),
        "serie": fila.get("serie", ""),
        "folio": fila.get("folio", ""),
        "total": fila.get("total", 0),
        "fecha_cfdi": fecha,
        "fecha_poliza": fila.get("fecha_poliza") or fecha,
        "tipo_poliza": fila.get("tipo_poliza") or None,
        "cuenta_principal": fila.get("cuenta", ""),
        "cuenta_contrapartida": fila.get("cuenta_contrapartida") or None,
        "cuenta_tercero": fila.get("cuenta_tercero") or None,
        "resultado": _resultado_de_la_fila(fila, uuids_bloqueados),
        "documento_original_uuid": fila.get("documento_original_uuid") or None,
    }


def registrar_lote(empresa_rfc, tipo_operacion, periodo, carpeta_origen, filas,
                   estado, archivo_txt="", uuids_bloqueados=()):
    """
    Crea el lote, guarda todos sus documentos (incluidos los omitidos, con su
    motivo) y los pagos aplicados de los REP. Devuelve el lote_id.
    """
    es_egresos = tipo_operacion == "egresos"
    bloqueados = {str(u).strip().upper() for u in uuids_bloqueados}
    registro.crear_tablas(empresa_rfc)
    lote_id = registro.crear_lote(empresa_rfc, tipo_operacion, periodo, carpeta_origen,
                                  estado, archivo_txt)
    registro.guardar_documentos(
        empresa_rfc, lote_id, [_documento_desde_fila(f, es_egresos, bloqueados) for f in filas])

    for fila in filas:
        if fila.get("tipo") == "P" and not fila.get("omitir") and fila.get("aplicaciones_pago"):
            registro.guardar_pagos_aplicados(
                empresa_rfc, lote_id, fila.get("uuid", ""), json.loads(fila["aplicaciones_pago"]))
    return lote_id
