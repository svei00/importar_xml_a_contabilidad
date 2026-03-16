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

    # Ocultar la ventana principal de Tkinter
    root = Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Selecciona la carpeta con los XML del SAT")

    if not folder:
        print("Operación cancelada. No se seleccionó ninguna carpeta.")
        return

    print(f"📁 Cargando XMLs desde: {folder}")
    rows = load_folder(folder)

    if not rows:
        print("⚠️ No se encontraron archivos XML válidos en la carpeta.")
        return

    enriched = []
    cancelados_count = 0

    print("🔍 Procesando facturas y validando estatus en el SAT...")
    for r in rows:
        # 1. Validar en el SAT
        estado = validar(r["uuid"], r["rfc_emisor"], r["rfc_receptor"], r["total"])
        r["estado_sat"] = estado

        if estado == "CANCELADO":
            print(f"   ⚠️ ALERTA: CFDI CANCELADO detectado -> {r['uuid']}")
            cancelados_count += 1

        # 2. Machine Learning: Predicción de cuenta
        cuenta = predict(r["concepto"], r["nombre_emisor"], r["cp"]) or "60000000"
        r["cuenta"] = cuenta
        r["nota"] = "" # Campo extra para claridad en el Excel

        # 3. Regla estricta para CFDI de Pagos
        if r["tipo"] == "P":
            r["cuenta"] = "10201000"  # Cuenta de Bancos
            r["nota"] = "CFDI Pago"

        # 4. Guardar en SQLite
        upsert_factura((
            r["uuid"], r["fecha"], r["tipo"],
            r["rfc_emisor"], r["rfc_receptor"],
            r["nombre_emisor"], r["nombre_receptor"],
            r["concepto"], r["subtotal"], r["iva"], r["total"],
            r["cp"], r["estado_sat"]
        ))

        enriched.append(r)

    df = pd.DataFrame(enriched)

    print("🧠 Entrenando modelo de Machine Learning con el histórico...")
    # Entrena si ya hay etiquetas en la base de datos
    train_data = get_training_data()
    if train_data is not None and not train_data.empty:
        train(train_data)

    print("📊 Generando DIOT y exportando pólizas...")
    diot_df = generar_diot(df)
    exportar(df, diot_df)

    print("\n✅ PROCESO COMPLETO. Archivo generado: salida.xlsx")
    if cancelados_count > 0:
        print(f"🚨 IMPORTANTE: Se encontraron {cancelados_count} facturas CANCELADAS. Revísalas antes de provisionar.")

if __name__ == "__main__":
    main()