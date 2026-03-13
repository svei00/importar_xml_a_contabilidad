from db import init_db
from sat_utils import validar_uuid
from ml_model import predecir
import pandas as pd

def main():
    init_db()

    # TODO: Leer XML reales
    df = pd.read_csv("input.csv")

    resultados = []

    for _, row in df.iterrows():

        estatus = validar_uuid(
            row["uuid"],
            row["rfc_emisor"],
            row["rfc_receptor"],
            row["total"]
        )

        cuenta = predecir(
            row["concepto"],
            row["rfc_emisor"],
            row["rfc_receptor"]
        )

        resultados.append({
            **row,
            "cuenta": cuenta,
            "estatus_sat": estatus
        })

    df_out = pd.DataFrame(resultados)

    df_out.to_excel("output/resultados.xlsx", index=False)

if __name__ == "__main__":
    main()