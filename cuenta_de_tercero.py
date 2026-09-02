"""
cuenta_de_tercero.py - Caso A: el pago cancela la cuenta donde vive la factura.

Problema: antes todo REP se pagaba contra la cuenta default de proveedores
(201-01-999), aunque la factura se hubiera registrado en 201-01-002 CFE. Quedaba
un saldo acreedor fantasma en una y un deudor falso en la otra.

Orden para decidir la cuenta de un documento (el primero que la tenga gana):
  1. esta_corrida  la factura se registro en este mismo lote (ya tiene cuenta)
  2. registro      la memoria de la app: la cuenta con que se contabilizo antes
  3. alias         la cuenta que Svei asigno al proveedor/cliente (por RFC)
  4. default       la cuenta general (proveedores varios / clientes varios)

Solo cuando se llega al 4 y el documento NO esta en el registro se avisa con
PAGO_DE_DOCUMENTO_NO_REGISTRADO.

Sin base de datos ni ventanas: las busquedas llegan como funciones.
"""
import json
import excepciones as exc

ORIGEN_ESTA_CORRIDA = "esta_corrida"
ORIGEN_REGISTRO = "registro"
ORIGEN_ALIAS = "alias"
ORIGEN_DEFAULT = "default"

# Diferencia (en pesos) que se tolera al comparar lo pagado contra el monto del REP.
TOLERANCIA_PESOS = 0.01


def cuenta_para_documento_nuevo(rfc_tercero, cuentas_alias, cuenta_default):
    """Cuenta de tercero para una factura que se contabiliza HOY: alias o default."""
    rfc = str(rfc_tercero or "").strip().upper()
    return cuentas_alias.get(rfc) or cuenta_default


def resolver_cuenta_de_documento(id_documento, rfc_tercero, cuentas_de_esta_corrida,
                                 buscar_en_registro, cuentas_alias, cuenta_default):
    """
    Devuelve (cuenta, origen, documento_conocido) para el documento que paga un REP.
    buscar_en_registro(uuid) -> (conocido, cuenta_o_None)
    """
    uuid = str(id_documento or "").strip().upper()

    if uuid in cuentas_de_esta_corrida:
        return cuentas_de_esta_corrida[uuid], ORIGEN_ESTA_CORRIDA, True

    conocido, cuenta_registro = buscar_en_registro(uuid)
    if cuenta_registro:
        return cuenta_registro, ORIGEN_REGISTRO, True

    rfc = str(rfc_tercero or "").strip().upper()
    if cuentas_alias.get(rfc):
        return cuentas_alias[rfc], ORIGEN_ALIAS, conocido

    return cuenta_default, ORIGEN_DEFAULT, conocido


def _leer_pagos(fila):
    """El REP guarda sus pagos como texto JSON en la columna pagos_json."""
    texto = fila.get("pagos_json") or ""
    try:
        return json.loads(texto) if texto else []
    except (TypeError, ValueError):
        return []


def armar_aplicaciones_pago(fila, resolver, cuenta_default, colector):
    """
    Convierte un REP en una lista de lineas [{id_documento, imp_pagado,
    imp_saldo_insoluto, cuenta, origen}], una por factura pagada, mas una linea
    residual (a la cuenta default) si lo pagado no suma el monto del REP.
    `resolver(id_documento)` -> (cuenta, origen, conocido).
    """
    aplicaciones = []
    for pago in _leer_pagos(fila):
        for doc in pago.get("documentos", []):
            cuenta, origen, conocido = resolver(doc.get("id_documento", ""))
            aplicaciones.append({
                "id_documento": doc.get("id_documento", ""),
                "imp_pagado": round(float(doc.get("imp_pagado", 0) or 0), 2),
                "imp_saldo_insoluto": round(float(doc.get("imp_saldo_insoluto", 0) or 0), 2),
                "cuenta": cuenta, "origen": origen})
            if origen == ORIGEN_DEFAULT and not conocido:
                colector.agregar(
                    exc.PAGO_DE_DOCUMENTO_NO_REGISTRADO, exc.INFORMATIVA, fila.get("uuid", ""),
                    f"El REP paga {doc.get('id_documento', '')[:8]} que no esta en el registro: "
                    f"se uso la cuenta {cuenta}.",
                    "Siembra el historial del mes de esa factura o asigna la cuenta del proveedor.")

    return _cuadrar_con_el_monto(fila, aplicaciones, cuenta_default, colector)


def _cuadrar_con_el_monto(fila, aplicaciones, cuenta_default, colector):
    """Garantiza que la suma de las lineas sea EXACTAMENTE el total del REP."""
    total = round(float(fila.get("total", 0) or 0), 2)
    pagado = round(sum(a["imp_pagado"] for a in aplicaciones), 2)

    if not aplicaciones or pagado > total + TOLERANCIA_PESOS:
        if aplicaciones:
            colector.agregar(
                exc.PAGO_DESCUADRADO_CON_DOCUMENTOS, exc.INFORMATIVA, fila.get("uuid", ""),
                f"Los documentos suman {pagado} y el REP {total}: se uso una sola linea a {cuenta_default}.",
                "Revisa el REP (¿otra moneda o tipo de cambio?).")
        return [{"id_documento": "", "imp_pagado": total, "imp_saldo_insoluto": 0.0,
                 "cuenta": cuenta_default, "origen": ORIGEN_DEFAULT}]

    residual = round(total - pagado, 2)
    if abs(residual) > TOLERANCIA_PESOS:
        aplicaciones.append({"id_documento": "", "imp_pagado": residual, "imp_saldo_insoluto": 0.0,
                             "cuenta": cuenta_default, "origen": ORIGEN_DEFAULT})
    return aplicaciones
