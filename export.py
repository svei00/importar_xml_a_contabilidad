import pandas as pd
import os
from config import load_settings, cargar_catalogo

# ==========================================
# CONFIGURACIÓN DE DIARIOS PARA CONTPAQI
# ==========================================
# Forzamos el diario a "21" para cumplir con la regla de tu empresa en CONTPAQi
DIARIO_POLIZA = "21"   
DIARIO_MOVIMIENTO = "21"
SEGMENTO_NEGOCIO = "0"

def generar_polizas(df, is_egresos):
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
        
        ref_base = str(r.get("referencia", "")).strip().replace(" ", "_")
        if not ref_base or ref_base == "nan": ref_base = "SR"
        
        nombre_tercero = str(r.get("nombre_emisor", "")) if is_egresos else str(r.get("nombre_receptor", ""))
        if nombre_tercero.lower() == "nan": nombre_tercero = ""
        nombre_tercero = nombre_tercero.replace(" ", "_") 
        
        if nombre_tercero:
            espacio_nombre = 30 - len(ref_base) - 1 
            nombre_corto = nombre_tercero[:espacio_nombre].strip("_")
            ref = f"{nombre_corto}_{ref_base}" if ref_base else nombre_corto
        else:
            ref = ref_base[:30]
        
        fecha_limpia = str(r.get("fecha", "2026-01-01")).split("T")[0]
        
        c_asignada = str(r.get("cuenta", "PENDIENTE")).strip()
        c_principal = c_asignada if c_asignada not in ["", "0", "PENDIENTE", "nan"] else "PENDIENTE"
        
        tot = float(r["total"])
        iva = float(r["iva_16"]) + float(r["iva_8"])
        ret = float(r["ret_iva"]) + float(r["ret_isr"])
        neto = round(tot - iva + ret, 2)
        
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
                c_principal = c_principal if c_principal != "PENDIENTE" else c_ventas
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
    txt_filename = excel_filename.replace(".xlsx", ".txt")
    filepath = os.path.join(output_dir, txt_filename)
    
    with open(filepath, "w", encoding="windows-1252", errors="replace") as f:
        for num, group in polizas_df.groupby("Numero"):
            primera_fila = group.iloc[0]
            
            try:
                fecha_str = pd.to_datetime(primera_fila["Fecha"]).strftime("%Y%m%d")
            except:
                fecha_str = "20260101"
            
            tipo_str = str(primera_fila["Tipo"]).upper()
            tipo_int = "3" 
            if "INGRESO" in tipo_str: tipo_int = "1"
            elif "EGRESO" in tipo_str: tipo_int = "2"
            
            concepto_poliza = str(primera_fila["Concepto"])[:100].strip()
            if not concepto_poliza: concepto_poliza = "Sin_Concepto"
            
            f.write(f"P {fecha_str} {tipo_int} {num} 1 {DIARIO_POLIZA} {concepto_poliza}\n")
            
            for _, r in group.iterrows():
                cuenta_val = r["Cuenta"]
                if pd.isna(cuenta_val): cuenta_val = "PENDIENTE"
                if isinstance(cuenta_val, float): cuenta_val = int(cuenta_val)
                cuenta = str(cuenta_val).strip()
                
                if cuenta == "PENDIENTE" or "FALTA" in cuenta.upper():
                    continue 
                
                referencia = str(r.get("Referencia", "SR")).strip().replace(" ", "_")[:30]
                if not referencia or referencia == "nan": referencia = "SR"
                
                debe = float(r["Debe"])
                haber = float(r["Haber"])
                
                concepto_mov = str(r["Concepto"])[:100].strip()
                if not concepto_mov: concepto_mov = "Sin_Concepto"
                
                uuid = str(r["UUID"]).strip()
                
                tipo_mov = "0" if debe > 0 else "1"
                importe = debe if debe > 0 else haber
                
                if importe == 0: continue 
                
                f.write(f"M {cuenta} {referencia} {tipo_mov} {importe:.2f} {DIARIO_MOVIMIENTO} {SEGMENTO_NEGOCIO} {concepto_mov}\n")
                
                if uuid and uuid != "nan" and len(uuid) == 36:
                    f.write(f"AD {uuid}\n")
                    
    return filepath

def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    is_egresos = "EGRESOS" in filename.upper()
    try: df_catalogo = cargar_catalogo()
    except: df_catalogo = None

    res_df = pd.DataFrame([{"Métrica": k, "Cantidad": v} for k, v in log_data.items()])
    df["Sugerencia"] = df.apply(lambda r: generar_sugerencia(r, df_catalogo), axis=1)

    polizas_df = generar_polizas(df, is_egresos)

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
            
    exportar_txt_contpaqi(polizas_df, output_dir, filename)

    try:
        import sys
        if os.name == 'nt': os.startfile(output_dir)
        elif sys.platform == 'darwin': __import__('subprocess').call(["open", output_dir])
    except Exception: pass

    return filepath