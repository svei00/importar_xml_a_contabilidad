"""
reglas_contables.py - Orquestador de las reglas contables (corre ANTES de armar polizas).

Principio rector del proyecto: separar DECIDIR de ESCRIBIR.
  - Aqui se DECIDE (que filas se omiten, a que periodo pertenece cada una...).
  - export.generar_polizas solo ESCRIBE los asientos con lo ya decidido.

Cada fila (diccionario de un CFDI) sale de aqui con estas columnas nuevas:
  periodo          'AAAA-MM' propio del CFDI
  omitir           True si NO debe generar poliza ni DIOT
  motivo_omision   'cancelado' | 'nomina' | ''   (por que se omitio)

Fase 1 implementa: cancelados (B-11), nomina en modo CONTPAQi, periodo del lote
y estatus SAT desconocido.
Fase 2 agrega (solo si se conoce la empresa y el tipo de corrida, porque necesita
el registro de lo ya contabilizado):
  llave_negocio            huella RFC|SERIE|FOLIO|TOTAL del comprobante
  motivo_omision           'reexpedicion' (caso D)
  documento_original_uuid  a cual documento corresponde la reexpedicion
  cuenta_tercero           donde vive el saldo del proveedor/cliente (caso A)
  aplicaciones_pago        para un REP: texto JSON con que factura cancela cada
                           linea y contra que cuenta (caso A)
Las fases siguientes agregan sus reglas en aplicar_reglas(), una despues de otra.

Sin Tkinter ni ventanas: solo datos adentro, datos afuera.
"""
import json
import excepciones as exc
import registro_contable
from db import get_cuentas_por_tipo
from periodo_lote import periodo_de_fecha, determinar_periodo, filas_fuera_de_periodo
from detector_reexpediciones import detectar_reexpediciones
from cuenta_de_tercero import (cuenta_para_documento_nuevo, resolver_cuenta_de_documento,
                               armar_aplicaciones_pago)

MOTIVO_CANCELADO = "cancelado"
MOTIVO_NOMINA = "nomina"


def _marcar_cancelado(fila, colector):
    """Regla B-11: un CFDI cancelado NO entra a polizas ni a DIOT."""
    fila["omitir"] = True
    fila["motivo_omision"] = MOTIVO_CANCELADO
    colector.agregar(
        exc.CANCELADO, exc.INFORMATIVA, fila.get("uuid", ""),
        "CFDI cancelado en el SAT: se excluyo de polizas y DIOT.",
        "Si es un error, confirma el estatus en el portal del SAT y vuelve a correr el mes.")


def _marcar_nomina_si_corresponde(fila, config_empresa):
    """
    Con nomina_modo = 'contpaqi' (default) la poliza de nomina la hace CONTPAQi
    Nominas; esta app no la duplica. Con 'xml' si la arma.
    """
    modo = str(config_empresa.get("nomina_modo", "contpaqi")).lower()
    if fila.get("tipo") == "N" and modo != "xml":
        fila["omitir"] = True
        fila["motivo_omision"] = MOTIVO_NOMINA


def _avisar_estatus_desconocido(fila, colector):
    """Si el SAT no respondio, el CFDI se contabiliza pero se avisa."""
    if fila.get("estado_sat") in ("ERROR", "DESCONOCIDO"):
        colector.agregar(
            exc.ESTATUS_SAT_DESCONOCIDO, exc.INFORMATIVA, fila.get("uuid", ""),
            f"No se pudo confirmar el estatus en el SAT ({fila.get('estado_sat')}).",
            "Revisa manualmente que el CFDI siga vigente.")


def _avisar_fuera_de_periodo(filas, periodo, colector):
    """Avisa (sin omitir) los CFDI cuyo mes de emision no es el del lote."""
    for uuid, periodo_propio in filas_fuera_de_periodo(filas, periodo):
        colector.agregar(
            exc.FUERA_DE_PERIODO, exc.INFORMATIVA, uuid,
            f"Emitido en {periodo_propio}, pero el lote es de {periodo}.",
            "Verifica que corresponda a este mes; podria ser una reexpedicion.")


def _cuenta_default_de_tercero(fila, es_egresos, cuentas_default):
    """Cuenta 'varios' cuando el proveedor/cliente no tiene cuenta propia."""
    if es_egresos:
        return cuentas_default.get("proveedores", "20101999")
    if str(fila.get("rfc_receptor", "")).strip().upper() == "XEXX010101000":
        return cuentas_default.get("clientes_extranjero", "10502000")
    return cuentas_default.get("clientes", "10501999")


def _rfc_del_tercero(fila, es_egresos):
    """En compras el tercero es el emisor; en ventas es el receptor."""
    return fila.get("rfc_emisor") if es_egresos else fila.get("rfc_receptor")


def _asignar_cuentas_de_terceros(filas, empresa_rfc, es_egresos, cuentas_default, colector):
    """
    Caso A. Primero las facturas/notas (su cuenta se decide hoy: alias o default);
    despues los REP, que cancelan la cuenta donde vive cada factura que pagan.
    """
    cuentas_alias = get_cuentas_por_tipo(empresa_rfc, "P" if es_egresos else "C")
    cuentas_de_esta_corrida = {}

    for fila in filas:
        if fila.get("omitir") or fila.get("tipo") in ("P", "N"):
            continue
        default = _cuenta_default_de_tercero(fila, es_egresos, cuentas_default)
        cuenta = cuenta_para_documento_nuevo(_rfc_del_tercero(fila, es_egresos), cuentas_alias, default)
        fila["cuenta_tercero"] = cuenta
        cuentas_de_esta_corrida[str(fila.get("uuid", "")).upper()] = cuenta

    for fila in filas:
        if fila.get("omitir") or fila.get("tipo") != "P":
            continue
        default = _cuenta_default_de_tercero(fila, es_egresos, cuentas_default)
        rfc_tercero = _rfc_del_tercero(fila, es_egresos)

        def resolver(id_documento, rfc=rfc_tercero, cuenta_default=default):
            return resolver_cuenta_de_documento(
                id_documento, rfc, cuentas_de_esta_corrida,
                lambda uuid: registro_contable.buscar_cuenta_de_documento(empresa_rfc, uuid),
                cuentas_alias, cuenta_default)

        aplicaciones = armar_aplicaciones_pago(fila, resolver, default, colector)
        fila["aplicaciones_pago"] = json.dumps(aplicaciones)
        fila["cuenta_tercero"] = aplicaciones[0]["cuenta"]


def _aplicar_reglas_del_registro(filas, periodo_lote, empresa_rfc, tipo_operacion,
                                 config_empresa, colector):
    """Reglas de la Fase 2: reexpediciones (D) y cuenta de tercero / pagos (A)."""
    es_egresos = tipo_operacion == "egresos"
    registro_contable.crear_tablas(empresa_rfc)

    detectar_reexpediciones(
        filas, periodo_lote,
        lambda uuid: registro_contable.buscar_documento_por_uuid(
            empresa_rfc, uuid, tipo_operacion, periodo_lote),
        lambda llave: registro_contable.buscar_documento_por_llave(
            empresa_rfc, llave, tipo_operacion, periodo_lote),
        colector)

    _asignar_cuentas_de_terceros(
        filas, empresa_rfc, es_egresos, config_empresa.get("cuentas_default", {}), colector)


def aplicar_reglas(filas, config_empresa, colector, empresa_rfc=None, tipo_operacion=None):
    """
    Aplica, en orden, las reglas de decision a TODAS las filas (modifica los
    diccionarios en su lugar) y devuelve el periodo del lote ('AAAA-MM').
    Si se da empresa_rfc y tipo_operacion ('ingresos'/'egresos') tambien aplica
    las reglas que consultan el registro de lo ya contabilizado (Fase 2).
    """
    periodo_lote = determinar_periodo(filas)

    for fila in filas:
        fila["periodo"] = periodo_de_fecha(fila.get("fecha"))
        fila["omitir"] = False
        fila["motivo_omision"] = ""

        if fila.get("estado_sat") == "CANCELADO":
            _marcar_cancelado(fila, colector)
            continue

        _marcar_nomina_si_corresponde(fila, config_empresa)
        _avisar_estatus_desconocido(fila, colector)

    _avisar_fuera_de_periodo(filas, periodo_lote, colector)

    if empresa_rfc and tipo_operacion:
        _aplicar_reglas_del_registro(filas, periodo_lote, empresa_rfc, tipo_operacion,
                                     config_empresa, colector)
    return periodo_lote
