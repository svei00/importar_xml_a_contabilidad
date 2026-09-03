import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, Frame, Button, Label, Text, Scrollbar
import pandas as pd

from db import (init_db, upsert_factura, upsert_etiqueta, get_training_data, get_tipo_diot_automatico,
                limpiar_etiquetas, get_cuentas_gasto, borrar_etiquetas_de_cuentas)
from xml_processor import load_folder, es_pago
from sat_validator import validar
from ml_model import train, predict
from export import exportar
from diot import generar_diot, exportar_txt_sat
from config import load_settings, save_settings, cargar_catalogo, validar_cuenta_vs_sat
from config_empresa import obtener_config_empresa
from excepciones import ColectorDeExcepciones
from reglas_contables import aplicar_reglas
from balanza_contpaqi import leer_balanza, es_cierre_del_mes_anterior, fecha_de_cierre_del_mes_anterior
from cuotas_patronales import cuentas_por_rfc, es_pago_de_cuota
from periodo_lote import determinar_periodo
from catalogo_contpaqi import leer_catalogo_si_es_valido, validar_cuenta, cuentas_acumulativas
from registrar_corrida import registrar_lote
from sembrar_historial import sembrar_desde_carpeta
import registro_contable
from periodo_lote import separar_anio_mes
from resumen_corrida import (desglose_corrida, hay_algo_que_contabilizar,
                             redactar_aviso_mes_vacio, redactar_aviso_sin_xml)

APP_DIR = os.path.dirname(os.path.abspath(__file__))

class PrintLogger:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, message):
        self.text_widget.insert(tk.END, message)
        self.text_widget.see(tk.END)

    def flush(self):
        pass

def avisar_corrida_sin_polizas(empresa_rfc, periodo, tipo_operacion, desglose, colector):
    """Regla I: no hay nada que contabilizar -> se AVISA y NO se genera ningun archivo."""
    titulo, mensaje = redactar_aviso_mes_vacio(empresa_rfc, periodo, tipo_operacion, desglose)
    print(f"ℹ️ {titulo}")
    print(f"   {mensaje}")
    colector.imprimir_en_log()
    messagebox.showinfo(titulo, mensaje)


def clasificar_y_validar_filas(rows, tipo_operacion, empresa_rfc, df_catalogo, cuentas_def, log_data,
                               cuentas_gasto_fijas=None):
    """
    Por cada CFDI: valida su estatus en el SAT, le asigna la cuenta principal
    (ML o cuenta fija) y lo guarda en la tabla facturas. Devuelve la lista enriquecida.
    """
    cuentas_gasto_fijas = cuentas_gasto_fijas or {}
    enriched = []
    for r in rows:
        if r["tipo"] == "N":
            log_data["nominas"] += 1
            r["cuenta"] = "60010000"   # cuenta de nomina por defecto
        elif r["tipo"] == "P":
            log_data["pagos"] += 1

        estado = validar(r["uuid"], r["rfc_emisor"], r["rfc_receptor"], r["total"])
        r["estado_sat"] = estado

        if estado == "CANCELADO":
            log_data["cancelados"] += 1
            print(f"   🚨 ALERTA: CFDI Cancelado -> {r['uuid']} (se excluye de pólizas y DIOT)")

        if r["tipo"] == "N":
            pass  # la nómina ya tiene su cuenta (60010000) asignada arriba
        elif tipo_operacion == "ingresos":
            # En EMITIDAS la cuenta principal es de INGRESO (Ventas). El clasificador
            # ML solo conoce cuentas de GASTO (se entrena con recibidas), así que NO
            # se usa aquí: codificaría una venta a una cuenta 60xx. El detalle por
            # cliente sale de la Referencia (RFC-ALIAS), no de una subcuenta.
            r["cuenta"] = cuentas_def.get("ventas", "40101000")
        else:
            # Orden: 1) cuenta de gasto FIJA del proveedor (alias)  2) la IA  3) la cuenta general.
            cuenta_fija = cuentas_gasto_fijas.get(str(r["rfc_emisor"]).strip().upper())
            cuenta = (cuenta_fija
                      or predict(r["concepto"], r["nombre_emisor"], r["cp"], empresa_rfc)
                      or cuentas_def.get("gastos_generales", "60000000"))
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
    return enriched


def _leer_balanza_del_periodo(ruta, periodo):
    """Lee la balanza y confirma que sea la del cierre del mes anterior. Devuelve (balanza o None, aviso)."""
    if not ruta or not os.path.exists(ruta):
        return None, "No hay balanza seleccionada."
    try:
        balanza = leer_balanza(ruta)
    except (ValueError, OSError) as error:
        return None, f"No se pudo leer la balanza: {error}"
    if not es_cierre_del_mes_anterior(balanza, periodo):
        esperada = fecha_de_cierre_del_mes_anterior(periodo).strftime("%d/%m/%Y")
        corte = balanza["fecha_corte"].strftime("%d/%m/%Y") if balanza["fecha_corte"] else "fecha desconocida"
        return None, f"La balanza esta cortada al {corte} y se necesita la del {esperada}."
    return balanza, ""


def obtener_balanza_para_cuotas(config_empresa, periodo, filas):
    """
    Solo si el lote trae pagos de cuotas patronales: usa la balanza guardada si es la del
    cierre del mes anterior; si no, PIDE a Svei que seleccione la correcta. Devuelve la
    balanza o None (la regla de cuotas sabe que hacer sin ella).
    """
    rfcs = cuentas_por_rfc(config_empresa)
    if not any(es_pago_de_cuota(f, rfcs) for f in filas):
        return None
    balanza, aviso = _leer_balanza_del_periodo(config_empresa.get("balanza_path", ""), periodo)
    if balanza is not None:
        return balanza

    cierre = fecha_de_cierre_del_mes_anterior(periodo).strftime("%d/%m/%Y")
    print(f"ℹ️ Cuotas patronales en el lote. {aviso}")
    if not messagebox.askyesno(
            "Balanza de comprobación",
            f"Este lote trae pagos de IMSS/INFONAVIT.\n{aviso}\n\n"
            f"Para saber si hay provisión por pagar necesito la balanza de comprobación "
            f"al {cierre} (exportada de CONTPAQi).\n\n¿Seleccionarla ahora?"):
        return None
    ruta = filedialog.askopenfilename(title=f"Balanza de comprobación al {cierre}",
                                      filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")])
    balanza, aviso = _leer_balanza_del_periodo(ruta, periodo)
    if balanza is None:
        print(f"⚠️ {aviso}")
        messagebox.showwarning("Balanza no válida", aviso)
        return None
    settings = load_settings()
    settings["balanza_path"] = ruta
    save_settings(settings)
    print(f"✅ Balanza al {cierre} cargada.")
    return balanza


def anotar_en_el_registro(empresa_rfc, tipo_operacion, periodo, carpeta, filas, estado, archivo_txt=""):
    """Guarda en la memoria de la app lo que esta corrida decidio. Si falla, AVISA (no es silencioso)."""
    try:
        registrar_lote(empresa_rfc, tipo_operacion, periodo, carpeta, filas, estado, archivo_txt)
        print(f"🗂️ Registro actualizado: lote {periodo} ({estado}).")
    except Exception as error:
        print(f"⚠️ No se pudo actualizar el registro de lo contabilizado: {error}")


def process_folder(folder_path, tipo_operacion):
    print(f"\n📁 Cargando XMLs ({tipo_operacion}) desde: {folder_path}")
    rows = load_folder(folder_path)

    if not rows:
        titulo, mensaje = redactar_aviso_sin_xml(folder_path)
        print(f"⚠️ {titulo}: no se encontraron archivos XML válidos o ZIPs.")
        messagebox.showwarning(titulo, mensaje)
        return

    if tipo_operacion == "ingresos":
        empresa_rfc = rows[0]["rfc_emisor"]
    else:
        empresa_rfc = rows[0]["rfc_receptor"]

    init_db(empresa_rfc)

    df_catalogo = cargar_catalogo()
    settings = load_settings()
    cuentas_def = settings.get("cuentas_default", {})
    config_empresa = obtener_config_empresa(empresa_rfc)

    output_dir = settings.get("output_path", "")
    if not output_dir or not os.path.exists(output_dir):
        output_dir = APP_DIR

    log_data = {"total": len(rows), "validas": 0, "nominas": 0, "pagos": 0, "cancelados": 0}
    colector = ColectorDeExcepciones()

    print("🔍 Validando en el SAT y clasificando conceptos...")
    enriched = clasificar_y_validar_filas(rows, tipo_operacion, empresa_rfc,
                                          df_catalogo, cuentas_def, log_data,
                                          get_cuentas_gasto(empresa_rfc))

    catalogo, aviso_catalogo = leer_catalogo_si_es_valido(config_empresa.get("catalogo_path", ""))
    if catalogo is None:
        print(f"⚠️ {aviso_catalogo}")

    # Reglas de decisión (Fase 1): cancelados, nómina en modo CONTPAQi, periodo del lote.
    balanza = None
    if tipo_operacion == "egresos":
        balanza = obtener_balanza_para_cuotas(config_empresa, determinar_periodo(enriched), enriched)
    periodo = aplicar_reglas(enriched, config_empresa, colector,
                             empresa_rfc=empresa_rfc, tipo_operacion=tipo_operacion,
                             catalogo=catalogo, balanza=balanza)

    # Caso E: lo que la IA aprendio hacia una cuenta rechazada se borra para que no la vuelva a proponer.
    cuentas_rechazadas = {f["cuenta_rechazada"] for f in enriched if f.get("cuenta_rechazada")}
    borradas = borrar_etiquetas_de_cuentas(empresa_rfc, cuentas_rechazadas)
    if borradas:
        print(f"🧹 La IA olvidó {borradas} etiqueta(s) hacia cuentas inválidas: {', '.join(sorted(cuentas_rechazadas))}")
    desglose = desglose_corrida(enriched)
    log_data["validas"] = desglose["contabilizables"]
    log_data["omitidos"] = desglose["total_xml"] - desglose["contabilizables"]

    if not periodo:
        print("❌ Ningún XML trae una fecha válida; no se puede determinar el periodo.")
        return
    anio, mes = separar_anio_mes(periodo)
    print(f"🏢 Empresa: {empresa_rfc} | Periodo: {mes}/{anio}")

    # Regla I: nada que contabilizar -> aviso y NINGÚN archivo (ni TXT, ni Excel, ni DIOT).
    if not hay_algo_que_contabilizar(desglose):
        anotar_en_el_registro(empresa_rfc, tipo_operacion, periodo, folder_path, enriched,
                              registro_contable.ESTADO_SIN_MOVIMIENTOS)
        avisar_corrida_sin_polizas(empresa_rfc, periodo, tipo_operacion, desglose, colector)
        return

    # A partir de aquí solo viajan los CFDI que SÍ generan póliza (sin cancelados ni nómina omitida).
    activos = [r for r in enriched if not r["omitir"]]
    df = pd.DataFrame(activos)

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

    exportar(df, diot_df, output_dir, excel_filename, log_data, colector)
    archivo_txt = "Polizas_CONTPAQi_" + excel_filename.replace(".xlsx", ".txt")
    anotar_en_el_registro(empresa_rfc, tipo_operacion, periodo, folder_path, enriched,
                          registro_contable.ESTADO_VIGENTE, archivo_txt)

    if colector.cuantas() > 0:
        print(f"📋 {colector.cuantas()} excepción(es) registradas (hoja EXCEPCIONES del Excel):")
        colector.imprimir_en_log()
    print(f"✅ ¡PROCESO COMPLETO! Excel guardado en: {output_dir}")

    # Aviso de fin + el usuario decide si abre la carpeta (antes se abría sola).
    abrir = messagebox.askyesno(
        "Proceso completo",
        f"Se generaron las pólizas y archivos en:\n{output_dir}\n\n"
        f"Excepciones registradas: {colector.cuantas()}\n"
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

        config_aprendizaje = obtener_config_empresa(rfc)
        catalogo_aprendizaje, _ = leer_catalogo_si_es_valido(config_aprendizaje.get("catalogo_path", ""))
        acumulativas_aprendizaje = cuentas_acumulativas(catalogo_aprendizaje) if catalogo_aprendizaje else set()
        cuentas_no_aprendidas = set()

        def es_aprendible(cuenta):
            c = str(cuenta).strip()
            if c[:3] in prefijos_excluir or not c.replace("-", "").isdigit():
                return False
            if catalogo_aprendizaje and validar_cuenta(
                    c, catalogo_aprendizaje, acumulativas_aprendizaje,
                    config_aprendizaje.get("cuentas_retiradas", [])) is not None:
                cuentas_no_aprendidas.add(c)   # cuenta inexistente/acumulativa/retirada: NO se aprende
                return False
            return True

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
        if cuentas_no_aprendidas:
            print(f"⚠️ No se aprendieron cuentas inválidas del catálogo: {', '.join(sorted(cuentas_no_aprendidas))}")
        
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

def sembrar_historial_ui():
    """Carga un mes YA contabilizado a la memoria de la app (para reexpediciones y pagos)."""
    folder = filedialog.askdirectory(title="Carpeta de XML de un mes ya contabilizado")
    if not folder:
        return
    son_recibidas = messagebox.askyesno(
        "Tipo de comprobantes",
        "¿Son comprobantes RECIBIDOS (compras)?\n\nSí = Recibidas   |   No = Emitidas (ventas)")
    tipo = "egresos" if son_recibidas else "ingresos"
    resumen = sembrar_desde_carpeta(folder, tipo)
    if resumen is None:
        messagebox.showwarning("Carpeta sin CFDI", f"No se encontraron XML válidos en:\n{folder}")
        return
    mensaje = (f"Empresa {resumen['empresa']} | periodo {resumen['periodo']}\n"
               f"{resumen['sembrados']} comprobantes registrados como ya contabilizados "
               f"(de {resumen['total_xml']} XML; la nómina no cuenta).")
    print(f"📚 Historial sembrado: {mensaje}")
    messagebox.showinfo("Historial sembrado", mensaje)


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
    """Administra Clientes (emitidas) y Proveedores (recibidas): alias para la
    Referencia (RFC-ALIAS) y, SOLO para clientes, la cuenta contable (10501001…).
    La cuenta de cliente es un mapa determinista RFC->cuenta (no usa ML)."""
    from tkinter import ttk
    from db import (get_aliases_full, set_alias, set_alias_cuenta, set_alias_cuenta_gasto,
                    backfill_tipo_aliases, list_empresas)
    from terceros import limpiar_shortname, construir_referencia

    empresas = list_empresas()
    if not empresas:
        messagebox.showinfo("Sin empresas",
                            "Aún no hay empresas procesadas.\nProcesa un lote de XML primero "
                            "para que se llenen los terceros.")
        return

    TIPO_LABEL = {"C": "Cliente", "P": "Proveedor", None: "", "": ""}

    win = tk.Toplevel()
    win.title("Administrar Clientes y Proveedores")
    win.geometry("960x560")
    win.configure(bg="#1E1E2E")

    top = Frame(win, bg="#1E1E2E", padx=12, pady=10); top.pack(fill="x")
    Label(top, text="Empresa:", bg="#1E1E2E", fg="#CDD6F4",
          font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
    combo = ttk.Combobox(top, values=empresas, state="readonly", width=22)
    combo.pack(side=tk.LEFT, padx=8); combo.current(0)
    Label(top, text="   Mostrar:", bg="#1E1E2E", fg="#CDD6F4",
          font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
    filtro = ttk.Combobox(top, values=["Todos", "Clientes", "Proveedores"],
                          state="readonly", width=14)
    filtro.pack(side=tk.LEFT, padx=8); filtro.current(0)

    Label(win, text="Referencia = RFC-ALIAS (sin espacios, máx 30). Cuenta tercero: dónde vive el saldo "
                    "del cliente (10501001…) o proveedor (20101002…); vacía = cuenta 'varios'. "
                    "Cuenta gasto: solo proveedores (60350000…).",
          wraplength=900, justify="left",
          bg="#1E1E2E", fg="#A6ADC8", font=("Segoe UI", 9)).pack(anchor="w", padx=12)

    cols = ("rfc", "nombre", "tipo", "alias", "cuenta", "gasto", "ref")
    tree = ttk.Treeview(win, columns=cols, show="headings", height=15)
    for c, txt, w in [("rfc", "RFC", 130), ("nombre", "Nombre oficial", 240),
                      ("tipo", "Tipo", 80), ("alias", "Alias", 110),
                      ("cuenta", "Cuenta tercero", 100), ("gasto", "Cuenta gasto", 90),
                      ("ref", "Referencia", 200)]:
        tree.heading(c, text=txt); tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True, padx=12, pady=8)

    edit = Frame(win, bg="#1E1E2E", padx=12, pady=8); edit.pack(fill="x")
    Label(edit, text="Alias:", bg="#1E1E2E", fg="#CDD6F4").pack(side=tk.LEFT)
    var = tk.StringVar()
    tk.Entry(edit, textvariable=var, width=18, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=6)
    Label(edit, text="Cuenta tercero:", bg="#1E1E2E", fg="#CDD6F4").pack(side=tk.LEFT, padx=(12, 0))
    var_cta = tk.StringVar()
    tk.Entry(edit, textvariable=var_cta, width=12, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=6)
    Label(edit, text="Cuenta gasto:", bg="#1E1E2E", fg="#CDD6F4").pack(side=tk.LEFT, padx=(6, 0))
    var_gasto = tk.StringVar()
    tk.Entry(edit, textvariable=var_gasto, width=12, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=6)
    prev = Label(edit, text="", bg="#1E1E2E", fg="#A6E3A1", font=("Consolas", 9))
    prev.pack(side=tk.LEFT, padx=10)

    def cargar():
        backfill_tipo_aliases(combo.get())
        tree.delete(*tree.get_children())
        f = filtro.get()
        for rfc, short, nom, tipo, cuenta, cuenta_gasto in get_aliases_full(combo.get()):
            if f == "Clientes" and tipo != "C": continue
            if f == "Proveedores" and tipo != "P": continue
            ref = construir_referencia(rfc, nom or "", {rfc: short} if short else {})
            tree.insert("", "end", iid=rfc,
                        values=(rfc, (nom or "")[:38], TIPO_LABEL.get(tipo, ""),
                                short or "", cuenta or "", cuenta_gasto or "", ref))

    def actualizar_preview(*_):
        sel = tree.selection()
        prev.config(text=(f"->  {sel[0]}-{limpiar_shortname(var.get())}" if sel else ""))

    def on_select(_e=None):
        sel = tree.selection()
        if sel:
            vals = tree.item(sel[0], "values")
            var.set(vals[3]); var_cta.set(vals[4]); var_gasto.set(vals[5]); actualizar_preview()

    def guardar():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Selecciona", "Elige un cliente o proveedor de la lista."); return
        rfc = sel[0]
        limpio = limpiar_shortname(var.get())
        if not limpio:
            messagebox.showwarning("Alias vacío",
                                   "El alias no puede quedar vacío. Escribe algo como LUZ, TELMEX, etc.")
            return
        cta = var_cta.get().strip()
        gasto = var_gasto.get().strip()
        for cuenta_escrita in (cta, gasto):
            if cuenta_escrita and not cuenta_escrita.replace("-", "").isdigit():
                messagebox.showwarning("Cuenta inválida",
                                       "Las cuentas deben ser numéricas (ej. 20101002 o 60350000)."); return
        set_alias(combo.get(), rfc, limpio)
        set_alias_cuenta(combo.get(), rfc, cta.replace("-", ""))
        set_alias_cuenta_gasto(combo.get(), rfc, gasto.replace("-", ""))
        cargar();
        if tree.exists(rfc): tree.selection_set(rfc); tree.see(rfc)

    crear_boton(edit, "💾 Guardar", "#38A169", "#2F855A", guardar).pack(side=tk.LEFT, padx=8)
    var.trace_add("write", actualizar_preview)
    tree.bind("<<TreeviewSelect>>", on_select)
    combo.bind("<<ComboboxSelected>>", lambda e: cargar())
    filtro.bind("<<ComboboxSelected>>", lambda e: cargar())
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
    crear_boton(left_frame, "👥 Administrar Clientes y Proveedores", "#D69E2E", "#B7791F", administrar_alias_ui).pack(fill="x", pady=5)

    Frame(left_frame, bg="#313244", height=1).pack(fill="x", pady=15)
    crear_boton(left_frame, "📚 Sembrar historial…", "#2C7A7B", "#285E61", sembrar_historial_ui).pack(fill="x", pady=5)
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