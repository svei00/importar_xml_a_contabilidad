# export.py
import pandas as pd
import os
from config import load_settings

def generar_polizas(df):
    settings = load_settings()
    cuentas_def = settings.get("cuentas_default", {})
    
    # Cuentas base
    c_banco = cuentas_def.get("bancos", "10201000")
    c_iva_pagado = cuentas_def.get("iva_acreditable", "11801000")
    c_iva_pdte_pago = cuentas_def.get("iva_pdte_pago", "11802000")
    c_proveedores = cuentas_def.get("proveedores", "20101000")
    c_clientes = cuentas_def.get("clientes", "10501000")
    c_ventas = cuentas_def.get("ventas", "40101000")
    c_iva_cobrado = cuentas_def.get("iva_trasladado", "20801000")
    c_iva_pdte_cobro = cuentas_def.get("iva_pdte_cobro", "20802000")
    
    pol = []
    num = 1

    # --- 1. PROCESAR INGRESOS Y EGRESOS ---
    facturas = df[df['tipo'].isin(['I', 'E'])]
    
    for _, r in facturas.iterrows():
        concepto_recortado = str(r["concepto"])[:50]
        
        # EL TRUCO DEL CUADRE (Absorber IEPS y Ajustes en el Gasto/Ingreso)
        # Gasto Real = Total - IVA + Retenciones
        monto_principal_ajustado = round(r["total"] - r["iva_16"] - r["iva_8"] + r["ret_iva"] + r["ret_isr"], 2)
        
        # LOGICA EGRESOS (COMPRAS/GASTOS)
        if r["tipo"] == "E":
            c_gasto = r["cuenta"]
            
            if r["metodo_pago"] == "PPD":
                # PROVISIÓN (Diario)
                pol.append([num, "Diario", c_gasto, monto_principal_ajustado, 0, concepto_recortado, r["uuid"]])
                if r["iva_16"] > 0:
                    pol.append([num, "Diario", c_iva_pdte_pago, r["iva_16"], 0, "IVA Pdte Pago", r["uuid"]])
                pol.append([num, "Diario", c_proveedores, 0, r["total"], r["nombre_emisor"][:50], r["uuid"]])
            else: 
                # PAGO INMEDIATO (Egreso PUE)
                pol.append([num, "Egreso", c_gasto, monto_principal_ajustado, 0, concepto_recortado, r["uuid"]])
                if r["iva_16"] > 0:
                    pol.append([num, "Egreso", c_iva_pagado, r["iva_16"], 0, "IVA Acreditable Pagado", r["uuid"]])
                pol.append([num, "Egreso", c_banco, 0, r["total"], r["nombre_emisor"][:50], r["uuid"]])

        # LOGICA INGRESOS (VENTAS)
        elif r["tipo"] == "I":
            c_ingreso = r["cuenta"] if r["cuenta"] != "60000000" else c_ventas 
            
            if r["metodo_pago"] == "PPD":
                # PROVISIÓN (Diario)
                pol.append([num, "Diario", c_clientes, r["total"], 0, r["nombre_receptor"][:50], r["uuid"]])
                pol.append([num, "Diario", c_ingreso, 0, monto_principal_ajustado, concepto_recortado, r["uuid"]])
                if r["iva_16"] > 0:
                    pol.append([num, "Diario", c_iva_pdte_cobro, 0, r["iva_16"], "IVA Pdte Cobro", r["uuid"]])
            else: 
                # COBRO INMEDIATO (Ingreso PUE)
                pol.append([num, "Ingreso", c_banco, r["total"], 0, r["nombre_receptor"][:50], r["uuid"]])
                pol.append([num, "Ingreso", c_ingreso, 0, monto_principal_ajustado, concepto_recortado, r["uuid"]])
                if r["iva_16"] > 0:
                    pol.append([num, "Ingreso", c_iva_cobrado, 0, r["iva_16"], "IVA Cobrado", r["uuid"]])
        
        num += 1

    # --- 2. PROCESAR NÓMINAS (AGRUPADAS) ---
    nominas = df[df['tipo'] == 'N']
    if not nominas.empty:
        for depto, grupo in nominas.groupby('departamento'):
            total_sueldos = grupo['subtotal'].sum()
            total_neto = grupo['total'].sum()
            total_ret_isr = grupo['ret_isr'].sum()
            
            c_nomina = cuentas_def.get("gastos_generales", "60000000")
            c_impuestos_ret = cuentas_def.get("retenciones", "21601000")
            
            concepto_nomina = f"Provisión Nómina - {depto}"
            pol.append([num, "Diario", c_nomina, total_sueldos, 0, concepto_nomina[:50], ""])
            if total_ret_isr > 0:
                pol.append([num, "Diario", c_impuestos_ret, 0, total_ret_isr, f"Ret ISR Nomina {depto}", ""])
            pol.append([num, "Diario", c_banco, 0, total_neto, f"Neto a Pagar {depto}", ""])
            num += 1

    return pd.DataFrame(pol, columns=["Numero", "Tipo", "Cuenta", "Debe", "Haber", "Concepto", "UUID"])

def auto_ajustar_columnas_openpyxl(writer, sheet_name, df):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
        max_len = min(max_len, 50) 
        from openpyxl.utils import get_column_letter
        col_letter = get_column_letter(i + 1)
        worksheet.column_dimensions[col_letter].width = max_len

def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    
    resumen_df = pd.DataFrame([
        {"Métrica": "Total de XMLs Analizados", "Cantidad": log_data["total"]},
        {"Métrica": "Facturas Procesadas (PUE/PPD Evaluado)", "Cantidad": log_data["validas"]},
        {"Métrica": "Nóminas Agrupadas por Depto (Sin UUID)", "Cantidad": log_data["nominas"]},
        {"Métrica": "CFDI de Pagos Encontrados", "Cantidad": log_data["pagos"]},
        {"Métrica": "CFDI Cancelados (¡Revisar!)", "Cantidad": log_data["cancelados"]},
        {"Métrica": "⚠️ RECORDATORIO CRÍTICO", "Cantidad": "CARGA LOS XML AL ADD ANTES DE IMPORTAR ESTE EXCEL"}
    ])

    df["Sugerencia_SAT"] = df["cuenta"].apply(lambda x: "601-84-000 (Sugerido)" if str(x) == "60000000" else "Aprendido por IA")

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
            
    return filepath