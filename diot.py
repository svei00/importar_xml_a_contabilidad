import pandas as pd

def generar_diot(df):
    diot = pd.DataFrame()

    diot["RFC"] = df["rfc_emisor"]
    diot["Tipo"] = "04"
    diot["Operacion"] = "85"
    diot["IVA"] = df["iva"]
    diot["Region"] = "0"

    diot.to_excel("output/diot.xlsx", index=False)