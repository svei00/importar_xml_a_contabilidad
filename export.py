import pandas as pd
import os
import re
from config import load_settings, cargar_catalogo
from terceros import construir_referencia, titulo

def generar_polizas(df, is_egresos, aliases=None, cuentas_clientes=None):
    """
    Toma los datos puros del SAT y genera el árbol de decisiones contables (Debe/Haber).
    Aplica las Normas de Información Financiera (NIF) para provisiones (PPD) y pagos (PUE/REP).
    """
    settings = load_settings()
    cuentas = settings.get("cuentas_default", {})
    
    c_banco = cuentas.get("bancos", "10201000")
    c_iva_pagado = cuentas.get("iva_acreditable", "11801000")
    c_iva_pdte_pago = cuentas.get("iva_pdte_pago", "11901000") 
    # FIX: Se cambia cuenta de mayor 20101000 por cuenta afectable 20101999 por defecto
    c_proveedores = cuentas.get("proveedores", "20101999") 
    # Clientes: cuenta POR cliente (mapa determinista RFC->cuenta del admin de alias).
    # Fallback: nacionales/público a la cuenta varios; extranjeros a la suya.
    cuentas_clientes = cuentas_clientes or {}
    c_clientes_default = cuentas.get("clientes", "10501999")
    c_clientes_ext = cuentas.get("clientes_extranjero", "10502000")
    c_ventas = cuentas.get("ventas", "40101000")
    c_iva_cobrado = cuentas.get("iva_trasladado", "20801000")
    c_iva_pdte_cobro = cuentas.get("iva_pdte_cobro", "20901000")

    # Retenciones por pagar (configurables: cada empresa tiene su propio COA).
    # En compras a proveedores que retienen: ISR servicios prof. + IVA retenido.
    c_ret_isr_hon = cuentas.get("ret_isr_honorarios", "21604000")
    c_ret_iva = cuentas.get("ret_iva", "21610000")

    # IEPS acreditable (toggle). Por defecto OFF: el IEPS se queda en el costo
    # (correcto para un contribuyente NO sujeto a IEPS). Si se activa y hay cuenta
    # configurada, el IEPS se separa del neto y se lleva a su propia cuenta
    # acreditable en compras PUE. Ver [[importar-xml-contpaqi]].
    c_ieps = str(cuentas.get("ieps_acreditable", "")).strip()
    ieps_activo = bool(settings.get("acredita_ieps", False)) and c_ieps not in ("", "0")

    # Modo de nómina: "contpaqi" (default) = NO generamos póliza de nómina porque
    # CONTPAQi Nóminas ya la produce; "xml" = la armamos desde el CFDI de nómina.
    nomina_modo = str(settings.get("nomina_modo", "contpaqi")).lower()

    aliases = aliases or {}
    pol = []
    num = 1
    df = df.fillna(0)

    for _, r in df.iterrows():
        tipo = r["tipo"]
        rol = "purchase" if is_egresos else "sale"
        metodo = r.get("metodo_pago", "PUE")
        uuid = str(r["uuid"]).strip()
        desc = str(r["concepto"]).strip()

        # Referencia = RFC-SHORTNAME (clave consistente y filtrable en Auxiliares).
        # El folio de la factura se conserva en el Concepto, no en la Referencia.
        ref_base = str(r.get("referencia", "")).strip()
        if not ref_base or ref_base.lower() == "nan": ref_base = "SR"

        rfc_tercero = str(r.get("rfc_emisor", "")) if is_egresos else str(r.get("rfc_receptor", ""))
        nombre_tercero = str(r.get("nombre_emisor", "")) if is_egresos else str(r.get("nombre_receptor", ""))
        if nombre_tercero.lower() == "nan": nombre_tercero = ""
        # El XML trae los nombres en MAYÚSCULAS; se muestran en Title Case (menos
        # ruido visual en el Listado de Pólizas). El RFC se queda en mayúsculas.
        nombre_tercero = titulo(nombre_tercero)

        ref = construir_referencia(rfc_tercero, nombre_tercero, aliases)
        if not ref:
            # Sin RFC válido (p.ej. nómina): se conserva el folio como referencia.
            ref = ref_base[:30]

        # Cuenta de cliente (solo emitidas): mapa RFC->cuenta, o varios/extranjero.
        rfc_up = str(rfc_tercero).strip().upper()
        c_cliente_row = (cuentas_clientes.get(rfc_up)
                         or (c_clientes_ext if rfc_up == "XEXX010101000" else c_clientes_default))

        # Concepto del cargo/abono principal: "NOMBRE - descripción" (legible en el
        # Listado de Pólizas, aunque la descripción del XML sea legalese).
        concepto = (f"{nombre_tercero} - {desc}".strip(" -") if nombre_tercero else desc)[:100]
        if not concepto:
            concepto = "Movimiento"
        concepto_pago = f"Pago a {nombre_tercero}".strip()[:100] if nombre_tercero else (desc[:100] or "Pago")
        concepto_cobro = f"Cobro de {nombre_tercero}".strip()[:100] if nombre_tercero else (desc[:100] or "Cobro")

        fecha_limpia = str(r.get("fecha", "2026-01-01")).split("T")[0]
        c_asignada = str(r.get("cuenta", "PENDIENTE")).strip()
        c_principal = c_asignada if c_asignada not in ["", "0", "PENDIENTE", "nan"] else "PENDIENTE"
        
        # Matemática de Impuestos NIF
        tot = float(r["total"])
        iva = float(r["iva_16"]) + float(r["iva_8"])
        ret_isr_v = float(r["ret_isr"])
        ret_iva_v = float(r["ret_iva"])
        ret = ret_iva_v + ret_isr_v
        ieps = float(r.get("ieps", 0) or 0)
        neto = round(tot - iva + ret, 2)   # = subtotal (la retención se acredita aparte)
        
        # Asientos Contables Automatizados
        if tipo == "I": 
            if rol == "purchase":
                prov = nombre_tercero[:50]
                if metodo == "PPD":
                    pol.append([num, "Diario", fecha_limpia, c_principal, ref, neto, 0, concepto, uuid])
                    if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_pago, ref, iva, 0, "IVA pendiente de pago", uuid])
                    if ret_isr_v > 0: pol.append([num, "Diario", fecha_limpia, c_ret_isr_hon, ref, 0, ret_isr_v, "Retención ISR por pagar", uuid])
                    if ret_iva_v > 0: pol.append([num, "Diario", fecha_limpia, c_ret_iva, ref, 0, ret_iva_v, "Retención IVA por pagar", uuid])
                    pol.append([num, "Diario", fecha_limpia, c_proveedores, ref, 0, tot, prov, uuid])
                else:
                    neto_pue = round(neto - ieps, 2) if ieps_activo else neto
                    pol.append([num, "Egreso", fecha_limpia, c_principal, ref, neto_pue, 0, concepto, uuid])
                    if ieps_activo and ieps > 0:
                        pol.append([num, "Egreso", fecha_limpia, c_ieps, ref, ieps, 0, "IEPS acreditable", uuid])
                    if iva > 0: pol.append([num, "Egreso", fecha_limpia, c_iva_pagado, ref, iva, 0, "IVA acreditable", uuid])
                    if ret_isr_v > 0: pol.append([num, "Egreso", fecha_limpia, c_ret_isr_hon, ref, 0, ret_isr_v, "Retención ISR por pagar", uuid])
                    if ret_iva_v > 0: pol.append([num, "Egreso", fecha_limpia, c_ret_iva, ref, 0, ret_iva_v, "Retención IVA por pagar", uuid])
                    pol.append([num, "Egreso", fecha_limpia, c_banco, ref, 0, tot, prov, uuid])
            else:
                cli = nombre_tercero[:50]
                c_principal = c_principal if c_principal != "PENDIENTE" else c_ventas
                if metodo == "PPD":
                    pol.append([num, "Diario", fecha_limpia, c_cliente_row, ref, tot, 0, cli, uuid])
                    pol.append([num, "Diario", fecha_limpia, c_principal, ref, 0, neto, concepto, uuid])
                    if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_cobro, ref, 0, iva, "IVA pendiente de cobro", uuid])
                else:
                    pol.append([num, "Ingreso", fecha_limpia, c_banco, ref, tot, 0, cli, uuid])
                    pol.append([num, "Ingreso", fecha_limpia, c_principal, ref, 0, neto, concepto, uuid])
                    if iva > 0: pol.append([num, "Ingreso", fecha_limpia, c_iva_cobrado, ref, 0, iva, "IVA Cobrado", uuid])

        elif tipo == "E": 
            if rol == "purchase":
                prov = nombre_tercero[:50]
                pol.append([num, "Diario", fecha_limpia, c_proveedores, ref, tot, 0, f"NC Prov - {prov}", uuid])
                pol.append([num, "Diario", fecha_limpia, c_principal, ref, 0, neto, concepto, uuid])
                if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_pago, ref, 0, iva, "Reversión IVA pendiente", uuid])
            else:
                cli = nombre_tercero[:50]
                pol.append([num, "Diario", fecha_limpia, c_principal, ref, neto, 0, concepto, uuid])
                if iva > 0: pol.append([num, "Diario", fecha_limpia, c_iva_pdte_cobro, ref, iva, 0, "Reversión IVA pendiente", uuid])
                pol.append([num, "Diario", fecha_limpia, c_cliente_row, ref, 0, tot, f"NC Cli - {cli}", uuid])

        elif tipo == "P":
            if rol == "purchase":
                pol.append([num, "Egreso", fecha_limpia, c_proveedores, ref, tot, 0, concepto_pago, uuid])
                pol.append([num, "Egreso", fecha_limpia, c_banco, ref, 0, tot, "Pago a proveedor", uuid])
                if iva > 0:
                    pol.append([num, "Egreso", fecha_limpia, c_iva_pagado, ref, iva, 0, "Reclasificación IVA acreditable", uuid])
                    pol.append([num, "Egreso", fecha_limpia, c_iva_pdte_pago, ref, 0, iva, "Cancelación IVA pendiente", uuid])
            else:
                pol.append([num, "Ingreso", fecha_limpia, c_banco, ref, tot, 0, "Cobro de cliente", uuid])
                pol.append([num, "Ingreso", fecha_limpia, c_cliente_row, ref, 0, tot, concepto_cobro, uuid])
                if iva > 0:
                    pol.append([num, "Ingreso", fecha_limpia, c_iva_pdte_cobro, ref, iva, 0, "Cancelación IVA pendiente de cobro", uuid])
                    pol.append([num, "Ingreso", fecha_limpia, c_iva_cobrado, ref, 0, iva, "Reclasificación IVA trasladado", uuid])

        elif tipo == "N":
            # Si usas CONTPAQi Nóminas (modo por defecto) NO duplicamos la póliza:
            # esa la genera el módulo de Nóminas. Solo se arma desde XML si modo="xml".
            if nomina_modo != "xml":
                num += 1
                continue
            c_nom = cuentas.get("nomina", "60010000")
            c_ret_isr = cuentas.get("ret_isr_nomina", "21601000")
            pol.append([num, "Diario", fecha_limpia, c_nom, ref, float(r["subtotal"]), 0, f"Provisión Nómina {r['departamento']}"[:50], ""])
            if float(r["ret_isr"]) > 0:
                pol.append([num, "Diario", fecha_limpia, c_ret_isr, ref, 0, float(r["ret_isr"]), "Retención ISR nómina", ""])
            pol.append([num, "Diario", fecha_limpia, c_banco, ref, 0, tot, "Neto a Pagar", ""])

        num += 1

    polizas_df = pd.DataFrame(pol, columns=["Numero", "Tipo", "Fecha", "Cuenta", "Referencia", "Debe", "Haber", "Concepto", "UUID"])
    polizas_df["Fecha"] = polizas_df["Fecha"].astype(str)
    return polizas_df

def generar_sugerencia(row, df_cat):
    c_act = str(row.get("cuenta", "")).strip()
    if c_act and c_act not in ["0", "PENDIENTE", "nan"]: return "🧠 IA"
    if df_cat is None or df_cat.empty: return "⚠️ Faltan Cuentas"
    emisor = str(row.get("nombre_emisor", "")).upper()
    basura = ['S.A.', 'DE', 'C.V.', 'SAB', 'RL', 'SA', 'CV', 'S', 'A', 'C', 'V']
    pals = [p for p in emisor.split() if p not in basura and len(p) > 2]
    if not pals: return "Manual"
    try:
        match = df_cat[df_cat.iloc[:, 1].str.upper().str.contains(pals[0], na=False)]
        if not match.empty: return f"💡 {match.iloc[0, 0]} ({match.iloc[0, 1]})"
    except Exception: pass
    return "Manual"

def auto_ajustar_columnas(writer, sheet_name, df):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
        col_letter = __import__('openpyxl').utils.get_column_letter(i + 1)
        worksheet.column_dimensions[col_letter].width = min(max_len, 50)
        
        for cell in worksheet[col_letter]:
            if col in ["Cuenta", "Referencia", "Fecha"]:
                cell.number_format = '@'

def exportar_txt_contpaqi(polizas_df, output_dir, excel_filename):
    """Generador TXT Estricto para CONTPAQi (Formato Tabular de Ancho Fijo)"""
    txt_filename = "Polizas_CONTPAQi_" + excel_filename.replace(".xlsx", ".txt")
    filepath = os.path.join(output_dir, txt_filename)
    
    with open(filepath, "w", encoding="windows-1252", errors="replace") as f:
        for num, group in polizas_df.groupby("Numero"):
            primera_fila = group.iloc[0]
            
            fecha_cruda = str(primera_fila["Fecha"]).split()[0].replace("-", "").replace("/", "").strip()
            fecha_str = fecha_cruda[:8] if len(fecha_cruda) >= 8 else "20260101"
            
            tipo_str = str(primera_fila["Tipo"]).upper()
            tipo_int = "3" 
            if "INGRESO" in tipo_str: tipo_int = "1"
            elif "EGRESO" in tipo_str: tipo_int = "2"
            
            concepto_poliza = str(primera_fila["Concepto"])[:100].strip()
            if not concepto_poliza: concepto_poliza = "Sin Concepto"
            
            # FIX: Cabecera P sin GUID interno falso. Termina exactamente en 11 0 0
            f.write(f"P  {fecha_str}    {tipo_int}         {num:<2}1 0          {concepto_poliza:<100} 11 0 0 \n")
            
            for _, r in group.iterrows():
                cuenta_val = str(r["Cuenta"]).strip()
                if cuenta_val.upper() in ["PENDIENTE", "NAN", "0"] or "FALTA" in cuenta_val.upper():
                    continue 
                if not cuenta_val.replace("-", "").isdigit():
                    continue
                
                referencia = str(r.get("Referencia", "")).strip()[:30]
                if referencia.lower() == "nan": referencia = ""
                
                debe = float(r["Debe"])
                haber = float(r["Haber"])
                if debe == 0 and haber == 0: continue 
                
                concepto_mov = str(r["Concepto"])[:100].strip()
                uuid_mov = str(r["UUID"]).strip().upper()
                
                tipo_mov = "0" if debe > 0 else "1"
                importe = debe if debe > 0 else haber
                
                # CONTPAQi lee los importes en columnas FIJAS. La cuenta debe ocupar
                # 31 caracteres (no 30): con 30 todo se recorre 1 a la izquierda y
                # CONTPAQi se "come" el primer dígito del importe (3915.00 -> 915.00),
                # dejando la póliza descuadrada -> cuenta de cuadre / pólizas rechazadas.
                cuenta_str = f"{cuenta_val:<31}"
                ref_str = f"{referencia:<31}"
                importe_str = f"{importe:.2f}"
                importe_pad = f"{importe_str:<21}"
                
                # FIX: M1 termina en el concepto, sin inyectar GUID falso
                f.write(f"M1 {cuenta_str}{ref_str}{tipo_mov} {importe_pad}0          0.0                  {concepto_mov:<106}\n")
                
                # FIX: El UUID va exclusivamente en la asociación digital (AD)
                if len(uuid_mov) == 36:
                    f.write(f"AD {uuid_mov}\n")
                        
    return filepath

def generar_archivo_diot_sat(df, output_dir, excel_filename):
    """
    [OBSOLETA — YA NO SE LLAMA] Segundo generador de DIOT que duplicaba el archivo.
    La DIOT oficial se genera ahora SOLO desde diot.py::exportar_txt_sat.
    Se conserva temporalmente como referencia para la unificación; se eliminará.
    """
    import re
    import os
    
    meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    match = re.search(r'_(\d{4})_(\d{2})', excel_filename)
    if match:
        year = match.group(1)
        month_num = int(match.group(2))
        month_str = meses[month_num - 1]
        base_name = f"{month_num:02d}. {month_str} {year}"
        
        # Archivo Normal con DOS ESPACIOS estrictos
        n_filename = f"{base_name}  N DIOT.txt"
        diot_filepath = os.path.join(output_dir, n_filename)
        
        # Contador Automático de Complementarias
        if os.path.exists(diot_filepath):
            counter = 1
            while True:
                c_filename = f"{base_name} C{counter} DIOT.txt"
                diot_filepath = os.path.join(output_dir, c_filename)
                if not os.path.exists(diot_filepath):
                    break
                counter += 1
    else:
        diot_filepath = os.path.join(output_dir, "DIOT_SAT_Fallback.txt")
        
    # Filtro estricto: PUE (Ingresos directos), P (Pagos/REPs) y E (Notas de Crédito)
    df_flujo = df[
        (df["metodo_pago"].astype(str).str.strip().str.upper() == "PUE") | 
        (df["tipo"].astype(str).str.strip().str.upper() == "P") | 
        (df["tipo"].astype(str).str.strip().str.upper() == "E")
    ].copy()
    
    if df_flujo.empty:
        return None

    acumulado_base = {}
    acumulado_descuentos = {}
    
    for _, r in df_flujo.iterrows():
        rfc = str(r.get("rfc_emisor", "")).strip().upper()
        if not rfc or rfc == "NAN" or len(rfc) < 12: 
            continue
            
        tipo_cfdi = str(r.get("tipo", "")).strip().upper()
        base_16 = float(r.get("subtotal", 0)) 
        
        # Cálculo matemático para la Base de los REPs (Subtotal en 0)
        if tipo_cfdi == "P" and base_16 == 0:
            tot_p = float(r.get("total", 0))
            iva_p = float(r.get("iva_16", 0))
            ret_p = float(r.get("ret_isr", 0)) + float(r.get("ret_iva", 0))
            
            if iva_p > 0:
                base_16 = tot_p - iva_p + ret_p
            elif tot_p > 0:
                base_16 = tot_p / 1.16
        
        descuento_cfdi = float(r.get("descuento", 0)) if "descuento" in r else 0.0
        
        if rfc not in acumulado_base:
            acumulado_base[rfc] = 0.0
            acumulado_descuentos[rfc] = 0.0
            
        if tipo_cfdi == "E":
            acumulado_descuentos[rfc] += base_16
        else:
            acumulado_base[rfc] += base_16
            acumulado_descuentos[rfc] += descuento_cfdi

    with open(diot_filepath, "w", encoding="windows-1252") as f:
        for rfc in acumulado_base.keys():
            base = round(acumulado_base[rfc])
            desc = round(acumulado_descuentos[rfc])
            
            if base < 0: base = 0
            if desc < 0: desc = 0
            
            if base == 0 and desc == 0:
                continue
                
            base_neta = base - desc
            if base_neta < 0: base_neta = 0
            iva_acreditable = round(base_neta * 0.16)
            
            # EL FIX ESTÁ AQUÍ: 54 elementos = 53 tuberías = 54 campos exactos.
            row = [""] * 54 
            row[0] = "04"  
            row[1] = "85"  
            row[2] = rfc   
            
            if base > 0:
                row[11] = str(base)              
            if desc > 0:
                row[12] = str(desc)              
            if iva_acreditable > 0:
                row[21] = str(iva_acreditable)   
            
            # Ya NO imprimimos el "01" al final
            f.write("|".join(row) + "\n")
            
    return diot_filepath

def sincronizar_aliases(empresa_rfc, df, is_egresos):
    """
    Da de alta (con apodo por defecto) cada tercero nuevo visto en este lote,
    para que aparezca en el administrador de alias listo para renombrar.
    Devuelve el diccionario {rfc: shortname} ya vigente.
    """
    if not empresa_rfc:
        return {}
    from db import ensure_alias, get_aliases
    from terceros import normalizar_shortname
    col_rfc = "rfc_emisor" if is_egresos else "rfc_receptor"
    col_nom = "nombre_emisor" if is_egresos else "nombre_receptor"
    tipo = "P" if is_egresos else "C"   # P=Proveedor (recibidas), C=Cliente (emitidas)
    for _, r in df.iterrows():
        if str(r.get("tipo", "")) == "N":   # nómina no tiene tercero proveedor
            continue
        rfc = str(r.get(col_rfc, "")).strip().upper()
        nombre = str(r.get(col_nom, ""))
        ensure_alias(empresa_rfc, rfc, nombre, normalizar_shortname(nombre), tipo=tipo)
    return get_aliases(empresa_rfc)

def validar_balance_polizas(polizas_df, tol=0.01):
    """Revisa el cuadre Debe=Haber por póliza y detecta cuentas sin asignar ANTES
    de escribir el TXT (CONTPAQi rechaza pólizas descuadradas y crea cuenta de cuadre).
    Devuelve (descuadres, pendientes) para avisar al usuario."""
    descuadres = []
    for num, g in polizas_df.groupby("Numero"):
        debe = float(pd.to_numeric(g["Debe"], errors="coerce").fillna(0).sum())
        haber = float(pd.to_numeric(g["Haber"], errors="coerce").fillna(0).sum())
        if abs(debe - haber) > tol:
            con = str(g.iloc[0]["Concepto"])[:40]
            descuadres.append((num, round(debe, 2), round(haber, 2), round(debe - haber, 2), con))
    ctas = polizas_df["Cuenta"].astype(str).str.strip().str.upper()
    mask = ctas.isin(["PENDIENTE", "NAN", "0", ""]) | ctas.str.contains("FALTA", na=False)
    pendientes = sorted(set(polizas_df.loc[mask, "Cuenta"].astype(str)))
    return descuadres, pendientes


def exportar(df, diot_df, output_dir, filename, log_data):
    filepath = os.path.join(output_dir, filename)
    is_egresos = "EGRESOS" in filename.upper()
    try: df_catalogo = cargar_catalogo()
    except: df_catalogo = None

    # Empresa = 3er segmento del nombre de archivo (Polizas_<TIPO>_<RFC>_<AAAA>_<MM>.xlsx)
    partes = os.path.basename(filename).split("_")
    empresa_rfc = partes[2] if len(partes) >= 3 else ""
    try: aliases = sincronizar_aliases(empresa_rfc, df, is_egresos)
    except Exception: aliases = {}
    try:
        from db import get_cuentas_clientes
        cuentas_clientes = get_cuentas_clientes(empresa_rfc)
    except Exception:
        cuentas_clientes = {}

    res_df = pd.DataFrame([{"Métrica": k, "Cantidad": v} for k, v in log_data.items()])
    df["Sugerencia"] = df.apply(lambda r: generar_sugerencia(r, df_catalogo), axis=1)

    polizas_df = generar_polizas(df, is_egresos, aliases, cuentas_clientes)

    # Cuadre Debe=Haber + cuentas sin asignar ANTES de escribir el TXT.
    descuadres, pendientes = validar_balance_polizas(polizas_df)
    if descuadres:
        print(f"[AVISO] {len(descuadres)} póliza(s) DESCUADRADA(S) (Debe != Haber):")
        for num, d, h, dif, con in descuadres:
            print(f"   Póliza {num}: Debe={d} Haber={h} dif={dif}  [{con}]")
    if pendientes:
        print(f"[AVISO] Cuentas sin asignar (corrige antes de importar): {', '.join(pendientes)}")
    if not descuadres and not pendientes:
        print("[OK] Todas las pólizas cuadran (Debe = Haber); sin cuentas pendientes.")

    with pd.ExcelWriter(filepath, engine='openpyxl') as w:
        res_df.to_excel(w, sheet_name="RESUMEN", index=False)
        auto_ajustar_columnas(w, "RESUMEN", res_df)

        df.to_excel(w, sheet_name="BASE", index=False)
        auto_ajustar_columnas(w, "BASE", df)

        polizas_df.to_excel(w, sheet_name="POLIZAS_CONTPAQI", index=False)
        auto_ajustar_columnas(w, "POLIZAS_CONTPAQI", polizas_df)

        # DIOT agregada (una fila por RFC) para revisión humana — solo egresos.
        if diot_df is not None and not diot_df.empty:
            diot_df.to_excel(w, sheet_name="DIOT_LISTA", index=False)
            auto_ajustar_columnas(w, "DIOT_LISTA", diot_df)
            
    # Solo se genera el TXT de pólizas aquí. La DIOT se produce UNA sola vez
    # desde diot.py (main.py -> exportar_txt_sat) para no duplicar archivos
    # con lógicas distintas. (generar_archivo_diot_sat quedó obsoleta.)
    exportar_txt_contpaqi(polizas_df, output_dir, filename)

    # NO se abre la carpeta aquí: la capa de UI (main.py) decide si avisar y abrir,
    # para que el usuario reciba el mensaje de "proceso terminado" y elija abrir o no.
    return filepath