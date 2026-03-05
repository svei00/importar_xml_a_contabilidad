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
#   * Col 54 "Manifiesto efectos fiscales" = "01" (Sí) / "02" (No). Numérico 2 pos.
#
# Mapa OFICIAL de las 54 columnas -- "Instructivo para el armado del archivo de
# carga masiva - DIOT", SAT, enero 2025, sección 3 (ejercicios 2025 en adelante).
# (1-index del SAT -> 0-index de Python). El bloque de IVA se divide en TRES
# secciones: 3.3 IVA ACREDITABLE, 3.4 IVA NO ACREDITABLE, 3.5 Datos adicionales.
#
# 3.1 Datos del tercero declarado
#   1  c[0]  Tipo de tercero (04 nacional / 05 extranjero / 15 global)
#   2  c[1]  Tipo de operación (nacional: 02/03/06/08/85 ; global: 87)
#   3  c[2]  RFC (obligatorio 04/15 ; opcional 05)
#   4  c[3]  Número de identificación fiscal del extranjero (05)
#   5  c[4]  Nombre del extranjero (05)
#   6  c[5]  País o jurisdicción de residencia fiscal (05; catálogo, p.ej. USA)
#   7  c[6]  Especificar lugar de jurisdicción fiscal (05, sólo si país = ZZZ)
#
# 3.2 Valor de los actos o actividades   [Valor total, DDB] x 5 secciones
#   8  c[7]  Valor total pagado / Región Fronteriza Norte 8%
#   9  c[8]  DDB / RFN 8%
#  10  c[9]  Valor total pagado / Región Fronteriza Sur 8%
#  11  c[10] DDB / RFS 8%
#  12  c[11] Valor total pagado / tasa general 16%           <-- BASE principal
#  13  c[12] DDB / tasa general 16%                          <-- notas de crédito
#  14  c[13] Valor total / importación por aduana bienes tangibles 16%
#  15  c[14] DDB / importación aduana bienes tangibles 16%
#  16  c[15] Valor total / importación bienes intangibles y servicios 16%
#  17  c[16] DDB / importación bienes intangibles y servicios 16%
#
# 3.3 IVA ACREDITABLE   [Exclusiv. gravadas, Asociado a proporción] x 5 secciones
#  18  c[17] Exclusivamente de actividades gravadas / RFN 8%  <-- IVA ACRED 8%
#  19  c[18] Asociado a proporción / RFN 8%
#  20  c[19] Exclusivamente de actividades gravadas / RFS 8%
#  21  c[20] Asociado a proporción / RFS 8%
#  22  c[21] Exclusivamente de actividades gravadas / 16%     <-- IVA ACRED 16%
#  23  c[22] Asociado a proporción / tasa general 16%
#  24  c[23] Exclusiv. gravadas / importación aduana tangibles 16%
#  25  c[24] Asociado a proporción / importación aduana tangibles 16%
#  26  c[25] Exclusiv. gravadas / importación intangibles y servicios 16%
#  27  c[26] Asociado a proporción / importación intangibles y servicios 16%
#
# 3.4 IVA NO ACREDITABLE  [Proporción, No cumple requisitos, Exentas, No objeto]
#                          x 5 secciones (RFN, RFS, 16%, imp. aduana, imp. intang.)
#  28-31  c[27..30]  ... / RFN 8%      (c[30] = "No objeto / RFN": DEBE IR EN 0)
#  32-35  c[31..34]  ... / RFS 8%
#  36-39  c[35..38]  ... / tasa general 16%
#  40-43  c[39..42]  ... / importación aduana bienes tangibles 16%
#  44-47  c[43..46]  ... / importación bienes intangibles y servicios 16%
#
# 3.5 Datos adicionales
#  48  c[47] IVA retenido por el contribuyente
#  49  c[48] Actos pagados en importación de bienes y servicios exentos
#  50  c[49] Actos o actividades pagados por los que no se pagará el IVA (exentos)
#  51  c[50] Demás actos o actividades pagados a la tasa del 0% de IVA
#  52  c[51] Actos no objeto del IVA realizados en territorio nacional
#  53  c[52] Actos no objeto del IVA por no contar con establecimiento en el país
#  54  c[53] Manifiesto efectos fiscales = "01" (Sí) / "02" (No)
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

    # Omitir terceros SIN IVA/base/retención: no son operaciones de proveedor con IVA
    # (p.ej. derechos/contribuciones de gobierno: ISN, IMSS, INFONAVIT, derechos estatales).
    # La DIOT (LIVA 32 / RLIVA 59) es solo para operaciones con proveedores que llevan IVA.
    # OJO: se REPORTA en el Log qué se omitió, para que el usuario verifique que ninguno
    # sea en realidad un proveedor EXENTO (renta/servicios médicos) que sí debería ir.
    filas, omitidos = [], []
    for v in acc.values():
        montos = (v["Base16"], v["DDB16"], v["IVA_Acred16"], v["Base8"],
                  v["IVA_Acred8"], v["BaseExento"], v["Base0"], v["RetIVA"])
        if all(abs(x) < 0.005 for x in montos):
            omitidos.append((v["RFC"], v["Nombre"]))
        else:
            filas.append(v)

    if omitidos:
        print(f"[AVISO] {len(omitidos)} tercero(s) SIN IVA/base omitidos de la DIOT "
              f"(no son operaciones de proveedor con IVA; revisa si alguno es proveedor EXENTO):")
        for rfc, nom in omitidos:
            print(f"   - {rfc}  {str(nom)[:45]}")

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
                c[5] = "USA"                           # 6 País (catálogo; default)

            # --- 3.2 Valor de los actos o actividades ---
            c[11] = _ent(r.get("Base16"))             # 12 Valor total pagado / 16%
            c[12] = _ent(r.get("DDB16"))              # 13 DDB / 16% (notas de crédito)
            # 8% frontera: sin dato RFN/RFS se asume RFN. Ver [[importar-xml-contpaqi]].
            c[7] = _ent(r.get("Base8"))               # 8  Valor total pagado / RFN 8%

            # --- 3.3 IVA ACREDITABLE (exclusivamente de actividades gravadas) ---
            c[21] = _ent(r.get("IVA_Acred16"))        # 22 IVA acred. gravado / 16%
            c[17] = _ent(r.get("IVA_Acred8"))         # 18 IVA acred. gravado / RFN 8%

            # --- 3.5 Datos adicionales ---
            c[47] = _ent(r.get("RetIVA"))             # 48 IVA retenido por el contribuyente
            # Exentos / tasa 0% (hoy 0: el parser no captura iva_exento aún).
            c[49] = _ent(r.get("BaseExento"))         # 50 Actos pagados exentos
            c[50] = _ent(r.get("Base0"))              # 51 Demás actos pagados a tasa 0%

            # 54 Manifiesto: se dio efectos fiscales a los CFDI del proveedor (01 = Sí).
            c[53] = "01"

            f.write("|".join(c) + "\n")
            n += 1

    print(f"[OK] DIOT (54 col, {n} terceros agregados) generada: {filename}")
    return filepath
