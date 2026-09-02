"""
formas_de_pago.py - Caso B: la forma de pago decide contra que cuenta se abona.

Problema: antes TODO pago iba contra banco. Pero un REP de Telmex con
FormaDePagoP = 04 (tarjeta de credito) lo pago el socio con SU tarjeta: no existe
ese cargo en el estado de cuenta de la empresa. Hay que reconocer una deuda con
el socio (205-01-002) y la poliza pasa a Diario.

El mapa forma -> (cuenta, tipo de poliza) vive en la configuracion de CADA
empresa (llave 'formas_pago'). Aqui solo van los valores que valen para todas:
transferencia y cheque salen del banco. Una forma que NO este en el mapa deja la
contrapartida en PENDIENTE y registra una excepcion BLOQUEANTE: nada se adivina.

Ejemplo de config de empresa:
    "formas_pago": {"04": {"cuenta": "20501002", "tipo_poliza": "Diario"},
                    "28": {"cuenta": "20501002", "tipo_poliza": "Diario"}}
"cuenta": "bancos" es un alias de cuentas_default.bancos.
"""
import excepciones as exc
from fecha_de_poliza import leer_pagos_del_rep

ALIAS_BANCO = "bancos"
CUENTA_PENDIENTE = "PENDIENTE"
LIMITE_PAGO_CON_REQUISITOS = 2000.0   # LISR 27 fr. III: pagos mayores deben ir por medios bancarios

FORMAS_POR_DEFECTO = {
    "02": {"cuenta": ALIAS_BANCO, "tipo_poliza": "Egreso"},                    # cheque nominativo
    "03": {"cuenta": ALIAS_BANCO, "tipo_poliza": "Egreso"},                    # transferencia
    "99": {"cuenta": ALIAS_BANCO, "tipo_poliza": "Egreso", "advertir": True},  # por definir
}


def forma_de_pago_de_la_fila(fila):
    """REP: la FormaDePagoP de su (primer) pago. Factura PUE: la FormaPago del comprobante."""
    if fila.get("tipo") == "P":
        pagos = leer_pagos_del_rep(fila)
        return str(pagos[0].get("forma_pago", "")).strip() if pagos else ""
    return str(fila.get("forma_pago", "")).strip()


def necesita_contrapartida(fila):
    """Solo los que MUEVEN dinero hoy: REP y facturas PUE (las PPD no tocan banco)."""
    return fila.get("tipo") == "P" or (fila.get("tipo") == "I" and fila.get("metodo_pago") == "PUE")


def _cuenta_real(cuenta_configurada, cuenta_banco):
    """Traduce el alias 'bancos' a la cuenta de banco de la empresa."""
    return cuenta_banco if cuenta_configurada == ALIAS_BANCO else str(cuenta_configurada)


def _avisar_forma_sin_mapeo(fila, forma, colector):
    colector.agregar(
        exc.FORMA_PAGO_SIN_MAPEO, exc.BLOQUEANTE, fila.get("uuid", ""),
        f"La forma de pago '{forma or 'vacia'}' no esta en el mapa de la empresa: "
        "la contrapartida quedo PENDIENTE.",
        "Agrega la forma en 'formas_pago' de la empresa (settings.json) con su cuenta y tipo de poliza.")


def _avisar_contrapartida_especial(fila, forma, cuenta, mapeo, colector):
    """Informa cuando el pago NO es un simple cargo a banco (tarjeta del socio, 'por definir'...)."""
    nota = ""
    if float(fila.get("total", 0) or 0) > LIMITE_PAGO_CON_REQUISITOS:
        nota = (" Pago mayor a $2,000: revisa que cumpla los requisitos de pago de la "
                "deduccion (LISR 27 fr. III).")
    colector.agregar(
        exc.FORMA_PAGO_ADVERTIDA, exc.INFORMATIVA, fila.get("uuid", ""),
        f"Forma de pago {forma}: la poliza va como {mapeo.get('tipo_poliza', 'Egreso')} contra {cuenta}.{nota}",
        "Confirma que corresponda; una forma 'por definir' o un pago del socio no sale del banco.")


def decidir_contrapartida(fila, formas_config, cuenta_banco, colector):
    """
    Deja en la fila 'cuenta_contrapartida' y 'tipo_poliza'. `formas_config` es el
    mapa de la empresa (se mezcla sobre FORMAS_POR_DEFECTO).
    """
    forma = forma_de_pago_de_la_fila(fila)
    mapeo = {**FORMAS_POR_DEFECTO, **(formas_config or {})}.get(forma)

    if mapeo is None:
        fila["cuenta_contrapartida"] = CUENTA_PENDIENTE
        fila["tipo_poliza"] = "Egreso"
        _avisar_forma_sin_mapeo(fila, forma, colector)
        return

    cuenta = _cuenta_real(mapeo["cuenta"], cuenta_banco)
    fila["cuenta_contrapartida"] = cuenta
    fila["tipo_poliza"] = mapeo.get("tipo_poliza", "Egreso")
    if mapeo.get("advertir") or cuenta != cuenta_banco:
        _avisar_contrapartida_especial(fila, forma, cuenta, mapeo, colector)
