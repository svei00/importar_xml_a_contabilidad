# diot.py
import pandas as pd

def determinar_tipo_tercero(rfc):
    if rfc == "XEXX010101000": return "05" 
    elif rfc == "XAXX010101000": return "15" 
    return "04" 

def determinar_tipo_operacion(concepto):
    concepto_lower = concepto.lower()
    if "arrendamiento" in concepto_lower or "renta" in concepto_lower: return "06"
    elif "honorarios" in concepto_lower or "servicios profesionales" in concepto_lower: return "03"
    return "85" 

def generar_diot(df):
    filas = []
    for _, r in df.iterrows():
        if r["tipo"] not in ["I", "E"]: 
            continue
            
        filas.append({
            "TipoTercero": determinar_tipo_tercero(r["rfc_emisor"]),   
            "TipoOperacion": determinar_tipo_operacion(r["concepto"]), 
            "RFC": r["rfc_emisor"],
            "Monto_IVA_16": int(round(r["iva_16"] / 0.16)) if r["iva_16"] > 0 else 0,
            "Monto_IVA_8": int(round(r["iva_8"] / 0.08)) if r["iva_8"] > 0 else 0,
            "Monto_IVA_Exento": int(round(r["iva_exento"])),
            "Retencion_IVA": int(round(r["ret_iva"])),
            "ImporteTotal": r["total"]
        })
    return pd.DataFrame(filas)

def exportar_txt_sat(df_diot, mes, anio, tipo="N"):
    if df_diot.empty:
        return
        
    meses_str = {"01":"Ene", "02":"Feb", "03":"Mar", "04":"Abr", "05":"May", "06":"Jun", 
                 "07":"Jul", "08":"Ago", "09":"Sep", "10":"Oct", "11":"Nov", "12":"Dic"}
    nombre_mes = meses_str.get(mes, "Mes")
    
    filename = f"{mes}. {nombre_mes} {anio} {tipo} DIOT.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        for _, r in df_diot.iterrows():
            linea = f"{r['TipoTercero']}|{r['TipoOperacion']}|||{r['RFC']}|||||{r['Monto_IVA_16']}||{r['Monto_IVA_8']}||||||||{r['Monto_IVA_Exento']}|||{r['Retencion_IVA']}|0|\n"
            f.write(linea)
            
    print(f"✅ Archivo TXT para la DIOT generado exitosamente: {filename}")