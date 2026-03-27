import pandas as pd
import json
import os
from tkinter import filedialog, Tk

SETTINGS_FILE = "settings.json"

def load_settings():
    """Carga configuraciones dinámicas. Si no existen, crea un template."""
    if not os.path.exists(SETTINGS_FILE):
        default_settings = {
            "catalogo_path": "",
            "cuentas_default": {
                "bancos": "",       # Déjalo en blanco, el ML aprenderá tus cuentas reales
                "iva_acreditable": "", 
                "gastos_generales": ""
            }
        }
        with open(SETTINGS_FILE, "w") as f:
            json.dump(default_settings, f, indent=4)
        return default_settings
    
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)

def cargar_catalogo():
    """Abre una ventana si no sabe dónde está el TXT, y luego lo lee."""
    settings = load_settings()
    ruta = settings.get("catalogo_path", "")

    if not ruta or not os.path.exists(ruta):
        print("⚠️ Catálogo no encontrado. Selecciona tu archivo cuentas.txt...")
        root = Tk()
        root.withdraw()
        ruta = filedialog.askopenfilename(
            title="Selecciona tu catálogo exportado de ContpaqI",
            filetypes=[("Text Files", "*.txt"), ("Excel Files", "*.xlsx"), ("All Files", "*.*")]
        )
        if ruta:
            settings["catalogo_path"] = ruta
            save_settings(settings)
        else:
            print("❌ No se seleccionó catálogo. El sistema correrá a ciegas.")
            return pd.DataFrame()

    try:
        df = pd.read_csv(ruta, sep='\t', dtype=str) # Asume tabulaciones
        print(f"✅ Catálogo cargado desde: {ruta} ({len(df)} cuentas).")
        return df
    except Exception as e:
        print(f"❌ Error al leer el catálogo: {e}")
        return pd.DataFrame()