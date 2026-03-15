# main.py
from db import init_db, upsert_factura, get_training_data
from xml_processor import load_folder
from sat_validator import validar
from ml_model import train, predict
from export import exportar
from diot import generar_diot

from tkinter import Tk, filedialog
import pandas as pd

def main():
    init_db()

    Tk().withdraw()
    folder = filedialog.askdirectory(title="Selecciona carpeta XML")

    rows = load_folder(folder)

    enriched = []

    for r in rows:
        estado = validar(r["uuid"], r["rfc_emisor"], r["rfc_receptor"], r["total"])
        r["estado_sat"] = estado

        # ML (fallback a regla simple si no hay modelo)
        cuenta = predict(r["concepto"], r["nombre_emisor"], r["cp"]) or "60000000"
        r["cuenta"] = cuenta

        upsert_factura((
            r["uuid"], r["fecha"], r["tipo"],
            r["rfc_emisor"], r["rfc_receptor"],
            r["nombre_emisor"], r["nombre_receptor"],
            r["concepto"], r["subtotal"], r["iva"], r["total"],
            r["cp"], r["estado_sat"]
        ))

        enriched.append(r)

    df = pd.DataFrame(enriched)

    # TODO CFDI pagos
    if r["tipo"] == "P":
        r["cuenta"] = "10201000"  # Bancos
        r["nota"] = "CFDI Pago"

    # Entrena si ya hay etiquetas (cuando tú confirmes/ajustes)
    train(get_training_data())

    diot_df = generar_diot(df)

    exportar(df, diot_df)

    if estado == "CANCELADO":
        print(f"⚠️ CFDI CANCELADO: {r['uuid']}")

    print("✅ Proceso completo. Archivo: salida.xlsx")

if __name__ == "__main__":
    main()