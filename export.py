# export.py
import pandas as pd

def generar_polizas(df):
    # Layout importable simple CONTPAQi
    pol = []
    num = 1

    for _, r in df.iterrows():
        if r["tipo"] != "E":
            continue

        subtotal = r["subtotal"]
        iva = r["iva"]
        total = r["total"]

        # Cuentas (ajusta a tu catálogo real)
        c_gasto = r["cuenta"]
        c_iva = "11801000"
        c_banco = "10201000"

        pol += [
            [num,"E",c_gasto,subtotal,0,r["concepto"],r["uuid"]],
            [num,"E",c_iva,iva,0,"IVA",r["uuid"]],
            [num,"E",c_banco,0,total,"Pago",r["uuid"]],
        ]
        num += 1

    return pd.DataFrame(pol, columns=[
        "Numero","Tipo","Cuenta","Debe","Haber","Concepto","UUID"
    ])

def exportar(df, diot_df):
    with pd.ExcelWriter("salida.xlsx") as w:
        df.to_excel(w, sheet_name="FACTURAS", index=False)
        generar_polizas(df).to_excel(w, sheet_name="POLIZAS", index=False)
        diot_df.to_excel(w, sheet_name="DIOT", index=False)