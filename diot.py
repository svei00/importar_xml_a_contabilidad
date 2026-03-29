import pandas as pd
import os

def determinar_tipo_tercero(rfc):
    rfc = str(rfc).strip().upper()
    if rfc == "XEXX010101000": 
        return "05" # Proveedor Extranjero
    elif rfc == "XAXX010101000": 
        return "15" # Proveedor Global
    return "04" # Proveedor Nacional

def determinar_tipo_operacion(concepto, tipo_tercero):
    """
    Cruza el concepto con el tipo de tercero según las reglas ESTRICTAS del SAT (Páginas 4 y 5).
    """
    concepto_lower = str(concepto).lower()
    
    # 1. Regla Proveedor Global (15) -> SOLO acepta 87
    if tipo_tercero == "15":
        return "87" 
        
    # 2. Regla Proveedor Extranjero (05) -> SOLO acepta 02, 03, 07
    if tipo_tercero == "05":
        if "servicio" in concepto_lower or "honorario" in concepto_lower: 
            return "03" # Prestación de Servicios Profesionales
        elif "importación" in concepto_lower or "aduana" in concepto_lower: 
            return "07" # Importación de bienes o servicios
        else: 
            return "02" # Enajenación de bienes (Por defecto)
            
    # 3. Regla Proveedor Nacional (04) -> Acepta 02, 03, 06, 08, 85
    if "arrendamiento" in concepto_lower or "renta" in concepto_lower: 
        return "06" # Uso o goce temporal
    elif "honorarios" in concepto_lower or "servicios profesionales" in concepto_lower: 
        return "03" # Prestación de Servicios Profesionales
    return "85" # Otros (El más común)

def generar_diot(df):
    """
    Genera el DataFrame que el usuario verá en el Excel (Pestaña DIOT_LISTA).
    """
    filas = []
    for _, r in df.iterrows():
        # Excluir Nóminas, Pagos y Traslados
        if r["tipo"] in ["N", "P", "T"]: 
            continue
            
        tipo_tercero = determinar_tipo_tercero(r["rfc_emisor"])
        tipo_operacion = determinar_tipo_operacion(r["concepto"], tipo_tercero) 
        
        filas.append({
            "TipoTercero": tipo_tercero,   
            "TipoOperacion": tipo_operacion, 
            "RFC": r["rfc_emisor"],
            "Nombre": r["nombre_emisor"],
            "IVA_16_Monto": r["iva_16"],
            "IVA_8_Monto": r["iva_8"],
            "Base_Exenta": r["iva_exento"],
            "Retencion_IVA": r["ret_iva"],
            "ImporteTotal": r["total"]
        })
    return pd.DataFrame(filas)

def exportar_txt_sat(df_diot, mes, anio, tipo_decl, output_dir):
    """
    Exporta el TXT de Carga Batch (Enero 2025) de EXACTAMENTE 54 COLUMNAS.
    """
    if df_diot.empty:
        return
        
    meses_str = {"01":"Ene", "02":"Feb", "03":"Mar", "04":"Abr", "05":"May", "06":"Jun", 
                 "07":"Jul", "08":"Ago", "09":"Sep", "10":"Oct", "11":"Nov", "12":"Dic"}
    
    mes_str = str(mes).zfill(2) 
    nombre_mes = meses_str.get(mes_str, "Mes")
    
    filename = f"{mes_str}. {nombre_mes} {anio} {tipo_decl} DIOT.txt"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        for _, r in df_diot.iterrows():
            # Inicializamos un arreglo de 54 posiciones vacías ("")
            # En Python, el índice empieza en 0. (Columna 1 = c[0], Columna 54 = c[53])
            c = [""] * 54
            
            tipo_tercero = r.get('TipoTercero', '04')
            c[0] = tipo_tercero                        # Col 1: Tipo de tercero
            c[1] = r.get('TipoOperacion', '85')        # Col 2: Tipo de operación
            
            # Col 3: RFC (Obligatorio para 04 y 15, vacío para 05)
            if tipo_tercero in ["04", "15"]:
                c[2] = r.get('RFC', '')
                
            # Col 4, 5, 6, 7: Datos de Extranjeros (Solo si es 05)
            if tipo_tercero == "05":
                c[3] = ""                              # Col 4: ID Fiscal
                c[4] = str(r.get('Nombre', ''))[:300]  # Col 5: Nombre Extranjero (Max 300)
                c[5] = "US"                            # Col 6: País (Por defecto ponemos US para no dejarlo vacío)

            # --- VALORES AL 16% ---
            iva_16 = float(r.get('IVA_16_Monto', 0))
            if iva_16 > 0:
                c[11] = str(int(round(iva_16 / 0.16))) # Col 12: Base actos pagados 16%
                c[21] = str(int(round(iva_16)))        # Col 22: IVA Acreditable 16%

            # --- VALORES AL 8% (Frontera) ---
            iva_8 = float(r.get('IVA_8_Monto', 0))
            if iva_8 > 0:
                c[7] = str(int(round(iva_8 / 0.08)))   # Col 8: Base actos pagados Frontera
                c[17] = str(int(round(iva_8)))         # Col 18: IVA Acreditable Frontera

            # --- RETENCIONES ---
            ret_iva = float(r.get('Retencion_IVA', 0))
            if ret_iva > 0:
                c[47] = str(int(round(ret_iva)))       # Col 48: IVA retenido por el contribuyente

            # --- EXENTOS ---
            exento = float(r.get('Base_Exenta', 0))
            if exento > 0:
                c[49] = str(int(round(exento)))        # Col 50: Actos pagados por los que no se pagará el IVA (Exentos)

            # --- MANIFIESTO FINAL ---
            c[53] = "01"                               # Col 54: Manifiesto que se dio efectos fiscales (01 = Sí)

            # Unimos las 54 posiciones con el separador de pipe (|)
            linea = "|".join(c) + "\n"
            f.write(linea)
            
    print(f"✅ Archivo TXT DIOT Carga Masiva (54 columnas) generado: {filename}")