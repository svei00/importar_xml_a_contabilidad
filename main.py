from db import init_db, upsert_factura, get_training_data
from xml_processor import load_folder, es_pago
from sat_validator import validar
from ml_model import train, predict
from export import exportar
from diot import generar_diot
from config import CUENTAS_DEFAULT, cargar_catalogo, validar_cuenta_vs_sat

from tkinter import Tk, filedialog
import pandas as pd

def main():
    init_db()
    
    print("📚 Cargando catálogo de cuentas...")
    df_catalogo = cargar_catalogo()

    root = Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Selecciona la carpeta con los XML del SAT")

    if not folder:
        print("Operación cancelada.")
        return

    print(f"📁 Cargando XMLs desde: {folder}")
    rows = load_folder(folder)

    enriched = []
    cancelados_count = 0

    print("🔍 Procesando facturas y validando en el SAT...")
    for r in rows:
        estado = validar(r["uuid"], r["rfc_emisor"], r["rfc_receptor"], r["total"])
        r["estado_sat"] = estado

        if estado == "CANCELADO":
            print(f"   ⚠️ ALERTA: CFDI CANCELADO -> {r['uuid']}")
            cancelados_count += 1

        # ML predice la cuenta (si no sabe, usa la default)
        cuenta = predict(r["concepto"], r["nombre_emisor"], r["cp"]) or CUENTAS_DEFAULT.get("gastos_generales", "60000000")
        r["cuenta"] = cuenta
        
        # Valida contra tu cuentas.txt
        r["nota"] = validar_cuenta_vs_sat(cuenta, df_catalogo)

        # Usando la función que pediste de vuelta
        if es_pago(r["tipo"]):
            r["cuenta"] = CUENTAS_DEFAULT.get("bancos", "10201000")
            r["nota"] = "CFDI Pago (Automático)"

        upsert_factura((
            r["uuid"], r["fecha"], r["tipo"],
            r["rfc_emisor"], r["rfc_receptor"],
            r["nombre_emisor"], r["nombre_receptor"],
            r["concepto"], r["subtotal"], r["iva_16"], r["total"],
            r["cp"], r["estado_sat"]
        ))
        enriched.append(r)

    df = pd.DataFrame(enriched)

    print("🧠 Entrenando modelo con histórico...")
    train_data = get_training_data()
    if train_data is not None and not train_data.empty:
        train(train_data)

    print("📊 Generando DIOT y exportando Excel...")
    diot_df = generar_diot(df)
    exportar(df, diot_df)

    print("✅ PROCESO COMPLETO. Revisa salida.xlsx")

if __name__ == "__main__":
    main()