import pandas as pd

def exportar_polizas(df):
    polizas = []

    for i, row in df.iterrows():
        polizas.append([
            row["fecha"],
            "E",
            i,
            row["concepto"],
            row["cuenta"],
            row["total"],
            0,
            row["rfc_emisor"],
            row["uuid"]
        ])

    df_out = pd.DataFrame(polizas, columns=[
        "Fecha","Tipo","Numero","Concepto",
        "Cuenta","Debe","Haber","RFC","UUID"
    ])

    df_out.to_excel("output/polizas.xlsx", index=False)