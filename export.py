import pandas as pd
import os
from config import load_settings

def generar_polizas(df):
    settings = load_settings()
    cuentas_def = settings.get("cuentas_default", {})
    
    pol = []
    num = 1

    for _, r in df.iterrows():
        # Ignoramos pagos para la provisión base, pero SÍ incluimos Nóminas (N) y Egresos (E)
        if r["tipo"] not in ["I", "E", "N"]: 
            continue

        c_gasto = r["cuenta"]
        c_iva = cuentas_def.get("iva_acreditable", "11801000")
        c_banco = cuentas_def.get("bancos", "10201000")

        # Póliza básica de provisión
        pol += [
            [num, "Diario/Egreso", c_gasto, r["subtotal"], 0, r["concepto"][:50], r["uuid"]],
        ]
        
        # Si tiene IVA, lo agregamos (Las nóminas no tienen IVA, así que esto se ignora para ellas)
        if r["iva_16"] > 0:
            pol += [[num, "Diario/Egreso", c_iva, r["iva_16"], 0, "IVA 16%", r["uuid"]]]
            
        pol += [
            [num, "Diario/Egreso", c_banco, 0, r["total"], "Acreedor/Banco", r["uuid"]]
        ]
        num += 1

    return pd.DataFrame(pol, columns=["Numero", "Tipo", "Cuenta", "Debe", "Haber", "Concepto", "UUID"])

def auto_ajustar_columnas_openpyxl(writer, sheet_name, df):
    """Ajusta las columnas automáticamente usando openpyxl para evitar crashes."""
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        # Encuentra el valor más largo en la columna o el título
        max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
        max_len = min(max_len, 50) # Límite de 50 para que no sea infinita
        
        # openpyxl usa letras para las columnas (A, B, C...)
        from openpyxl.utils import get_column_letter
        col_letter = get_column_letter(i + 1)
        worksheet.column_dimensions[col_letter].width = max_len

def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    
    resumen_df = pd.DataFrame([
        {"Métrica": "Total de XMLs Analizados", "Cantidad": log_data["total"]},
        {"Métrica": "Facturas/Nóminas Procesadas en Pólizas", "Cantidad": log_data["validas"]},
        {"Métrica": "Nóminas (Omitidas de DIOT)", "Cantidad": log_data["nominas"]},
        {"Métrica": "CFDI de Pagos", "Cantidad": log_data["pagos"]},
        {"Métrica": "CFDI Cancelados (¡Revisar!)", "Cantidad": log_data["cancelados"]}
    ])

    df["Sugerencia_SAT"] = df["cuenta"].apply(lambda x: "601-84-000 (Sugerido)" if x == "60000000" else "Aprendido por IA")

    # Usamos openpyxl en lugar de xlsxwriter para evitar el error
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