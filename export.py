import pandas as pd
import os
import re
from config import load_settings, cargar_catalogo
from terceros import construir_referencia

def generar_polizas(df, is_egresos, aliases=None):
    """
    Toma los datos puros del SAT y genera el árbol de decisiones contables (Debe/Haber).
    Aplica las Normas de Información Financiera (NIF) para provisiones (PPD) y pagos (PUE/REP).
    """
    settings = load_settings()
    cuentas = settings.get("cuentas_default", {})
    
    c_banco = cuentas.get("bancos", "10201000")
    c_iva_pagado = cuentas.get("iva_acreditable", "11801000")
    c_iva_pdte_pago = cuentas.get("iva_pdte_pago", "11901000") 
    # FIX: Se cambia cuenta de mayor 20101000 por cuenta afectable 20101999 por defecto
    c_proveedores = cuentas.get("proveedores", "20101999") 
    c_clientes = cuentas.get("clientes", "10501001")
    c_ventas = cuentas.get("ventas", "40101000")
    c_iva_cobrado = cuentas.get("iva_trasladado", "20801000")
    c_iva_pdte_cobro = cuentas.get("iva_pdte_cobro", "20901000")
    
    aliases = aliases or {}
    pol = []
    num = 1
    df = df.fillna(0)

    for _, r in df.iterrows():
        tipo = r["tipo"]
        rol = "purchase" if is_egresos else "sale"
        metodo = r.get("metodo_pago", "PUE")
        uuid = str(r["uuid"]).strip()
        concepto = str(r["concepto"])[:50]

        # Referencia = RFC-SHORTNAME (clave consistente y filtrable en Auxiliares).
        # El folio de la factura se conserva en el Concepto, no en la Referencia.
        ref_base = str(r.get("referencia", "")).strip()
        if not ref_base or ref_base.lower() == "nan": ref_base = "SR"

        rfc_tercero = str(r.get("rfc_emisor", "")) if is_egresos else str(r.get("rfc_receptor", ""))
        nombre_tercero = str(r.get("nombre_emisor", "")) if is_egresos else str(r.get("nombre_receptor", ""))
        if nombre_tercero.lower() == "nan": nombre_tercero = ""

        ref = construir_referencia(rfc_tercero, nombre_tercero, aliases)
        if not ref:
            # Sin RFC válido (p.ej. nómina): se conserva el folio como referencia.
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
    """Generador TXT Estricto para CONTPAQi (Formato Tabular de Ancho Fijo)"""
    txt_filename = "Polizas_CONTPAQi_" + excel_filename.replace(".xlsx", ".txt")
    filepath = os.path.join(output_dir, txt_filename)
    
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
            
            # FIX: Cabecera P sin GUID interno falso. Termina exactamente en 11 0 0
            f.write(f"P  {fecha_str}    {tipo_int}         {num:<2}1 0          {concepto_poliza:<100} 11 0 0 \n")
            
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
                uuid_mov = str(r["UUID"]).strip().upper()
                
                tipo_mov = "0" if debe > 0 else "1"
                importe = debe if debe > 0 else haber
                
                # CONTPAQi lee los importes en columnas FIJAS. La cuenta debe ocupar
                # 31 caracteres (no 30): con 30 todo se recorre 1 a la izquierda y
                # CONTPAQi se "come" el primer dígito del importe (3915.00 -> 915.00),
                # dejando la póliza descuadrada -> cuenta de cuadre / pólizas rechazadas.
                cuenta_str = f"{cuenta_val:<31}"
                ref_str = f"{referencia:<31}"
                importe_str = f"{importe:.2f}"
                importe_pad = f"{importe_str:<21}"
                
                # FIX: M1 termina en el concepto, sin inyectar GUID falso
                f.write(f"M1 {cuenta_str}{ref_str}{tipo_mov} {importe_pad}0          0.0                  {concepto_mov:<106}\n")
                
                # FIX: El UUID va exclusivamente en la asociación digital (AD)
                if len(uuid_mov) == 36:
                    f.write(f"AD {uuid_mov}\n")
                        
    return filepath

def generar_archivo_diot_sat(df, output_dir, excel_filename):
    """
    Genera el archivo TXT Batch de la DIOT oficial del SAT.
    Usa dos espacios para el Normal (ej. "03. Mar 2026  N DIOT.txt").
    Si el N ya existe, escanea la carpeta y genera el C1, C2, etc.
    """
    import re
    import os
    
    meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    match = re.search(r'_(\d{4})_(\d{2})', excel_filename)
    if match:
        year = match.group(1)
        month_num = int(match.group(2))
        month_str = meses[month_num - 1]
        base_name = f"{month_num:02d}. {month_str} {year}"
        
        # Archivo Normal con DOS ESPACIOS estrictos
        n_filename = f"{base_name}  N DIOT.txt"
        diot_filepath = os.path.join(output_dir, n_filename)
        
        # Contador Automático de Complementarias
        if os.path.exists(diot_filepath):
            counter = 1
            while True:
                c_filename = f"{base_name} C{counter} DIOT.txt"
                diot_filepath = os.path.join(output_dir, c_filename)
                if not os.path.exists(diot_filepath):
                    break
                counter += 1
    else:
        diot_filepath = os.path.join(output_dir, "DIOT_SAT_Fallback.txt")
        
    # Filtro estricto: PUE (Ingresos directos), P (Pagos/REPs) y E (Notas de Crédito)
    df_flujo = df[
        (df["metodo_pago"].astype(str).str.strip().str.upper() == "PUE") | 
        (df["tipo"].astype(str).str.strip().str.upper() == "P") | 
        (df["tipo"].astype(str).str.strip().str.upper() == "E")
    ].copy()
    
    if df_flujo.empty:
        return None

    acumulado_base = {}
    acumulado_descuentos = {}
    
    for _, r in df_flujo.iterrows():
        rfc = str(r.get("rfc_emisor", "")).strip().upper()
        if not rfc or rfc == "NAN" or len(rfc) < 12: 
            continue
            
        tipo_cfdi = str(r.get("tipo", "")).strip().upper()
        base_16 = float(r.get("subtotal", 0)) 
        
        # Cálculo matemático para la Base de los REPs (Subtotal en 0)
        if tipo_cfdi == "P" and base_16 == 0:
            tot_p = float(r.get("total", 0))
            iva_p = float(r.get("iva_16", 0))
            ret_p = float(r.get("ret_isr", 0)) + float(r.get("ret_iva", 0))
            
            if iva_p > 0:
                base_16 = tot_p - iva_p + ret_p
            elif tot_p > 0:
                base_16 = tot_p / 1.16
        
        descuento_cfdi = float(r.get("descuento", 0)) if "descuento" in r else 0.0
        
        if rfc not in acumulado_base:
            acumulado_base[rfc] = 0.0
            acumulado_descuentos[rfc] = 0.0
            
        if tipo_cfdi == "E":
            acumulado_descuentos[rfc] += base_16
        else:
            acumulado_base[rfc] += base_16
            acumulado_descuentos[rfc] += descuento_cfdi

    with open(diot_filepath, "w", encoding="windows-1252") as f:
        for rfc in acumulado_base.keys():
            base = round(acumulado_base[rfc])
            desc = round(acumulado_descuentos[rfc])
            
            if base < 0: base = 0
            if desc < 0: desc = 0
            
            if base == 0 and desc == 0:
                continue
                
            base_neta = base - desc
            if base_neta < 0: base_neta = 0
            iva_acreditable = round(base_neta * 0.16)
            
            # EL FIX ESTÁ AQUÍ: 54 elementos = 53 tuberías = 54 campos exactos.
            row = [""] * 54 
            row[0] = "04"  
            row[1] = "85"  
            row[2] = rfc   
            
            if base > 0:
                row[11] = str(base)              
            if desc > 0:
                row[12] = str(desc)              
            if iva_acreditable > 0:
                row[21] = str(iva_acreditable)   
            
            # Ya NO imprimimos el "01" al final
            f.write("|".join(row) + "\n")
            
    return diot_filepath

def sincronizar_aliases(empresa_rfc, df, is_egresos):
    """
    Da de alta (con apodo por defecto) cada tercero nuevo visto en este lote,
    para que aparezca en el administrador de alias listo para renombrar.
    Devuelve el diccionario {rfc: shortname} ya vigente.
    """
    if not empresa_rfc:
        return {}
    from db import ensure_alias, get_aliases
    from terceros import normalizar_shortname
    col_rfc = "rfc_emisor" if is_egresos else "rfc_receptor"
    col_nom = "nombre_emisor" if is_egresos else "nombre_receptor"
    for _, r in df.iterrows():
        if str(r.get("tipo", "")) == "N":   # nómina no tiene tercero proveedor
            continue
        rfc = str(r.get(col_rfc, "")).strip().upper()
        nombre = str(r.get(col_nom, ""))
        ensure_alias(empresa_rfc, rfc, nombre, normalizar_shortname(nombre))
    return get_aliases(empresa_rfc)

def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    is_egresos = "EGRESOS" in filename.upper()
    try: df_catalogo = cargar_catalogo()
    except: df_catalogo = None

    # Empresa = 3er segmento del nombre de archivo (Polizas_<TIPO>_<RFC>_<AAAA>_<MM>.xlsx)
    partes = os.path.basename(filename).split("_")
    empresa_rfc = partes[2] if len(partes) >= 3 else ""
    try: aliases = sincronizar_aliases(empresa_rfc, df, is_egresos)
    except Exception: aliases = {}

    res_df = pd.DataFrame([{"Métrica": k, "Cantidad": v} for k, v in log_data.items()])
    df["Sugerencia"] = df.apply(lambda r: generar_sugerencia(r, df_catalogo), axis=1)

    polizas_df = generar_polizas(df, is_egresos, aliases)

    with pd.ExcelWriter(filepath, engine='openpyxl') as w:
        res_df.to_excel(w, sheet_name="RESUMEN", index=False)
        auto_ajustar_columnas(w, "RESUMEN", res_df)
        
        df.to_excel(w, sheet_name="BASE", index=False)
        auto_ajustar_columnas(w, "BASE", df)
        
        polizas_df.to_excel(w, sheet_name="POLIZAS_CONTPAQI", index=False)
        auto_ajustar_columnas(w, "POLIZAS_CONTPAQI", polizas_df)
            
    # Exportación final orquestada: Lanza Pólizas y Lanza DIOT
    exportar_txt_contpaqi(polizas_df, output_dir, filename)
    generar_archivo_diot_sat(df, output_dir, filename)

    try:
        import sys
        if os.name == 'nt': os.startfile(output_dir)
        elif sys.platform == 'darwin': __import__('subprocess').call(["open", output_dir])
    except Exception: pass

    return filepath