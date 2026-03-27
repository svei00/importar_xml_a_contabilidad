import pandas as pd
from config import CUENTAS_DEFAULT

def generar_polizas(df):
    pol = []
    num = 1

    for _, r in df.iterrows():
        # Ignorar pagos aquí para no duplicar pólizas, o procesarlos diferente
        if r["tipo"] not in ["I", "E"]: 
            continue

        c_gasto = r["cuenta"]
        c_iva = CUENTAS_DEFAULT.get("iva_acreditable", "11801000")
        c_banco = CUENTAS_DEFAULT.get("bancos", "10201000")

        # Póliza de Egreso/Diario básica
        pol += [
            [num, "Diario/Egreso", c_gasto, r["subtotal"], 0, r["concepto"][:50], r["uuid"]],
            [num, "Diario/Egreso", c_iva, r["iva_16"], 0, "IVA 16%", r["uuid"]],
            [num, "Diario/Egreso", c_banco, 0, r["total"], "Acreedor/Banco", r["uuid"]],
        ]
        num += 1

    return pd.DataFrame(pol, columns=["Numero", "Tipo", "Cuenta", "Debe", "Haber", "Concepto", "UUID"])

def exportar(df, diot_df):
    with pd.ExcelWriter("salida.xlsx") as w:
        df.to_excel(w, sheet_name="FACTURAS_BASE", index=False)
        generar_polizas(df).to_excel(w, sheet_name="POLIZAS_CONTPAQI", index=False)
        diot_df.to_excel(w, sheet_name="DIOT_LISTA", index=False)