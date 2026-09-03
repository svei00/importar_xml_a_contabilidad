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
Fase 3 agrega:
  fecha_poliza             fecha del pago (REP) o de pago embebida en el folio del IMSS (caso C)
  tipo_poliza              Egreso o Diario segun la forma de pago (caso B)
  cuenta_contrapartida     banco, cuenta del socio (tarjeta) o PENDIENTE (caso B)
Fase 4 agrega (caso E): cada cuenta decidida (principal, de tercero, contrapartida y las
lineas de pago de un REP) se valida contra el catalogo de CONTPAQi. Una cuenta que no
existe, es acumulativa, esta retirada o tiene agrupador de nivel 1 se cambia por
PENDIENTE (la original queda en <campo>_rechazada) y se registra CUENTA_INVALIDA.
Fase 5 agrega (caso F): un pago de cuota patronal (IMSS, INFONAVIT) se carga al pasivo solo si la
balanza del cierre del mes anterior muestra saldo por pagar; si no, va directo al gasto.
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
from fecha_de_poliza import (decidir_fecha_poliza, avisar_si_el_pago_es_de_otro_periodo,
                             avisar_saldo_insoluto)
from formas_de_pago import necesita_contrapartida, decidir_contrapartida
from catalogo_contpaqi import cuentas_acumulativas, validar_cuenta, advertencia_de_espejo
from cuotas_patronales import aplicar_regla_de_cuotas

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


def _aplicar_fecha_y_forma_de_pago(filas, periodo_lote, config_empresa, es_egresos, colector):
    """
    Fase 3. Cada fila activa sale con:
      fecha_poliza           fecha del PAGO en un REP; fecha de pago del folio en el IMSS; si no, la de emision
      tipo_poliza           (solo compras que mueven dinero) Egreso o Diario
      cuenta_contrapartida  (solo compras que mueven dinero) banco, cuenta del socio o PENDIENTE
    """
    rfcs_con_fecha = {str(r).strip().upper() for r in config_empresa.get("rfcs_con_fecha_en_folio", [])}
    cuenta_banco = config_empresa.get("cuentas_default", {}).get("bancos", "10201000")
    formas_config = config_empresa.get("formas_pago", {})

    for fila in filas:
        if fila.get("omitir"):
            continue
        fila["fecha_poliza"] = decidir_fecha_poliza(fila, rfcs_con_fecha, colector)
        avisar_si_el_pago_es_de_otro_periodo(fila, periodo_lote, colector)
        if fila.get("tipo") == "P":
            avisar_saldo_insoluto(fila, colector)
        if es_egresos and necesita_contrapartida(fila):
            decidir_contrapartida(fila, formas_config, cuenta_banco, colector)


CUENTA_PENDIENTE = "PENDIENTE"
_SIN_CUENTA = ("", "0", "nan", "None", CUENTA_PENDIENTE)

_SUGERENCIA_POR_CAMPO = {
    "cuenta": "Asigna la cuenta correcta como 'Cuenta gasto' del proveedor en Administrar "
              "Clientes y Proveedores (o corrige el Excel y usa 'Aprender').",
    "cuenta_tercero": "Corrige la 'Cuenta tercero' de este proveedor o cliente en Administrar Clientes y Proveedores.",
    "cuenta_contrapartida": "Corrige la cuenta de esa forma de pago en 'formas_pago' de la empresa (settings.json).",
}


def _rechazar_cuenta(fila, campo, cuenta, motivo, colector):
    """Cambia la cuenta mala por PENDIENTE, guarda la original y deja la excepcion BLOQUEANTE."""
    fila[campo + "_rechazada"] = cuenta
    colector.agregar(
        exc.CUENTA_INVALIDA, exc.BLOQUEANTE, fila.get("uuid", ""),
        f"La cuenta {cuenta} ({campo}) {motivo}.", _SUGERENCIA_POR_CAMPO.get(campo, ""))
    return CUENTA_PENDIENTE


def _revisar_una_cuenta(fila, campo, cuenta, reglas, colector):
    """Devuelve la cuenta que debe quedar: la misma si sirve, PENDIENTE si no."""
    cuenta = str(cuenta).strip()
    if cuenta in _SIN_CUENTA:
        return cuenta
    catalogo, acumulativas, retiradas, pedir_espejo = reglas
    rechazo = validar_cuenta(cuenta, catalogo, acumulativas, retiradas)
    if rechazo is not None:
        return _rechazar_cuenta(fila, campo, cuenta, rechazo[1], colector)
    if pedir_espejo:
        aviso = advertencia_de_espejo(cuenta, catalogo)
        if aviso:
            colector.agregar(exc.CUENTA_FUERA_DE_ESPEJO, exc.INFORMATIVA, fila.get("uuid", ""),
                             f"Cuenta {cuenta}: {aviso}.", "Solo informativo; confirma que sea la cuenta que quieres.")
    return cuenta


def _revisar_lineas_de_pago(fila, reglas, colector):
    """Las cuentas de cada linea de un REP (caso A) tambien deben ser validas."""
    lineas = json.loads(fila.get("aplicaciones_pago") or "[]")
    for linea in lineas:
        linea["cuenta"] = _revisar_una_cuenta(fila, "cuenta_tercero", linea["cuenta"], reglas, colector)
    fila["aplicaciones_pago"] = json.dumps(lineas)
    if lineas:
        fila["cuenta_tercero"] = lineas[0]["cuenta"]


def _validar_cuentas_de_las_filas(filas, catalogo, config_empresa, colector):
    """Caso E: ninguna cuenta mala llega a una poliza sin que se vea."""
    if catalogo is None:
        colector.agregar(
            exc.CATALOGO_NO_DISPONIBLE, exc.INFORMATIVA, "",
            "No hay catalogo de cuentas legible: las cuentas NO se validaron.",
            "Revisa la ruta del catalogo en Configuracion (debe ser el cuentas.txt de CONTPAQi).")
        return
    reglas = (catalogo, cuentas_acumulativas(catalogo),
              config_empresa.get("cuentas_retiradas", []),
              bool(config_empresa.get("catalogo_espejo_agrupador")))

    for fila in filas:
        if fila.get("omitir"):
            continue
        tipo = fila.get("tipo")
        if tipo in ("I", "E", "N") and fila.get("cuenta") is not None:
            fila["cuenta"] = _revisar_una_cuenta(fila, "cuenta", fila["cuenta"], reglas, colector)
        if tipo == "P" and fila.get("aplicaciones_pago"):
            _revisar_lineas_de_pago(fila, reglas, colector)
        elif tipo in ("I", "E") and fila.get("cuenta_tercero"):
            fila["cuenta_tercero"] = _revisar_una_cuenta(fila, "cuenta_tercero", fila["cuenta_tercero"], reglas, colector)
        if fila.get("cuenta_contrapartida"):
            fila["cuenta_contrapartida"] = _revisar_una_cuenta(
                fila, "cuenta_contrapartida", fila["cuenta_contrapartida"], reglas, colector)


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


def aplicar_reglas(filas, config_empresa, colector, empresa_rfc=None, tipo_operacion=None,
                   catalogo=None, balanza=None):
    """
    Aplica, en orden, las reglas de decision a TODAS las filas (modifica los
    diccionarios en su lugar) y devuelve el periodo del lote ('AAAA-MM').
    Si se da empresa_rfc y tipo_operacion ('ingresos'/'egresos') tambien aplica
    las reglas que consultan el registro de lo ya contabilizado (Fase 2).
    `catalogo` es el diccionario de catalogo_contpaqi.leer_catalogo (None = no validar).
    `balanza` es el resultado de balanza_contpaqi.leer_balanza (None = sin balanza).
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
        _aplicar_fecha_y_forma_de_pago(filas, periodo_lote, config_empresa,
                                       tipo_operacion == "egresos", colector)
        if tipo_operacion == "egresos":
            aplicar_regla_de_cuotas(filas, config_empresa, balanza, colector)
        _validar_cuentas_de_las_filas(filas, catalogo, config_empresa, colector)
    return periodo_lote
