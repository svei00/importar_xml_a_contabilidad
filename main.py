import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, Frame, Button, Label, Text, Scrollbar
import pandas as pd

from db import init_db, upsert_factura, upsert_etiqueta, get_training_data, get_tipo_diot_automatico
from xml_processor import load_folder, es_pago
from sat_validator import validar
from ml_model import train, predict
from export import exportar
from diot import generar_diot, exportar_txt_sat
from config import load_settings, save_settings, cargar_catalogo, validar_cuenta_vs_sat

APP_DIR = os.path.dirname(os.path.abspath(__file__))

class PrintLogger:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, message):
        self.text_widget.insert(tk.END, message)
        self.text_widget.see(tk.END)

    def flush(self):
        pass

def process_folder(folder_path, tipo_operacion):
    print(f"\n📁 Cargando XMLs ({tipo_operacion}) desde: {folder_path}")
    rows = load_folder(folder_path)
    
    if not rows:
        print("⚠️ ERROR: No se encontraron archivos XML válidos o ZIPs.")
        return

    if tipo_operacion == "ingresos":
        empresa_rfc = rows[0]["rfc_emisor"] 
    else:
        empresa_rfc = rows[0]["rfc_receptor"] 
        
    fecha_primer_xml = rows[0]["fecha"] 
    anio = fecha_primer_xml.split("-")[0]
    mes = fecha_primer_xml.split("-")[1]

    print(f"🏢 Empresa: {empresa_rfc} | Periodo: {mes}/{anio}")
    init_db(empresa_rfc)

    df_catalogo = cargar_catalogo()
    settings = load_settings()
    cuentas_def = settings.get("cuentas_default", {})

    output_dir = settings.get("output_path", "")
    if not output_dir or not os.path.exists(output_dir):
        output_dir = APP_DIR

    enriched = []
    log_data = {"total": len(rows), "validas": 0, "nominas": 0, "pagos": 0, "cancelados": 0}

    print("🔍 Validando en el SAT y clasificando conceptos...")
    for r in rows:
        # Lógica correcta para Nóminas
        if r["tipo"] == "N":
            log_data["nominas"] += 1
            print(f"   ℹ️ Nómina detectada ({r['uuid'][:8]}): Se incluye en Pólizas, omitida en DIOT.")
            # Default account for payroll
            r["cuenta"] = "60010000" 
        elif r["tipo"] == "P":
            log_data["pagos"] += 1

        estado = validar(r["uuid"], r["rfc_emisor"], r["rfc_receptor"], r["total"])
        r["estado_sat"] = estado

        if estado == "CANCELADO":
            log_data["cancelados"] += 1
            print(f"   🚨 ALERTA: CFDI Cancelado -> {r['uuid']}")

        if r["tipo"] != "N":
            cuenta = predict(r["concepto"], r["nombre_emisor"], r["cp"]) or cuentas_def.get("gastos_generales", "60000000")
            r["cuenta"] = cuenta

        r["nota"] = validar_cuenta_vs_sat(r["cuenta"], df_catalogo)

        if es_pago(r["tipo"]):
            r["cuenta"] = cuentas_def.get("bancos", "10201000")
            r["nota"] = "CFDI Pago"

        upsert_factura(empresa_rfc, (
            r["uuid"], r["fecha"], r["tipo"],
            r["rfc_emisor"], r["rfc_receptor"],
            r["nombre_emisor"], r["nombre_receptor"],
            r["concepto"], r["subtotal"], r["iva_16"], r["total"],
            r["cp"], r["estado_sat"]
        ))
        enriched.append(r)
        log_data["validas"] += 1

    df = pd.DataFrame(enriched)

    try:
        train_data = get_training_data(empresa_rfc)
        if train_data is not None and len(train_data) > 1:
            train(train_data)
    except Exception:
        pass

    excel_filename = f"Polizas_{tipo_operacion.upper()}_{empresa_rfc}_{anio}_{mes}.xlsx"
    diot_df = None

    if tipo_operacion == "egresos":
        print("📊 Generando base DIOT...")
        diot_df = generar_diot(df)
        tipo_decl = get_tipo_diot_automatico(empresa_rfc, mes, anio)
        print(f"📝 Generando TXT del SAT automáticamente (Tipo: {tipo_decl})...")
        exportar_txt_sat(diot_df, mes, anio, tipo_decl, output_dir)
    else:
        print("📊 Exportando Excel de Ingresos (Sin DIOT)...")
    
    exportar(df, diot_df, output_dir, excel_filename, log_data)
    print(f"✅ ¡PROCESO COMPLETO! Excel guardado en: {output_dir}")

def learn_from_excel_ui():
    filepath = filedialog.askopenfilename(title="Selecciona el Excel Corregido", filetypes=[("Excel Files", "*.xlsx")])
    if not filepath: return

    try:
        filename = os.path.basename(filepath)
        partes = filename.split("_")
        if len(partes) < 3:
            print("❌ ERROR: El nombre del archivo no tiene el formato original.")
            return
        rfc = partes[2]
        print(f"\n🧠 Leyendo correcciones para la empresa: {rfc}...")

        df_polizas = pd.read_excel(filepath, sheet_name="POLIZAS_CONTPAQI")
        df_gastos = df_polizas[~df_polizas["Concepto"].isin(["IVA 16%", "Acreedor/Banco"])]

        count = 0
        for _, r in df_gastos.iterrows():
            uuid = str(r["UUID"]).strip()
            cuenta = str(r["Cuenta"]).strip()
            upsert_etiqueta(rfc, uuid, cuenta, "") 
            count += 1

        print("⚙️ Re-entrenando la Inteligencia artificial...")
        train_data = get_training_data(rfc)
        if train_data is not None and len(train_data) > 1:
            train(train_data)
            
        print(f"✅ ¡Aprendizaje Completado! La IA memorizó {count} cuentas para el RFC {rfc}.")
    except Exception as e:
        print(f"❌ Error leyendo el Excel: {e}")

def select_folder_and_run(tipo):
    settings = load_settings()
    key = f"last_{tipo}_path"
    initial_dir = settings.get(key, "/")
    folder = filedialog.askdirectory(title=f"Selecciona carpeta de {tipo.upper()}", initialdir=initial_dir)
    if folder:
        settings[key] = folder
        save_settings(settings)
        process_folder(folder, tipo)

def set_output_folder():
    settings = load_settings()
    initial_dir = settings.get("output_path", APP_DIR)
    folder = filedialog.askdirectory(title="Selecciona Carpeta de Salida", initialdir=initial_dir)
    if folder:
        settings["output_path"] = folder
        save_settings(settings)
        print(f"\n⚙️ Configuración Guardada: Los archivos irán a {folder}")

def clear_log(text_widget):
    text_widget.delete('1.0', tk.END)

def copy_log(text_widget, root):
    root.clipboard_clear()
    root.clipboard_append(text_widget.get("1.0", tk.END))
    messagebox.showinfo("Copiado", "Log copiado al portapapeles.")

def crear_boton(parent, text, bg, hover, command):
    btn = Button(parent, text=text, bg=bg, fg="white", font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2", command=command, pady=6)
    btn.bind("<Enter>", lambda e: e.widget.config(bg=hover))
    btn.bind("<Leave>", lambda e: e.widget.config(bg=bg))
    return btn

def main():
    root = tk.Tk()
    root.title("SAT & ContpaqI Automator AI Pro")
    root.geometry("800x550") 
    root.eval('tk::PlaceWindow . center') 
    
    bg_dark = "#1E1E2E"       
    text_color = "#CDD6F4"    

    root.configure(bg=bg_dark)

    # 📌 NOTA: Para cambiar el ícono de la app, descomenta la siguiente línea 
    # y asegúrate de tener tu archivo 'icono.ico' en esta misma carpeta:
    # root.iconbitmap('icono.ico')

    left_frame = Frame(root, bg=bg_dark, padx=20, pady=20, width=300)
    left_frame.pack(side=tk.LEFT, fill=tk.Y)

    Label(left_frame, text="Procesamiento:", bg=bg_dark, fg=text_color, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
    crear_boton(left_frame, "📤 EMITIDAS (Ventas)", "#3182CE", "#2B6CB0", lambda: select_folder_and_run("ingresos")).pack(fill="x", pady=5)
    crear_boton(left_frame, "📥 RECIBIDAS (Compras + DIOT)", "#38A169", "#2F855A", lambda: select_folder_and_run("egresos")).pack(fill="x", pady=5)
    
    Frame(left_frame, bg="#313244", height=1).pack(fill="x", pady=15)
    
    Label(left_frame, text="Inteligencia Artificial:", bg=bg_dark, fg=text_color, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
    crear_boton(left_frame, "🧠 Aprender de Excel Corregido", "#805AD5", "#6B46C1", learn_from_excel_ui).pack(fill="x", pady=5)
    
    Frame(left_frame, bg="#313244", height=1).pack(fill="x", pady=15)
    crear_boton(left_frame, "⚙️ Configurar Carpeta de Salida", "#45475A", "#585B70", set_output_folder).pack(fill="x", pady=5)

    right_frame = Frame(root, bg="#11111B", padx=10, pady=10)
    right_frame.pack(side=tk.RIGHT, expand=True, fill="both")

    log_label_frame = Frame(right_frame, bg="#11111B")
    log_label_frame.pack(fill="x")
    Label(log_label_frame, text="Terminal de Registro (Log):", bg="#11111B", fg=text_color, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
    
    Button(log_label_frame, text="Limpiar", bg="#45475A", fg="white", relief="flat", command=lambda: clear_log(text_area)).pack(side=tk.RIGHT, padx=5)
    Button(log_label_frame, text="Copiar", bg="#3182CE", fg="white", relief="flat", command=lambda: copy_log(text_area, root)).pack(side=tk.RIGHT)

    text_area = Text(right_frame, bg="#181825", fg="#A6E3A1", font=("Consolas", 9), wrap="word", relief="flat")
    scrollbar = Scrollbar(right_frame, command=text_area.yview)
    text_area.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    text_area.pack(expand=True, fill="both", pady=5)

    sys.stdout = PrintLogger(text_area)
    print("🤖 Sistema Contable ML Inicializado.")
    print("Esperando instrucciones...")

    root.mainloop()

if __name__ == "__main__":
    main()