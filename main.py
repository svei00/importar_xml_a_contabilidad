import os
from tkinter import Tk, filedialog, simpledialog, Button, Label, Frame
import pandas as pd

from db import init_db, upsert_factura, get_training_data
from xml_processor import load_folder, es_pago
from sat_validator import validar
from ml_model import train, predict
from export import exportar
from diot import generar_diot, exportar_txt_sat
from config import load_settings, save_settings, cargar_catalogo, validar_cuenta_vs_sat

def process_folder(folder_path, tipo_operacion):
    print(f"\n📁 Cargando XMLs ({tipo_operacion}) desde: {folder_path}")
    rows = load_folder(folder_path)
    
    if not rows:
        print("⚠️ No se encontraron archivos XML válidos.")
        return

    df_catalogo = cargar_catalogo()
    settings = load_settings()
    cuentas_def = settings.get("cuentas_default", {})

    enriched = []
    cancelados_count = 0

    print("🔍 Procesando facturas y validando en el SAT...")
    for r in rows:
        estado = validar(r["uuid"], r["rfc_emisor"], r["rfc_receptor"], r["total"])
        r["estado_sat"] = estado

        if estado == "CANCELADO":
            print(f"   ⚠️ ALERTA: CFDI CANCELADO -> {r['uuid']}")
            cancelados_count += 1

        cuenta = predict(r["concepto"], r["nombre_emisor"], r["cp"]) or cuentas_def.get("gastos_generales", "60000000")
        r["cuenta"] = cuenta
        r["nota"] = validar_cuenta_vs_sat(cuenta, df_catalogo)

        if es_pago(r["tipo"]):
            r["cuenta"] = cuentas_def.get("bancos", "10201000")
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

    print("📊 Exportando Excel...")
    diot_df = generar_diot(df)
    exportar(df, diot_df)

    # Si son Egresos, preguntamos los datos para generar el TXT del SAT
    if tipo_operacion == "egresos":
        root = Tk()
        root.withdraw() # Oculta la ventana principal
        mes = simpledialog.askstring("Generar DIOT", "Ingresa el MES a declarar (ej. 01 para Enero):")
        anio = simpledialog.askstring("Generar DIOT", "Ingresa el AÑO (ej. 2026):")
        tipo_decl = simpledialog.askstring("Generar DIOT", "Tipo de declaración (N = Normal, C = Complementaria):", initialvalue="N")
        
        if mes and anio and tipo_decl:
            exportar_txt_sat(diot_df, mes, anio, tipo_decl.upper())

    print("\n✅ PROCESO COMPLETO. Revisa salida.xlsx")
    if cancelados_count > 0:
        print(f"🚨 Se encontraron {cancelados_count} facturas CANCELADAS.")

def select_folder_and_run(tipo):
    settings = load_settings()
    key = f"last_{tipo}_path"
    initial_dir = settings.get(key, "/")

    folder = filedialog.askdirectory(title=f"Selecciona carpeta de {tipo.upper()}", initialdir=initial_dir)
    if folder:
        settings[key] = folder
        save_settings(settings)
        process_folder(folder, tipo)

def main():
    init_db()

    # Interfaz Gráfica Principal
    root = Tk()
    root.title("SAT Automator")
    root.geometry("380x200")
    root.eval('tk::PlaceWindow . center')

    Label(root, text="Selecciona el tipo de XML a procesar:", pady=20, font=("Arial", 12)).pack()

    Button(root, text="Cargar EMITIDAS (Ingresos / Ventas)", 
           command=lambda: select_folder_and_run("ingresos"), 
           width=40, bg="#3182DF", fg="white", font=("Arial", 10, "bold")).pack(pady=5)
           
    Button(root, text="Cargar RECIBIDAS (Egresos / Gastos)", 
           command=lambda: select_folder_and_run("egresos"), 
           width=40, bg="#21B868", fg="white", font=("Arial", 10, "bold")).pack(pady=5)

    root.mainloop()

if __name__ == "__main__":
    main()