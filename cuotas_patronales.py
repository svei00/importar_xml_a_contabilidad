"""
cuotas_patronales.py - Caso F: pago de cuota sin provision.

Problema: el IMSS de julio se pago en agosto y la app cargo el pago a
211-01-000 "IMSS por pagar". Pero esa cuenta estaba en CERO porque julio no se
provisiono; el cargo la dejo con un saldo deudor falso. Si no hay provision que
cancelar, el pago debe ir DIRECTO al gasto (603-26-000).

Regla (para cada CFDI PUE de un emisor configurado como cuota patronal):
  saldo disponible = saldo acreedor del pasivo en la balanza del cierre del mes
                     anterior - lo que esta misma corrida ya cargo a esa cuenta
  * saldo >= importe          -> cargo al pasivo (cancela la provision)
  * saldo = 0                 -> cargo directo al gasto + aviso PASIVO_SIN_SALDO
  * 0 < saldo < importe       -> PENDIENTE + aviso BLOQUEANTE (pago parcial: decide Svei)
  * no hay balanza utilizable -> segun 'sin_balanza': 'gasto_directo' (default, con aviso)
                                 o 'pendiente' (bloqueante)

Configuracion por empresa (settings.json -> empresas -> <RFC> -> cuotas_patronales):
    {"sin_balanza": "gasto_directo",
     "rfcs": {"IMS421231I45": {"cuenta_pasivo": "21101000", "cuenta_gasto": "60326000"},
              "INF7205011ZA": {"cuenta_pasivo": "21103000", "cuenta_gasto": "60327000"}}}

Sin Tkinter ni archivos: la balanza llega ya leida (balanza_contpaqi.leer_balanza).
"""
import excepciones as exc
from balanza_contpaqi import saldo_acreedor

TOLERANCIA_PESOS = 0.01
CUENTA_PENDIENTE = "PENDIENTE"
MODO_GASTO_DIRECTO = "gasto_directo"
MODO_PENDIENTE = "pendiente"


def cuentas_por_rfc(config_empresa):
    """{RFC: {'cuenta_pasivo', 'cuenta_gasto'}} de la empresa (vacio si no configuro nada)."""
    rfcs = (config_empresa.get("cuotas_patronales") or {}).get("rfcs") or {}
    return {str(rfc).strip().upper(): cuentas for rfc, cuentas in rfcs.items()}


def modo_sin_balanza(config_empresa):
    """Que hacer cuando no hay balanza: 'gasto_directo' (default) o 'pendiente'."""
    modo = (config_empresa.get("cuotas_patronales") or {}).get("sin_balanza", MODO_GASTO_DIRECTO)
    return modo if modo in (MODO_GASTO_DIRECTO, MODO_PENDIENTE) else MODO_GASTO_DIRECTO


def es_pago_de_cuota(fila, rfcs_de_cuotas):
    """Compra PUE (ya pagada) de un emisor configurado como cuota patronal."""
    return (fila.get("tipo") == "I" and fila.get("metodo_pago") == "PUE"
            and str(fila.get("rfc_emisor", "")).strip().upper() in rfcs_de_cuotas)


def _cargar_al_gasto(fila, cuentas, aviso, colector):
    fila["cuenta"] = cuentas["cuenta_gasto"]
    colector.agregar(exc.PASIVO_SIN_SALDO, exc.INFORMATIVA, fila.get("uuid", ""), aviso,
                     "Si el mes anterior si se provisiono, revisa que la balanza sea la correcta.")


def _dejar_pendiente(fila, codigo, mensaje, sugerencia, colector):
    fila["cuenta"] = CUENTA_PENDIENTE
    colector.agregar(codigo, exc.BLOQUEANTE, fila.get("uuid", ""), mensaje, sugerencia)


def _decidir_sin_balanza(fila, cuentas, modo, colector):
    mensaje = ("No hay balanza del cierre del mes anterior: no se puede saber si "
               f"{cuentas['cuenta_pasivo']} tiene saldo.")
    if modo == MODO_PENDIENTE:
        _dejar_pendiente(fila, exc.BALANZA_NO_DISPONIBLE, mensaje + " La cuenta quedo PENDIENTE.",
                         "Selecciona la balanza del mes anterior y vuelve a correr.", colector)
        return
    colector.agregar(exc.BALANZA_NO_DISPONIBLE, exc.INFORMATIVA, fila.get("uuid", ""),
                     mensaje + f" Se cargo directo al gasto {cuentas['cuenta_gasto']}.",
                     "Selecciona la balanza del mes anterior para validarlo.")
    fila["cuenta"] = cuentas["cuenta_gasto"]


def _decidir_con_balanza(fila, cuentas, saldo, importe, colector):
    """Devuelve el importe que se cargo al pasivo (0 si no fue al pasivo)."""
    if saldo + TOLERANCIA_PESOS >= importe:
        fila["cuenta"] = cuentas["cuenta_pasivo"]
        return importe
    if saldo <= TOLERANCIA_PESOS:
        _cargar_al_gasto(fila, cuentas,
                         f"{cuentas['cuenta_pasivo']} no tiene saldo por pagar: el pago de {importe:.2f} "
                         f"se cargo directo al gasto {cuentas['cuenta_gasto']}.", colector)
        return 0.0
    _dejar_pendiente(
        fila, exc.PASIVO_SALDO_PARCIAL,
        f"{cuentas['cuenta_pasivo']} tiene saldo {saldo:.2f} pero el pago es {importe:.2f}: "
        "solo una parte esta provisionada.",
        "Decide cuanto va al pasivo y cuanto al gasto; la poliza quedo PENDIENTE.", colector)
    return 0.0


def aplicar_regla_de_cuotas(filas, config_empresa, balanza, colector):
    """
    Decide la cuenta (pasivo o gasto) de cada pago de cuota patronal. Modifica
    fila['cuenta']. `balanza` es el resultado de leer_balanza o None.
    """
    por_rfc = cuentas_por_rfc(config_empresa)
    if not por_rfc:
        return
    ya_cargado_al_pasivo = {}   # lo que esta corrida ya cancelo en cada cuenta de pasivo

    pagos = [f for f in filas if not f.get("omitir") and es_pago_de_cuota(f, por_rfc)]
    # En orden cronologico: el primer pago del mes "usa" la provision, el siguiente ya no la encuentra.
    pagos.sort(key=lambda f: (str(f.get("fecha_poliza") or f.get("fecha", "")), str(f.get("uuid", ""))))

    for fila in pagos:
        cuentas = por_rfc[str(fila["rfc_emisor"]).strip().upper()]
        importe = round(float(fila.get("total", 0) or 0), 2)
        if balanza is None:
            _decidir_sin_balanza(fila, cuentas, modo_sin_balanza(config_empresa), colector)
            continue
        pasivo = cuentas["cuenta_pasivo"]
        saldo = round(saldo_acreedor(balanza, pasivo) - ya_cargado_al_pasivo.get(pasivo, 0.0), 2)
        ya_cargado_al_pasivo[pasivo] = ya_cargado_al_pasivo.get(pasivo, 0.0) + \
            _decidir_con_balanza(fila, cuentas, saldo, importe, colector)
