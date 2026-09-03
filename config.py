import pandas as pd
import json
import os
from tkinter import filedialog, Tk
from catalogo_contpaqi import leer_catalogo, catalogo_a_tabla, normalizar_cuenta

SETTINGS_FILE = "settings.json"

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        default_settings = {
            "catalogo_path": "",
            "last_ingresos_path": "/",
            "last_egresos_path": "/",
            "output_path": "", 
            "cuentas_default": {
                "bancos": "10201000",       
                "iva_acreditable": "11801000", 
                "gastos_generales": "60000000"
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
    settings = load_settings()
    ruta = settings.get("catalogo_path", "")

    if not ruta or not os.path.exists(ruta):
        print("⚠️ Catálogo no encontrado. Selecciona tu archivo cuentas.txt...")
        root = Tk()
        root.withdraw()
        ruta = filedialog.askopenfilename(
            title="Selecciona tu catálogo exportado",
            filetypes=[("Text Files", "*.txt"), ("Excel Files", "*.xlsx"), ("All Files", "*.*")]
        )
        if ruta:
            settings["catalogo_path"] = ruta
            save_settings(settings)
        else:
            return pd.DataFrame()

    try:
        # El cuentas.txt de CONTPAQi es de ANCHO FIJO (no CSV); catalogo_contpaqi sabe leerlo.
        catalogo = leer_catalogo(ruta)
        df = pd.DataFrame(catalogo_a_tabla(catalogo),
                          columns=['cuenta', 'nombre', 'cuenta_mayor', 'tipo', 'nivel', 'agrupador'])
        print(f"✅ Catálogo cargado: {len(df)} cuentas listas.")
        return df
    except Exception as e:
        print(f"❌ Error al leer el catálogo: {e}")
        return pd.DataFrame()

def validar_cuenta_vs_sat(cuenta_predicha, df_catalogo):
    if df_catalogo is None or df_catalogo.empty:
        return "Sin validar"
        
    match = df_catalogo[df_catalogo.iloc[:, 0] == normalizar_cuenta(cuenta_predicha)]
    
    if not match.empty:
        return "OK (En catálogo)"
    else:
        return "⚠️ Revisar: Cuenta no en catálogo"