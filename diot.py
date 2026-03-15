import pandas as pd

def generar_diot(df):
    filas = []

    for _, r in df.iterrows():
        if r["tipo"] != "E":
            continue

        filas.append({
            "RFC": r["rfc_emisor"],
            "Nombre": r["nombre_emisor"],
            "TipoTercero": "04",   # Nacional
            "TipoOperacion": "03", # Servicios
            "IVA_16": r["iva"],
            "IVA_8": 0,
            "IVA_Exento": 0,
            "RetencionIVA": 0,
            "RetencionISR": 0,
            "ImporteTotal": r["total"]
        })

    return pd.DataFrame(filas)