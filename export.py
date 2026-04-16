# export.py
import pandas as pd
import os
from config import load_settings, cargar_catalogo

def generar_polizas(df):
    settings = load_settings()
    cuentas_def = settings.get("cuentas_default", {})
    
    # Cuentas dinámicas desde settings.json (¡Cero hardcoding!)
    c_banco = cuentas_def.get("bancos", "FALTA_CUENTA_BANCO")
    c_iva_pagado = cuentas_def.get("iva_acreditable", "FALTA_CUENTA_IVA")
    c_iva_pdte_pago = cuentas_def.get("iva_pdte_pago", "FALTA_CUENTA_IVA_PDTE")
    c_proveedores = cuentas_def.get("proveedores", "FALTA_CUENTA_PROV")
    c_clientes = cuentas_def.get("clientes", "FALTA_CUENTA_CLI")
    c_ventas = cuentas_def.get("ventas", "FALTA_CUENTA_VENTAS")
    c_iva_cobrado = cuentas_def.get("iva_trasladado", "FALTA_IVA_TRASLADADO")
    c_iva_pdte_cobro = cuentas_def.get("iva_pdte_cobro", "FALTA_IVA_PDTE_COBRO")
    
    pol = []
    num = 1
    df = df.fillna(0)

    # --- 1. FACTURAS NORMALES (I, E) ---
    facturas = df[df['tipo'].isin(['I', 'E'])]
    
    for _, r in facturas.iterrows():
        concepto_recortado = str(r["concepto"])[:50]
        cuenta_asignada = str(r.get("cuenta", "")).strip()
        c_gasto_ingreso = cuenta_asignada if cuenta_asignada and cuenta_asignada != "0" else "PENDIENTE"
        
        total = float(r["total"])
        iva_16 = float(r["iva_16"])
        iva_8 = float(r["iva_8"])
        ret_iva = float(r["ret_iva"])
        ret_isr = float(r["ret_isr"])
        monto_ajustado = round(total - iva_16 - iva_8 + ret_iva + ret_isr, 2)
        
        if r["tipo"] == "E":
            if r.get("metodo_pago", "PUE") == "PPD":
                pol.append([num, "Diario", c_gasto_ingreso, monto_ajustado, 0, concepto_recortado, r["uuid"]])
                if iva_16 > 0: pol.append([num, "Diario", c_iva_pdte_pago, iva_16, 0, "IVA Pdte Pago", r["uuid"]])
                pol.append([num, "Diario", c_proveedores, 0, total, str(r["nombre_emisor"])[:50], r["uuid"]])
            else: 
                pol.append([num, "Egreso", c_gasto_ingreso, monto_ajustado, 0, concepto_recortado, r["uuid"]])
                if iva_16 > 0: pol.append([num, "Egreso", c_iva_pagado, iva_16, 0, "IVA Acreditable", r["uuid"]])
                pol.append([num, "Egreso", c_banco, 0, total, str(r["nombre_emisor"])[:50], r["uuid"]])

        elif r["tipo"] == "I":
            c_gasto_ingreso = c_gasto_ingreso if c_gasto_ingreso != "PENDIENTE" else c_ventas 
            if r.get("metodo_pago", "PUE") == "PPD":
                pol.append([num, "Diario", c_clientes, total, 0, str(r["nombre_receptor"])[:50], r["uuid"]])
                pol.append([num, "Diario", c_gasto_ingreso, 0, monto_ajustado, concepto_recortado, r["uuid"]])
                if iva_16 > 0: pol.append([num, "Diario", c_iva_pdte_cobro, 0, iva_16, "IVA Pdte Cobro", r["uuid"]])
            else: 
                pol.append([num, "Ingreso", c_banco, total, 0, str(r["nombre_receptor"])[:50], r["uuid"]])
                pol.append([num, "Ingreso", c_gasto_ingreso, 0, monto_ajustado, concepto_recortado, r["uuid"]])
                if iva_16 > 0: pol.append([num, "Ingreso", c_iva_cobrado, 0, iva_16, "IVA Cobrado", r["uuid"]])
        num += 1

    # --- 2. NÓMINAS AGRUPADAS (N) ---
    nominas = df[df['tipo'] == 'N']
    if not nominas.empty:
        c_nomina = cuentas_def.get("nomina", "FALTA_CUENTA_NOMINA")
        c_impuestos_ret = cuentas_def.get("retenciones", "FALTA_CUENTA_RETENCIONES")
        
        for depto, grupo in nominas.groupby('departamento'):
            total_sueldos = float(grupo['subtotal'].sum())
            total_neto = float(grupo['total'].sum())
            total_ret_isr = float(grupo['ret_isr'].sum())
            
            pol.append([num, "Diario", c_nomina, total_sueldos, 0, f"Provisión Nómina {depto}"[:50], ""])
            if total_ret_isr > 0:
                pol.append([num, "Diario", c_impuestos_ret, 0, total_ret_isr, f"Ret ISR Nomina {depto}", ""])
            pol.append([num, "Diario", c_banco, 0, total_neto, f"Neto a Pagar {depto}", ""])
            num += 1

    # --- 3. PAGOS / REP (P) ---
    pagos = df[df['tipo'] == 'P']
    if not pagos.empty:
        for _, r in pagos.iterrows():
            total = float(r["total"])
            iva_16 = float(r["iva_16"])
            concepto = f"Pago a Proveedor REP - {str(r['nombre_emisor'])[:30]}"
            
            pol.append([num, "Egreso", c_proveedores, total, 0, concepto, r["uuid"]])
            if iva_16 > 0:
                pol.append([num, "Egreso", c_iva_pagado, iva_16, 0, "Traspaso IVA Pagado", r["uuid"]])
                pol.append([num, "Egreso", c_iva_pdte_pago, 0, iva_16, "Cance. IVA Pdte", r["uuid"]])
            pol.append([num, "Egreso", c_banco, 0, total, "Pago desde Banco", r["uuid"]])
            num += 1

    return pd.DataFrame(pol, columns=["Numero", "Tipo", "Cuenta", "Debe", "Haber", "Concepto", "UUID"])

def generar_sugerencia_dinamica(row, df_catalogo):
    """Sugerencia inteligente leyendo tu catálogo real (Cuentas.txt)"""
    cuenta_actual = str(row.get("cuenta", "")).strip()
    
    if cuenta_actual and cuenta_actual not in ["0", "PENDIENTE"]:
        return "🧠 Asignado por IA"

    if df_catalogo is None or df_catalogo.empty:
        return "⚠️ Carga tu catálogo para ver sugerencias"

    nombre_emisor = str(row.get("nombre_emisor", "")).upper()
    palabras_basura = ['S.A.', 'DE', 'C.V.', 'SAB', 'RL', 'SA', 'CV', 'S', 'A', 'C', 'V']
    palabras = [p for p in nombre_emisor.split() if p not in palabras_basura and len(p) > 2]
    
    if not palabras:
        return "Requiere Clasificación Manual"
        
    palabra_clave = palabras[0]

    try:
        coincidencias = df_catalogo[df_catalogo.iloc[:, 1].str.upper().str.contains(palabra_clave, na=False)]
        if not coincidencias.empty:
            cuenta_sug = coincidencias.iloc[0, 0] 
            nombre_sug = coincidencias.iloc[0, 1] 
            return f"💡 Encontrado en Catálogo: {cuenta_sug} ({nombre_sug})"
    except Exception:
        pass
        
    return "Requiere Clasificación Manual"

def auto_ajustar_columnas_openpyxl(writer, sheet_name, df):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
        max_len = min(max_len, 50) 
        from openpyxl.utils import get_column_letter
        col_letter = get_column_letter(i + 1)
        worksheet.column_dimensions[col_letter].width = max_len

# ¡NOTA: Se regresó a 5 parámetros para que sea 100% compatible con tu main.py actual!
def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    
    # Carga el catálogo internamente sin molestar a main.py
    df_catalogo = cargar_catalogo()
    
    resumen_df = pd.DataFrame([
        {"Métrica": "Total de XMLs Analizados", "Cantidad": log_data.get("total", 0)},
        {"Métrica": "Facturas Procesadas (PUE/PPD)", "Cantidad": log_data.get("validas", 0)},
        {"Métrica": "Nóminas Agrupadas (Sin UUID)", "Cantidad": log_data.get("nominas", 0)},
        {"Métrica": "CFDI de Pagos (REPs) Procesados", "Cantidad": log_data.get("pagos", 0)},
        {"Métrica": "CFDI Cancelados (Revisar)", "Cantidad": log_data.get("cancelados", 0)},
        {"Métrica": "⚠️ RECORDATORIO", "Cantidad": "SUBE LOS XML AL ADD ANTES DE IMPORTAR"}
    ])

    df["Sugerencia_Catálogo"] = df.apply(lambda row: generar_sugerencia_dinamica(row, df_catalogo), axis=1)

    with pd.ExcelWriter(filepath, engine='openpyxl') as w:
        resumen_df.to_excel(w, sheet_name="RESUMEN_LOG", index=False)
        auto_ajustar_columnas_openpyxl(w, "RESUMEN_LOG", resumen_df)

        df.to_excel(w, sheet_name="FACTURAS_BASE", index=False)
        auto_ajustar_columnas_openpyxl(w, "FACTURAS_BASE", df)

        polizas_df = generar_polizas(df)
        polizas_df.to_excel(w, sheet_name="POLIZAS_CONTPAQI", index=False)
        auto_ajustar_columnas_openpyxl(w, "POLIZAS_CONTPAQI", polizas_df)
        
        if diot_df is not None and not diot_df.empty:
            diot_df.to_excel(w, sheet_name="DIOT_LISTA", index=False)
            auto_ajustar_columnas_openpyxl(w, "DIOT_LISTA", diot_df)
            
    # --- MENSAJE DE ÉXITO Y APERTURA DE CARPETA AUTOMÁTICA ---
    print("\n" + "="*50)
    print("✅ ¡PROCESO FINALIZADO CON ÉXITO!")
    print(f"📁 Excel generado en: {output_dir.replace(chr(92), '/')}")
    print(f"📄 Nombre: {filename}")
    print("="*50 + "\n")
    
    try:
        # Esto abre mágicamente la carpeta en Windows al terminar
        if os.name == 'nt':
            os.startfile(output_dir)
    except Exception:
        pass
        
    return filepath