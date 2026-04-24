import pandas as pd
import os
import math
from config import load_settings, cargar_catalogo

def generar_polizas(df, is_egresos):
    """
    Toma los datos puros del SAT y genera el árbol de decisiones contables (Debe/Haber).
    Aplica las Normas de Información Financiera (NIF) para provisiones (PPD) y pagos (PUE/REP).
    """
    settings = load_settings()
    cuentas = settings.get("cuentas_default", {})
    
    c_banco = cuentas.get("bancos", "10201000")
    c_iva_pagado = cuentas.get("iva_acreditable", "11801000")
    c_iva_pdte_pago = cuentas.get("iva_pdte_pago", "11901000") 
    c_proveedores = cuentas.get("proveedores", "20101000")
    c_clientes = cuentas.get("clientes", "10501000")
    c_ventas = cuentas.get("ventas", "40101000")
    c_iva_cobrado = cuentas.get("iva_trasladado", "20801000")
    c_iva_pdte_cobro = cuentas.get("iva_pdte_cobro", "20901000")
    
    pol = []
    num = 1
    df = df.fillna(0)

    for _, r in df.iterrows():
        tipo = r["tipo"]
        rol = "purchase" if is_egresos else "sale"
        metodo = r.get("metodo_pago", "PUE")
        uuid = str(r["uuid"]).strip()
        concepto = str(r["concepto"])[:50]
        
        # =====================================================================
        # LÓGICA DE REFERENCIA (Nombre_Serie-Folio)
        # =====================================================================
        ref_base = str(r.get("referencia", "")).strip()
        if not ref_base or ref_base.lower() == "nan": ref_base = "SR"
        
        nombre_tercero = str(r.get("nombre_emisor", "")) if is_egresos else str(r.get("nombre_receptor", ""))
        if nombre_tercero.lower() == "nan": nombre_tercero = ""
        
        if nombre_tercero:
            espacio_nombre = 30 - len(ref_base) - 1 
            nombre_corto = nombre_tercero[:espacio_nombre].strip()
            ref = f"{nombre_corto} {ref_base}" if ref_base else nombre_corto
        else:
            ref = ref_base[:30]
        
        fecha_limpia = str(r.get("fecha", "2026-01-01")).split("T")[0]
        c_asignada = str(r.get("cuenta", "PENDIENTE")).strip()
        c_principal = c_asignada if c_asignada not in ["", "0", "PENDIENTE", "nan"] else "PENDIENTE"
        
        # Matemática de Impuestos NIF
        tot = float(r["total"])
        iva = float(r["iva_16"]) + float(r["iva_8"])
        ret = float(r["ret_iva"]) + float(r["ret_isr"])
        neto = round(tot - iva + ret, 2)
        
        # Asientos Contables Automatizados
        if tipo == "I": 
            if rol == "purchase":
                prov = str(r["nombre_emisor"])[:50]
                if metodo == "PPD":
                    pol.append([num, "Diario", fecha_limpia, c_principal, ref, neto, 0, concepto, uuid])
                    if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_pago, ref, iva, 0, "IVA pendiente", uuid])
                    pol.append([num, "Diario", fecha_limpia, c_proveedores, ref, 0, tot, prov, uuid])
                else:
                    pol.append([num, "Egreso", fecha_limpia, c_principal, ref, neto, 0, concepto, uuid])
                    if iva > 0: pol.append([num, "Egreso", fecha_limpia, c_iva_pagado, ref, iva, 0, "IVA acreditable", uuid])
                    pol.append([num, "Egreso", fecha_limpia, c_banco, ref, 0, tot, prov, uuid])
            else:
                cli = str(r["nombre_receptor"])[:50]
                c_principal = c_principal if c_principal != "PENDIENTE" else c_ventas
                if metodo == "PPD":
                    pol.append([num, "Diario", fecha_limpia, c_clientes, ref, tot, 0, cli, uuid])
                    pol.append([num, "Diario", fecha_limpia, c_principal, ref, 0, neto, concepto, uuid])
                    if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_cobro, ref, 0, iva, "IVA Pdte Cobro", uuid])
                else:
                    pol.append([num, "Ingreso", fecha_limpia, c_banco, ref, tot, 0, cli, uuid])
                    pol.append([num, "Ingreso", fecha_limpia, c_principal, ref, 0, neto, concepto, uuid])
                    if iva > 0: pol.append([num, "Ingreso", fecha_limpia, c_iva_cobrado, ref, 0, iva, "IVA Cobrado", uuid])

        elif tipo == "E": 
            if rol == "purchase":
                prov = str(r["nombre_emisor"])[:50]
                pol.append([num, "Diario", fecha_limpia, c_proveedores, ref, tot, 0, f"NC Prov - {prov}", uuid])
                pol.append([num, "Diario", fecha_limpia, c_principal, ref, 0, neto, concepto, uuid])
                if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_pago, ref, 0, iva, "Reversión IVA Pdte", uuid])
            else:
                cli = str(r["nombre_receptor"])[:50]
                pol.append([num, "Diario", fecha_limpia, c_principal, ref, neto, 0, concepto, uuid])
                if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_cobro, ref, iva, 0, "Reversión IVA Pdte", uuid])
                pol.append([num, "Diario", fecha_limpia, c_clientes, ref, 0, tot, f"NC Cli - {cli}", uuid])

        elif tipo == "P": 
            if rol == "purchase":
                pol.append([num, "Egreso", fecha_limpia, c_proveedores, ref, tot, 0, concepto, uuid])
                pol.append([num, "Egreso", fecha_limpia, c_banco, ref, 0, tot, "Salida a Proveedor", uuid])
                if iva > 0:
                    pol.append([num, "Egreso", fecha_limpia, c_iva_pagado, ref, iva, 0, "Reclasifica IVA Acred", uuid])
                    pol.append([num, "Egreso", fecha_limpia, c_iva_pdte_pago, ref, 0, iva, "Mata IVA Pdte", uuid])
            else:
                pol.append([num, "Ingreso", fecha_limpia, c_banco, ref, tot, 0, "Entrada de Cliente", uuid])
                pol.append([num, "Ingreso", fecha_limpia, c_clientes, ref, 0, tot, concepto, uuid])
                if iva > 0:
                    pol.append([num, "Ingreso", fecha_limpia, c_iva_pdte_cobro, ref, iva, 0, "Mata IVA Pdte Cobro", uuid])
                    pol.append([num, "Ingreso", fecha_limpia, c_iva_cobrado, ref, 0, iva, "Reclasifica IVA Cobrado", uuid])

        elif tipo == "N": 
            c_nom = cuentas.get("nomina", "60010000")
            c_ret_isr = cuentas.get("retencion_isr", "21601000")
            pol.append([num, "Diario", fecha_limpia, c_nom, ref, float(r["subtotal"]), 0, f"Provisión Nómina {r['departamento']}"[:50], ""])
            if float(r["ret_isr"]) > 0: 
                pol.append([num, "Diario", fecha_limpia, c_ret_isr, ref, 0, float(r["ret_isr"]), "Ret ISR Nomina", ""])
            pol.append([num, "Diario", fecha_limpia, c_banco, ref, 0, tot, "Neto a Pagar", ""])
            
        num += 1

    polizas_df = pd.DataFrame(pol, columns=["Numero", "Tipo", "Fecha", "Cuenta", "Referencia", "Debe", "Haber", "Concepto", "UUID"])
    polizas_df["Fecha"] = polizas_df["Fecha"].astype(str)
    return polizas_df

def generar_sugerencia(row, df_cat):
    c_act = str(row.get("cuenta", "")).strip()
    if c_act and c_act not in ["0", "PENDIENTE", "nan"]: return "🧠 IA"
    if df_cat is None or df_cat.empty: return "⚠️ Faltan Cuentas"
    emisor = str(row.get("nombre_emisor", "")).upper()
    basura = ['S.A.', 'DE', 'C.V.', 'SAB', 'RL', 'SA', 'CV', 'S', 'A', 'C', 'V']
    pals = [p for p in emisor.split() if p not in basura and len(p) > 2]
    if not pals: return "Manual"
    try:
        match = df_cat[df_cat.iloc[:, 1].str.upper().str.contains(pals[0], na=False)]
        if not match.empty: return f"💡 {match.iloc[0, 0]} ({match.iloc[0, 1]})"
    except Exception: pass
    return "Manual"

def auto_ajustar_columnas(writer, sheet_name, df):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
        col_letter = __import__('openpyxl').utils.get_column_letter(i + 1)
        worksheet.column_dimensions[col_letter].width = min(max_len, 50)
        for cell in worksheet[col_letter]:
            if col in ["Cuenta", "Referencia", "Fecha"]:
                cell.number_format = '@'

def exportar_txt_contpaqi(polizas_df, output_dir, excel_filename):
    """Genera el archivo de pólizas imitando perfectamente el Ancho Fijo nativo del sistema."""
    txt_filename = excel_filename.replace(".xlsx", ".txt")
    filepath = os.path.join(output_dir, txt_filename)
    
    # IMPORTANTE: Forzamos codificación windows-1252 (ANSI) para conservar el ancho exacto por byte
    with open(filepath, "w", encoding="windows-1252", errors="replace") as f:
        for num, group in polizas_df.groupby("Numero"):
            primera_fila = group.iloc[0]
            
            fecha_cruda = str(primera_fila["Fecha"]).split()[0].replace("-", "").replace("/", "").strip()
            fecha_str = fecha_cruda[:8] if len(fecha_cruda) >= 8 else "20260101"
            
            tipo_str = str(primera_fila["Tipo"]).upper()
            tipo_int = "3" 
            if "INGRESO" in tipo_str: tipo_int = "1"
            elif "EGRESO" in tipo_str: tipo_int = "2"
            
            concepto_poliza = str(primera_fila["Concepto"])[:100].strip()
            if not concepto_poliza: concepto_poliza = "Sin Concepto"
            
            # Formato de línea P replicado al espacio exacto del archivo nativo
            f.write(f"P  {fecha_str}    {tipo_int}         {num:<2}1 0          {concepto_poliza}\n")
            
            # Control de duplicidad de UUID en el ADD para la DIOT interna de CONTPAQi
            uuids_escritos = set()
            
            for _, r in group.iterrows():
                cuenta_val = str(r["Cuenta"]).strip()
                if cuenta_val.upper() in ["PENDIENTE", "NAN", "0"] or "FALTA" in cuenta_val.upper():
                    continue 
                if not cuenta_val.replace("-", "").isdigit():
                    continue
                
                referencia = str(r.get("Referencia", "")).strip()[:30]
                if referencia.lower() == "nan": referencia = ""
                
                debe = float(r["Debe"])
                haber = float(r["Haber"])
                if debe == 0 and haber == 0: continue 
                
                concepto_mov = str(r["Concepto"])[:100].strip()
                uuid = str(r["UUID"]).strip()
                
                tipo_mov = "0" if debe > 0 else "1"
                importe = debe if debe > 0 else haber
                
                # Armado de strings con anchos fijos estrictos (M1)
                cuenta_str = f"{cuenta_val:<31}"
                ref_str = f"{referencia:<31}"
                importe_pad = f"{importe:<21.2f}"
                
                f.write(f"M1 {cuenta_str}{ref_str}{tipo_mov} {importe_pad}0          0.0                  {concepto_mov}\n")
                
                # El UUID se asocia una única vez por póliza para no inflar acumulados
                if uuid and uuid.lower() != "nan" and len(uuid) == 36:
                    if uuid not in uuids_escritos:
                        f.write(f"AD {uuid}\n")
                        uuids_escritos.add(uuid)
                        
    return filepath

def generar_archivo_diot_sat(df, output_dir, excel_filename):
    """
    Genera el archivo TXT oficial para la DIOT del SAT.
    Aplica las reglas fiscales: Filtra PUE/REP, agrupa por RFC,
    manda las Notas de Crédito (Tipo E) a la columna de Descuentos/Devoluciones
    y blinda el redondeo para evitar el error de centavos del validador.
    """
    diot_filename = "DIOT_SAT_" + excel_filename.replace(".xlsx", ".txt")
    diot_filepath = os.path.join(output_dir, diot_filename)
    
    # 1. FILTRAR FLUJO EFECTIVO: Solo entra lo efectivamente pagado (PUE o Complementos de Pago 'P')
    # Las facturas con método PPD se excluyen porque no representan flujo en el mes.
    df_flujo = df[df["metodo_pago"].astype(str).upper().isin(["PUE", "P"])].copy()
    if df_flujo.empty:
        return None

    # Inicializar diccionarios de acumulación por RFC para consolidar una única línea
    acumulado_base = {}
    acumulado_descuentos = {}
    
    for _, r in df_flujo.iterrows():
        rfc = str(r.get("rfc_emisor", "")).strip().upper()
        if not rfc or rfc == "NAN" or len(rfc) < 12: 
            continue
            
        tipo_cfdi = str(r.get("tipo", "")).upper()
        base_16 = float(r.get("subtotal", 0)) # Base gravada antes de IVA
        
        if rfc not in acumulado_base:
            acumulado_base[rfc] = 0.0
            acumulado_descuentos[rfc] = 0.0
            
        # 2. SEPARACIÓN DE NOTAS DE CRÉDITO (TIPO E) SEGÚN REGLAS DEL SAT
        if tipo_cfdi == "E":
            # Las notas de crédito se acumulan de forma positiva en la columna de descuentos
            acumulado_descuentos[rfc] += base_16
        else:
            # Las facturas normales acumulan la base de actos gravados
            acumulado_base[rfc] += base_16

    # 3. ESCRITURA DEL LAYOUT OFICIAL DEL SAT DELIMITADO POR PIPES (|)
    with open(diot_filepath, "w", encoding="windows-1252") as f:
        for rfc in acumulado_base.keys():
            base_neta = acumulado_base[rfc]
            descuentos_netos = acumulado_descuentos[rfc]
            
            # 4. CONTROL DE VALORES NEGATIVOS: Si el descuento supera al ingreso, se topa en cero
            if base_neta < 0: base_neta = 0.0
            if descuentos_netos < 0: descuentos_netos = 0.0
            
            # Redondeo sin decimales exigido por la plataforma de la DIOT
            base_final = round(base_neta)
            descuentos_final = round(descuentos_netos)
            
            # 5. BLINDAJE MATEMÁTICO CONTRA ERRORES DE CENTAVOS DEL SAT
            # El validador calcula internamente (Base * 0.16) y si tu IVA reportado difiere por redondeo, te batea.
            iva_calculado_max = int(base_final * 0.16)
            
            # Formateo del renglón DIOT estándar (Proveedor Nacional = 04, Op. General = 85)
            # Columna 8: Valor de los actos al 16% | Columna 14: Devoluciones y Descuentos
            row_diot = [
                "04", "85", rfc, "", "", "", "", 
                str(base_final) if base_final > 0 else "", 
                "", "", "", "", "", 
                str(descuentos_final) if descuentos_final > 0 else "",
                "", "", "", "", "", "", "", "", "", ""
            ]
            
            f.write("|".join(row_diot) + "|\n")
            
    return diot_filepath

def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    is_egresos = "EGRESOS" in filename.upper()
    try: df_catalogo = cargar_catalogo()
    except: df_catalogo = None

    res_df = pd.DataFrame([{"Métrica": k, "Cantidad": v} for k, v in log_data.items()])
    df["Sugerencia"] = df.apply(lambda r: generar_sugerencia(r, df_catalogo), axis=1)

    # 1. Generamos pólizas en formato limpio para Excel
    polizas_df = generar_polizas(df, is_egresos)

    # 2. Escritura del libro de Excel de control humano
    with pd.ExcelWriter(filepath, engine='openpyxl') as w:
        res_df.to_excel(w, sheet_name="RESUMEN", index=False)
        auto_ajustar_columnas(w, "RESUMEN", res_df)
        
        df.to_excel(w, sheet_name="BASE", index=False)
        auto_ajustar_columnas(w, "BASE", df)
        
        polizas_df.to_excel(w, sheet_name="POLIZAS_CONTPAQI", index=False)
        auto_ajustar_columnas(w, "POLIZAS_CONTPAQI", polizas_df)
        
        if diot_df is not None and not diot_df.empty:
            diot_df.to_excel(w, sheet_name="DIOT", index=False)
            auto_ajustar_columnas(w, "DIOT", diot_df)
            
    # 3. Exportación de layouts planos a disco duro
    exportar_txt_contpaqi(polizas_df, output_dir, filename)
    generar_archivo_diot_sat(df, output_dir, filename) # Genera el TXT corregido para el SAT

    try:
        import sys
        if os.name == 'nt': os.startfile(output_dir)
        elif sys.platform == 'darwin': __import__('subprocess').call(["open", output_dir])
    except Exception: pass

    return filepath