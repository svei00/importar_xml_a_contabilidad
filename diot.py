import pandas as pd
import os

# ---------------------------------------------------------------------------
# DIOT 2025 (carga por lotes, 54 columnas separadas por pipe).
#
# Reglas clave (confirmadas con el usuario / spec SAT 2025):
#   * UNA fila por RFC de proveedor (agregado del mes), no una por factura.
#   * Base CONTABLE = flujo de efectivo (PUE pagadas en el mes + REP recibidos).
#     Las PPD NO pagadas (sin REP) NO se incluyen; entran cuando llega su pago.
#   * Notas de crédito recibidas (tipo E) -> Devoluciones/Descuentos/Bonif. (DDB).
#   * Col 54 = "1" (Sí se cuenta con el CFDI).
#
# Mapa de columnas (1-index del SAT -> 0-index de Python):
#   1  c[0]  Tipo de tercero (04/05/15)
#   2  c[1]  Tipo de operación (02/03/06/85/87…)
#   3  c[2]  RFC (04/15; vacío en 05)
#   4  c[3]  ID fiscal extranjero (05)
#   5  c[4]  Nombre extranjero (05)
#   6  c[5]  País (05)
#   7  c[6]  Lugar jurisdicción fiscal (05)
#   8  c[7]  Base pagada RFN 8%
#   9  c[8]  DDB RFN 8%
#  10  c[9]  Base pagada RFS 8%
#  11  c[10] DDB RFS 8%
#  12  c[11] Base pagada tasa general 16%        <-- principal
#  13  c[12] DDB tasa general 16%                <-- notas de crédito
#  18  c[17] Base actos pagados Exentos
#  19  c[18] Base actos pagados tasa 0%
#  29  c[28] IVA Acreditable RFN 8%
#  31  c[30] IVA Acreditable tasa general 16%    <-- principal
#  48  c[47] IVA retenido por el contribuyente
#  54  c[53] Efectos fiscales del comprobante = "1"
# (las demás reservadas: van vacías pero con su pipe).
# ---------------------------------------------------------------------------

TASA_16 = 0.16
TASA_8 = 0.08


def determinar_tipo_tercero(rfc):
    rfc = str(rfc).strip().upper()
    if rfc == "XEXX010101000":
        return "05"  # Extranjero
    if rfc == "XAXX010101000":
        return "15"  # Global (público en general)
    return "04"      # Nacional


def determinar_tipo_operacion(concepto, tipo_tercero):
    """
    Tipo de operación según las reglas del SAT.
    NOTA: el código de 'Otros' para nacionales es 85 (no 08). El resumen de
    blog que circula usa 08; el código oficial histórico/SAT es 85. Se deja 85.
    """
    cl = str(concepto).lower()
    if tipo_tercero == "15":
        return "87"  # Global -> solo 87
    if tipo_tercero == "05":
        if "servicio" in cl or "honorario" in cl:
            return "03"
        if "importaci" in cl or "aduana" in cl:
            return "07"
        return "02"
    # Nacional (04): acepta 02, 03, 06, 85
    if "arrendamiento" in cl or "renta" in cl:
        return "06"
    if "honorarios" in cl or "servicios profesionales" in cl:
        return "03"
    return "85"  # Otros (el más común)


def generar_diot(df):
    """
    Agrega los comprobantes RECIBIDOS en UNA fila por (tipo_tercero, tipo_operacion, RFC)
    sobre base de FLUJO (PUE pagadas + REP), devolviendo el DataFrame que se ve en el
    Excel (pestaña DIOT_LISTA) y que consume exportar_txt_sat.
    """
    acc = {}  # clave -> dict agregado

    def slot(tipo_tercero, tipo_op, rfc, nombre):
        key = (tipo_tercero, tipo_op, str(rfc).strip().upper())
        if key not in acc:
            acc[key] = {
                "TipoTercero": tipo_tercero,
                "TipoOperacion": tipo_op,
                "RFC": str(rfc).strip().upper(),
                "Nombre": str(nombre),
                "Base16": 0.0, "DDB16": 0.0, "IVA_Acred16": 0.0,
                "Base8": 0.0, "IVA_Acred8": 0.0,
                "BaseExento": 0.0, "Base0": 0.0,
                "RetIVA": 0.0,
            }
        return acc[key]

    for _, r in df.iterrows():
        tipo = str(r.get("tipo", "")).strip().upper()
        metodo = str(r.get("metodo_pago", "")).strip().upper()

        # Nóminas y traslados nunca van a DIOT.
        if tipo in ("N", "T"):
            continue
        # PPD sin pagar (factura I marcada PPD) NO entra: entrará vía su REP.
        if tipo == "I" and metodo == "PPD":
            continue
        # Solo cuentan: facturas PUE (pagadas) y los REP (tipo P).
        if tipo not in ("I", "P", "E"):
            continue

        rfc = r.get("rfc_emisor", "")
        nombre = r.get("nombre_emisor", "")
        tt = determinar_tipo_tercero(rfc)
        top = determinar_tipo_operacion(r.get("concepto", ""), tt)
        s = slot(tt, top, rfc, nombre)

        iva16 = float(r.get("iva_16", 0) or 0)
        iva8 = float(r.get("iva_8", 0) or 0)
        ret_iva = float(r.get("ret_iva", 0) or 0)
        exento = float(r.get("iva_exento", 0) or 0)

        if tipo == "E":
            # Nota de crédito recibida -> Devoluciones/Descuentos/Bonificaciones.
            s["DDB16"] += iva16 / TASA_16 if iva16 else 0.0
            continue

        # Facturas PUE y REP: suman a la base acreditable del mes.
        if iva16:
            s["Base16"] += iva16 / TASA_16
            s["IVA_Acred16"] += iva16
        if iva8:
            s["Base8"] += iva8 / TASA_8
            s["IVA_Acred8"] += iva8
        if exento:
            s["BaseExento"] += exento
        if ret_iva:
            s["RetIVA"] += ret_iva

    filas = list(acc.values())
    return pd.DataFrame(filas)


def _ent(x):
    """Entero en pesos (DIOT por lotes no lleva decimales). Vacío si es 0."""
    try:
        n = int(round(float(x)))
    except (TypeError, ValueError):
        return ""
    return str(n) if n != 0 else ""


def exportar_txt_sat(df_diot, mes, anio, tipo_decl, output_dir):
    """
    Escribe el TXT de carga por lotes (54 columnas, pipe). Una línea por fila ya
    agregada de generar_diot. Devuelve la ruta del archivo (o None si vacío).
    """
    if df_diot is None or df_diot.empty:
        print("[AVISO] DIOT vacía: no se generó archivo.")
        return None

    meses_str = {"01": "Ene", "02": "Feb", "03": "Mar", "04": "Abr", "05": "May",
                 "06": "Jun", "07": "Jul", "08": "Ago", "09": "Sep", "10": "Oct",
                 "11": "Nov", "12": "Dic"}
    mes_str = str(mes).zfill(2)
    nombre_mes = meses_str.get(mes_str, "Mes")
    filename = f"{mes_str}. {nombre_mes} {anio} {tipo_decl} DIOT.txt"
    filepath = os.path.join(output_dir, filename)

    n = 0
    with open(filepath, "w", encoding="utf-8") as f:
        for _, r in df_diot.iterrows():
            c = [""] * 54

            tt = str(r.get("TipoTercero", "04"))
            c[0] = tt                                  # 1 Tipo tercero
            c[1] = str(r.get("TipoOperacion", "85"))   # 2 Tipo operación

            if tt in ("04", "15"):
                c[2] = str(r.get("RFC", ""))           # 3 RFC nacional/global
            elif tt == "05":
                c[4] = str(r.get("Nombre", ""))[:300]  # 5 Nombre extranjero
                c[5] = "US"                            # 6 País (default)

            # --- Tasa general 16% ---
            c[11] = _ent(r.get("Base16"))              # 12 Base 16%
            c[12] = _ent(r.get("DDB16"))               # 13 DDB 16%
            c[30] = _ent(r.get("IVA_Acred16"))         # 31 IVA acreditable 16%

            # --- 8% (frontera; este cliente normalmente no lo usa).
            # Sin dato RFN/RFS se asume RFN por defecto. Ver [[importar-xml-contpaqi]].
            c[7] = _ent(r.get("Base8"))                # 8 Base RFN 8%
            c[28] = _ent(r.get("IVA_Acred8"))          # 29 IVA acreditable RFN 8%

            # --- Exentos / tasa 0% (hoy 0: el parser no captura iva_exento aún).
            c[17] = _ent(r.get("BaseExento"))          # 18 Base exentos
            c[18] = _ent(r.get("Base0"))               # 19 Base 0%

            # --- Retención de IVA hecha por el contribuyente.
            c[47] = _ent(r.get("RetIVA"))              # 48 IVA retenido

            # --- Manifiesto: sí se cuenta con el CFDI.
            c[53] = "1"                                # 54 Efectos fiscales

            f.write("|".join(c) + "\n")
            n += 1

    print(f"[OK] DIOT (54 col, {n} terceros agregados) generada: {filename}")
    return filepath
