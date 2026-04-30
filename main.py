import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, Frame, Button, Label, Text, Scrollbar
import pandas as pd

from db import init_db, upsert_factura, upsert_etiqueta, get_training_data, get_tipo_diot_automatico, limpiar_etiquetas
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
            cuenta = predict(r["concepto"], r["nombre_emisor"], r["cp"], empresa_rfc) or cuentas_def.get("gastos_generales", "60000000")
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
            train(train_data, empresa_rfc)
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

    # Aviso de fin + el usuario decide si abre la carpeta (antes se abría sola).
    abrir = messagebox.askyesno(
        "Proceso completo",
        f"Se generaron las pólizas y archivos en:\n{output_dir}\n\n"
        f"Revisa el Log para ver descuadres o cuentas pendientes.\n\n"
        f"¿Abrir la carpeta ahora?")
    if abrir:
        try:
            if os.name == "nt":
                os.startfile(output_dir)
            elif sys.platform == "darwin":
                __import__("subprocess").call(["open", output_dir])
            else:
                __import__("subprocess").call(["xdg-open", output_dir])
        except Exception:
            pass

def learn_from_excel_ui():
    from export import exportar_txt_contpaqi # Aseguramos importar el generador de TXT
    
    filepath = filedialog.askopenfilename(title="Selecciona el Excel Corregido", filetypes=[("Excel Files", "*.xlsx")])
    if not filepath: return

    try:
        filename = os.path.basename(filepath)
        output_dir = os.path.dirname(filepath) # Guardaremos el nuevo TXT en la misma carpeta
        
        partes = filename.split("_")
        if len(partes) < 3:
            print("❌ ERROR: El nombre del archivo no tiene el formato original.")
            return
            
        rfc = partes[2]
        print(f"\n🧠 Leyendo correcciones para la empresa: {rfc}...")

        xls = pd.ExcelFile(filepath)
        sheet_to_use = "POLIZAS_CONTPAQI" if "POLIZAS_CONTPAQI" in xls.sheet_names else xls.sheet_names[0]
        df_polizas = pd.read_excel(xls, sheet_name=sheet_to_use)

        # 1. ENTRENAR A LA IA — UNA cuenta principal por póliza (UUID).
        # Cada póliza tiene varios movimientos con el MISMO UUID (gasto, IVA, banco).
        # Hay que aprender SOLO la cuenta de gasto/activo, nunca el banco/IVA/proveedor,
        # o el modelo memoriza basura (era el bug de "no aprende nada").
        cuentas_def = load_settings().get("cuentas_default", {})
        prefijos_excluir = {"101", "102", "105", "118", "119", "201", "205", "208", "209"}
        for k in ("bancos", "iva_acreditable", "iva_pdte_pago", "proveedores",
                  "clientes", "iva_trasladado", "iva_pdte_cobro"):
            v = str(cuentas_def.get(k, "")).strip()
            if len(v) >= 3:
                prefijos_excluir.add(v[:3])

        def es_aprendible(cuenta):
            c = str(cuenta).strip()
            return c[:3] not in prefijos_excluir and c.replace("-", "").isdigit()

        df_polizas["Cuenta"] = df_polizas["Cuenta"].astype(str)
        df_polizas["Debe"] = pd.to_numeric(df_polizas.get("Debe"), errors="coerce").fillna(0)
        df_polizas["Haber"] = pd.to_numeric(df_polizas.get("Haber"), errors="coerce").fillna(0)

        count = 0
        for uuid, grupo in df_polizas.groupby("UUID"):
            uuid = str(uuid).strip()
            if not uuid or uuid.lower() == "nan":
                continue
            cand = grupo[grupo["Cuenta"].apply(es_aprendible)].copy()
            if cand.empty:           # p.ej. un REP (puro banco/IVA/proveedor): no se aprende
                continue
            cand["monto"] = cand["Debe"] + cand["Haber"]
            cuenta = str(cand.sort_values("monto", ascending=False).iloc[0]["Cuenta"]).strip()
            upsert_etiqueta(rfc, uuid, cuenta, "")
            count += 1

        # Sana etiquetas corruptas de corridas anteriores (banco/IVA/proveedor mal aprendidas)
        purgadas = limpiar_etiquetas(rfc, sorted(prefijos_excluir))

        train_data = get_training_data(rfc)
        if train_data is not None and len(train_data) > 1:
            train(train_data, rfc)
        print(f"✅ ¡IA actualizada! Aprendió {count} cuentas principales "
              f"(se descartaron {purgadas} etiquetas inválidas).")
        
        # 2. LA MAGIA: REGENERAR EL ARCHIVO TXT CON LAS CORRECCIONES
        print(f"🔄 Regenerando archivo TXT para CONTPAQi con los nuevos cambios...")
        
        # Pandas lee las fechas a veces con formato largo (YYYY-MM-DD HH:MM:SS), lo limpiamos:
        df_polizas["Fecha"] = df_polizas["Fecha"].astype(str).str[:10] 
        
        # Generamos el nuevo TXT que aplastará al viejo y erróneo
        txt_path = exportar_txt_contpaqi(df_polizas, output_dir, filename)
        
        print(f"✅ ¡NUEVO TXT LISTO! Archivo actualizado exitosamente.")
        
        # Mensaje de éxito en la interfaz
        messagebox.showinfo("Éxito", f"1. La IA memorizó {count} cuentas.\n2. El archivo TXT fue regenerado con tus correcciones.\n\n¡Ya puedes importarlo a CONTPAQi!")
        
    except Exception as e:
        print(f"❌ Error procesando el Excel: {e}")

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

def abrir_configuracion():
    """Ventana de Configuración: carpeta de salida, catálogo de cuentas (con la
    fecha de última actualización del archivo) y el toggle de IEPS con advertencia."""
    import datetime
    settings = load_settings()

    win = tk.Toplevel()
    win.title("Configuración")
    win.geometry("660x460")
    win.configure(bg="#1E1E2E")

    Label(win, text="⚙️ Configuración", bg="#1E1E2E", fg="#F9E2AF",
          font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=14, pady=(12, 4))

    def bloque(titulo):
        f = Frame(win, bg="#1E1E2E", padx=14, pady=6); f.pack(fill="x")
        Label(f, text=titulo, bg="#1E1E2E", fg="#CDD6F4",
              font=("Segoe UI", 10, "bold")).pack(anchor="w")
        val = Label(f, text="", bg="#1E1E2E", fg="#A6ADC8", font=("Consolas", 9),
                    wraplength=600, justify="left"); val.pack(anchor="w")
        return f, val

    def fecha_archivo(path):
        try:
            ts = os.path.getmtime(path)
            return datetime.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
        except Exception:
            return None

    # --- Carpeta de salida ---
    f_out, lbl_out = bloque("Carpeta de salida (pólizas, Excel y DIOT):")
    lbl_out.config(text=settings.get("output_path", "(no definida)"))
    def cambiar_out():
        d = filedialog.askdirectory(title="Carpeta de Salida",
                                    initialdir=load_settings().get("output_path", APP_DIR))
        if d:
            s = load_settings(); s["output_path"] = d; save_settings(s)
            lbl_out.config(text=d); print(f"⚙️ Carpeta de salida: {d}")
    crear_boton(f_out, "Cambiar carpeta", "#45475A", "#585B70", cambiar_out).pack(anchor="w", pady=4)

    # --- Catálogo de cuentas ---
    f_cat, lbl_cat = bloque("Catálogo de cuentas (COA):")
    def pintar_cat():
        cat = load_settings().get("catalogo_path", "(no definido)")
        fch = fecha_archivo(cat)
        lbl_cat.config(text=f"{cat}\nÚltima actualización: {fch}" if fch
                       else f"{cat}\n(no se encontró el archivo)")
    pintar_cat()
    def cambiar_cat():
        path = filedialog.askopenfilename(title="Catálogo de cuentas",
                                          filetypes=[("Texto/Excel/CSV", "*.txt *.xlsx *.csv"),
                                                     ("Todos", "*.*")])
        if path:
            s = load_settings(); s["catalogo_path"] = path; save_settings(s)
            pintar_cat(); print(f"⚙️ Catálogo actualizado: {path}")
    crear_boton(f_cat, "Cambiar catálogo", "#45475A", "#585B70", cambiar_cat).pack(anchor="w", pady=4)

    Frame(win, bg="#313244", height=1).pack(fill="x", padx=14, pady=10)

    # --- Toggle IEPS ---
    f_ieps = Frame(win, bg="#1E1E2E", padx=14, pady=4); f_ieps.pack(fill="x")
    var_ieps = tk.BooleanVar(value=bool(settings.get("acredita_ieps", False)))
    def toggle_ieps():
        s = load_settings(); s["acredita_ieps"] = bool(var_ieps.get()); save_settings(s)
        print(f"⚙️ Acreditamiento de IEPS {'ACTIVADO' if var_ieps.get() else 'desactivado'}.")
        cta = str(load_settings().get("cuentas_default", {}).get("ieps_acreditable", "")).strip()
        if var_ieps.get() and not cta:
            messagebox.showwarning("Falta la cuenta de IEPS",
                "Activaste el acreditamiento de IEPS pero no hay cuenta 'ieps_acreditable' "
                "en settings.json. El IEPS seguirá en el costo hasta que la definas.")
    tk.Checkbutton(f_ieps, text="Acreditar IEPS (separarlo a su propia cuenta)",
                   variable=var_ieps, command=toggle_ieps, bg="#1E1E2E", fg="#CDD6F4",
                   selectcolor="#313244", activebackground="#1E1E2E",
                   font=("Segoe UI", 10, "bold")).pack(anchor="w")
    Label(f_ieps, text="⚠️ Actívalo SOLO si la empresa es sujeta a IEPS (gasolineras, bebidas, "
                       "tabacos, etc.).\nSi no lo es, el IEPS debe quedarse como parte del costo "
                       "(déjalo apagado).",
          bg="#1E1E2E", fg="#F38BA8", font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(2, 0))

    Frame(win, bg="#313244", height=1).pack(fill="x", padx=14, pady=10)

    # --- Modo de nómina ---
    f_nom = Frame(win, bg="#1E1E2E", padx=14, pady=4); f_nom.pack(fill="x")
    var_nom = tk.BooleanVar(value=str(settings.get("nomina_modo", "contpaqi")).lower() == "xml")
    def toggle_nom():
        s = load_settings(); s["nomina_modo"] = "xml" if var_nom.get() else "contpaqi"; save_settings(s)
        print(f"⚙️ Modo de nómina: {s['nomina_modo']}.")
    tk.Checkbutton(f_nom, text="Generar póliza de nómina desde el XML",
                   variable=var_nom, command=toggle_nom, bg="#1E1E2E", fg="#CDD6F4",
                   selectcolor="#313244", activebackground="#1E1E2E",
                   font=("Segoe UI", 10, "bold")).pack(anchor="w")
    Label(f_nom, text="Déjalo APAGADO si usas CONTPAQi Nóminas (ese módulo ya genera la póliza; "
                      "así no se duplica).\nEnciéndelo solo si quieres que esta app arme la nómina "
                      "desde el CFDI.",
          bg="#1E1E2E", fg="#A6ADC8", font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(2, 0))


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

def administrar_alias_ui():
    """Ventana para que el usuario edite el alias (shortname) de cada tercero.
    La Referencia de las pólizas será  RFC-ALIAS  (consistente y filtrable)."""
    from tkinter import ttk
    from db import get_aliases_full, set_alias, list_empresas
    from terceros import limpiar_shortname, normalizar_shortname, construir_referencia

    empresas = list_empresas()
    if not empresas:
        messagebox.showinfo("Sin empresas",
                            "Aún no hay empresas procesadas.\nProcesa un lote de XML primero "
                            "para que se llenen los terceros.")
        return

    win = tk.Toplevel()
    win.title("Administrar Alias de Terceros")
    win.geometry("780x540")
    win.configure(bg="#1E1E2E")

    top = Frame(win, bg="#1E1E2E", padx=12, pady=10); top.pack(fill="x")
    Label(top, text="Empresa:", bg="#1E1E2E", fg="#CDD6F4",
          font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
    combo = ttk.Combobox(top, values=empresas, state="readonly", width=24)
    combo.pack(side=tk.LEFT, padx=8); combo.current(0)
    Label(win, text="La Referencia de cada póliza será  RFC-ALIAS  (sin espacios, máx 30 caracteres).",
          bg="#1E1E2E", fg="#A6ADC8", font=("Segoe UI", 9)).pack(anchor="w", padx=12)

    cols = ("rfc", "nombre", "apodo", "ref")
    tree = ttk.Treeview(win, columns=cols, show="headings", height=15)
    for c, txt, w in [("rfc", "RFC", 130), ("nombre", "Nombre oficial", 250),
                      ("apodo", "Alias", 120), ("ref", "Referencia resultante", 250)]:
        tree.heading(c, text=txt); tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True, padx=12, pady=8)

    edit = Frame(win, bg="#1E1E2E", padx=12, pady=8); edit.pack(fill="x")
    Label(edit, text="Alias:", bg="#1E1E2E", fg="#CDD6F4").pack(side=tk.LEFT)
    var = tk.StringVar()
    tk.Entry(edit, textvariable=var, width=20, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=6)
    prev = Label(edit, text="", bg="#1E1E2E", fg="#A6E3A1", font=("Consolas", 9))
    prev.pack(side=tk.LEFT, padx=10)

    def cargar():
        tree.delete(*tree.get_children())
        for rfc, short, nom in get_aliases_full(combo.get()):
            ref = construir_referencia(rfc, nom or "", {rfc: short} if short else {})
            tree.insert("", "end", iid=rfc, values=(rfc, (nom or "")[:40], short or "", ref))

    def actualizar_preview(*_):
        sel = tree.selection()
        prev.config(text=(f"->  {sel[0]}-{limpiar_shortname(var.get())}" if sel else ""))

    def on_select(_e=None):
        sel = tree.selection()
        if sel:
            var.set(tree.item(sel[0], "values")[2]); actualizar_preview()

    def guardar():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Selecciona", "Elige un tercero de la lista."); return
        rfc = sel[0]
        limpio = limpiar_shortname(var.get())
        if not limpio:
            messagebox.showwarning("Alias vacío",
                                   "El alias no puede quedar vacío. Escribe algo como LUZ, TELMEX, etc.")
            return
        set_alias(combo.get(), rfc, limpio)
        cargar(); tree.selection_set(rfc); tree.see(rfc)

    crear_boton(edit, "💾 Guardar Alias", "#38A169", "#2F855A", guardar).pack(side=tk.LEFT, padx=8)
    var.trace_add("write", actualizar_preview)
    tree.bind("<<TreeviewSelect>>", on_select)
    combo.bind("<<ComboboxSelected>>", lambda e: cargar())
    cargar()


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
    crear_boton(left_frame, "👥 Administrar Alias de Terceros", "#D69E2E", "#B7791F", administrar_alias_ui).pack(fill="x", pady=5)

    Frame(left_frame, bg="#313244", height=1).pack(fill="x", pady=15)
    crear_boton(left_frame, "⚙️ Configuración", "#45475A", "#585B70", abrir_configuracion).pack(fill="x", pady=5)

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