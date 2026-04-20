import pandas as pd
import os
from config import load_settings, cargar_catalogo

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
        
        # OBTENEMOS LA REFERENCIA (Serie+Folio, VIN, o Nombre de Proveedor)
        ref = str(r.get("referencia", "SR"))[:20] 
        
        # Extraemos la fecha limpia (YYYY-MM-DD)
        fecha_limpia = str(r.get("fecha", "2026-01-01")).split("T")[0]
        
        c_asignada = str(r.get("cuenta", "PENDIENTE")).strip()
        c_principal = c_asignada if c_asignada not in ["", "0", "PENDIENTE"] else "PENDIENTE"
        
        tot = float(r["total"])
        iva = float(r["iva_16"]) + float(r["iva_8"])
        ret = float(r["ret_iva"]) + float(r["ret_isr"])
        neto = round(tot - iva + ret, 2)
        
        # 1. TIPO "I" (INGRESOS NORMALES)
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

        # 2. TIPO "E" (EGRESOS / NOTAS DE CRÉDITO)
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

        # 3. TIPO "P" (PAGOS / REPs)
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

        # 4. TIPO "N" (NÓMINAS)
        elif tipo == "N":
            c_nom = cuentas.get("nomina", "60010000")
            c_ret_isr = cuentas.get("retencion_isr", "21601000")
            pol.append([num, "Diario", fecha_limpia, c_nom, ref, float(r["subtotal"]), 0, f"Provisión Nómina {r['departamento']}"[:50], ""])
            if float(r["ret_isr"]) > 0: 
                pol.append([num, "Diario", fecha_limpia, c_ret_isr, ref, 0, float(r["ret_isr"]), "Ret ISR Nomina", ""])
            pol.append([num, "Diario", fecha_limpia, c_banco, ref, 0, tot, "Neto a Pagar", ""])
            
        num += 1

    # Agregamos la columna "Referencia" al Dataframe
    return pd.DataFrame(pol, columns=["Numero", "Tipo", "Fecha", "Cuenta", "Referencia", "Debe", "Haber", "Concepto", "UUID"])

def generar_sugerencia(row, df_cat):
    c_act = str(row.get("cuenta", "")).strip()
    if c_act and c_act not in ["0", "PENDIENTE"]: return "🧠 IA"
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
        worksheet.column_dimensions[__import__('openpyxl').utils.get_column_letter(i + 1)].width = min(max_len, 50)

def exportar_txt_contpaqi(polizas_df, output_dir, excel_filename):
    """Genera el archivo TXT nativo para Carga Batch en CONTPAQi."""
    txt_filename = excel_filename.replace(".xlsx", ".txt")
    filepath = os.path.join(output_dir, txt_filename)
    
    with open(filepath, "w", encoding="windows-1252", errors="replace") as f:
        for num, group in polizas_df.groupby("Numero"):
            primera_fila = group.iloc[0]
            
            fecha_str = str(primera_fila["Fecha"]).replace("-", "")
            if len(fecha_str) != 8: fecha_str = "20260101"
            
            tipo_str = str(primera_fila["Tipo"]).upper()
            tipo_int = "3" 
            if "INGRESO" in tipo_str: tipo_int = "1"
            elif "EGRESO" in tipo_str: tipo_int = "2"
            
            concepto_poliza = str(primera_fila["Concepto"])[:100]
            
            # Encabezado sin el "0" que causaba el crash de Diarios
            f.write(f"P {fecha_str} {tipo_int} {num} 1   {concepto_poliza}\n")
            
            for _, r in group.iterrows():
                # Conservamos los guiones si existen
                cuenta = str(r["Cuenta"]).strip()
                if cuenta == "PENDIENTE" or "FALTA" in cuenta.upper():
                    continue 
                
                # INYECTAR LA REFERENCIA: Reemplazamos espacios por guiones bajos para no romper las columnas del TXT
                referencia = str(r.get("Referencia", "SR")).strip().replace(" ", "_")[:20]
                if not referencia: referencia = "SR"
                
                debe = float(r["Debe"])
                haber = float(r["Haber"])
                concepto_mov = str(r["Concepto"])[:100]
                uuid = str(r["UUID"]).strip()
                
                tipo_mov = "0" if debe > 0 else "1"
                importe = debe if debe > 0 else haber
                
                if importe == 0: continue 
                
                # LA NUEVA ESTRUCTURA INCLUYE LA REFERENCIA DESPUÉS DE LA CUENTA
                f.write(f"M {cuenta} {referencia} {tipo_mov} {importe:.2f} 0 0 {concepto_mov}\n")
                
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

    # 1. Generamos el DataFrame maestro de pólizas (Ahora incluye Referencia)
    polizas_df = generar_polizas(df, is_egresos)

    # 2. Generamos el Excel
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
            
    # 3. GENERAMOS EL TXT NATIVO DE CONTPAQI (Con la nueva Referencia)
    exportar_txt_contpaqi(polizas_df, output_dir, filename)

    try:
        import sys
        if os.name == 'nt': os.startfile(output_dir)
        elif sys.platform == 'darwin': __import__('subprocess').call(["open", output_dir])
    except Exception: pass

    return filepath