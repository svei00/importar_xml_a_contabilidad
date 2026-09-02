"""
sembrar_historial.py - Carga meses YA contabilizados a la memoria de la app.

Para que la app detecte reexpediciones (caso D) y sepa que facturas de meses
anteriores existen (caso A), necesita conocer lo que ya se contabilizo antes de
que existiera el registro. Se "siembra": se leen los XML de un mes anterior y se
crea un lote 'historico'.

Importante (aprendido con los datos reales de julio 2026): lo que esta en un TXT
de polizas viejo NO siempre es lo que quedo en los libros (Svei corrige cuentas a
mano en CONTPAQi). Por eso aqui NO se guardan cuentas: solo QUE comprobantes ya
se contabilizaron. La cuenta del proveedor sale del alias que Svei capture.
"""
from xml_processor import load_folder
from periodo_lote import determinar_periodo
from detector_reexpediciones import poner_llaves
from registrar_corrida import registrar_lote
import registro_contable as registro


def sembrar_desde_carpeta(carpeta, tipo_operacion):
    """
    Siembra un lote historico con los XML de una carpeta (un mes). Devuelve un
    diccionario con el resumen, o None si la carpeta no trae XML legibles.
    """
    filas = load_folder(carpeta)
    if not filas:
        return None

    es_egresos = tipo_operacion == "egresos"
    empresa_rfc = filas[0]["rfc_receptor"] if es_egresos else filas[0]["rfc_emisor"]
    periodo = determinar_periodo(filas)
    poner_llaves(filas)

    for fila in filas:
        # La nomina que genera CONTPAQi Nominas no cuenta como contabilizada por esta app.
        fila["omitir"] = fila.get("tipo") == "N"
        fila["motivo_omision"] = "nomina" if fila["omitir"] else ""

    registro.crear_tablas(empresa_rfc)
    lote_id = registrar_lote(empresa_rfc, tipo_operacion, periodo, carpeta, filas,
                             registro.ESTADO_HISTORICO)
    sembrados = sum(1 for f in filas if not f["omitir"])
    return {"empresa": empresa_rfc, "periodo": periodo, "lote_id": lote_id,
            "total_xml": len(filas), "sembrados": sembrados}
