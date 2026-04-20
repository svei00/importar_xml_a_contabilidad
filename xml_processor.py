import os
import zipfile
import xml.etree.ElementTree as ET

def parse_xml(source):
    tree = ET.parse(source)
    root = tree.getroot()

    ns_cfdi = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
    
    tipo = root.attrib.get("TipoDeComprobante", "")
    total = float(root.attrib.get("Total", 0))
    subtotal = float(root.attrib.get("SubTotal", 0))
    cp = root.attrib.get("LugarExpedicion", "")
    metodo_pago = root.attrib.get("MetodoPago", "")
    
    # NUEVO: Referencia base con guion (Ej. F-1234)
    serie = root.attrib.get("Serie", "")
    folio = root.attrib.get("Folio", "")
    referencia_xml = f"{serie}-{folio}".strip("-")

    em = root.find(f'{ns_cfdi}Emisor')
    re = root.find(f'{ns_cfdi}Receptor')
    rfc_emisor = em.attrib.get("Rfc", "") if em is not None else ""
    rfc_receptor = re.attrib.get("Rfc", "") if re is not None else ""
    
    uuid = None
    for elem in root.iter():
        if elem.tag.endswith('TimbreFiscalDigital'):
            uuid = elem.attrib.get("UUID")
            break

    concepto = ""
    c = root.find(f'{ns_cfdi}Conceptos/{ns_cfdi}Concepto')
    if c is not None:
        concepto = c.attrib.get("Descripcion", "")

    departamento = "General"
    iva_16, iva_8, iva_exento, ieps = 0.0, 0.0, 0.0, 0.0
    ret_iva, ret_isr = 0.0, 0.0
    monto_pago_rep = 0.0
    doctos_relacionados = []

    nodo_impuestos_global = root.find(f'./{ns_cfdi}Impuestos')
    if nodo_impuestos_global is not None:
        for t in nodo_impuestos_global.findall(f'.//{ns_cfdi}Traslado'):
            impuesto = t.attrib.get("Impuesto")
            importe = float(t.attrib.get("Importe", 0))
            if impuesto == "002":
                tasa = t.attrib.get("TasaOCuota", "0")
                if tasa == "0.160000": iva_16 += importe
                elif tasa == "0.080000": iva_8 += importe
            elif impuesto == "003":
                ieps += importe
                
        for r in nodo_impuestos_global.findall(f'.//{ns_cfdi}Retencion'):
            impuesto = r.attrib.get("Impuesto")
            importe = float(r.attrib.get("Importe", 0))
            if impuesto == "001": ret_isr += importe
            elif impuesto == "002": ret_iva += importe

    for elem in root.iter():
        tag = elem.tag.split('}')[-1]
        
        if tag == 'Receptor' and tipo == 'N':
            departamento = elem.attrib.get("Departamento", "General")
            
        elif tag == 'Pago':
            monto_pago_rep += float(elem.attrib.get("Monto", 0))
            metodo_pago = "PPD"
            
        elif tag == 'DoctoRelacionado':
            doc_id = elem.attrib.get("IdDocumento")
            if doc_id: doctos_relacionados.append(doc_id)
            
        elif tag == 'TrasladoP':
            if elem.attrib.get("ImpuestoP") == "002":
                tasa = elem.attrib.get("TasaOCuotaP", "0")
                if tasa == "0.160000":
                    iva_16 += float(elem.attrib.get("ImporteP", 0))

    if tipo == "P":
        total = monto_pago_rep
        concepto = f"Pago a UUID: {doctos_relacionados[0][:8]}..." if doctos_relacionados else "REP de Pago"
        referencia_xml = doctos_relacionados[0][:8] if doctos_relacionados else "REP"
    elif not metodo_pago:
        metodo_pago = "PUE" 
        
    return {
        "uuid": uuid, "tipo": tipo, "fecha": root.attrib.get("Fecha"),
        "metodo_pago": metodo_pago, "departamento": departamento, 
        "rfc_emisor": rfc_emisor, "rfc_receptor": rfc_receptor,
        "nombre_emisor": em.attrib.get("Nombre", "") if em is not None else "",
        "nombre_receptor": re.attrib.get("Nombre", "") if re is not None else "",
        "concepto": concepto, "subtotal": subtotal, "total": total, "cp": cp,
        "iva_16": iva_16, "iva_8": iva_8, "iva_exento": iva_exento, "ieps": ieps,
        "ret_iva": ret_iva, "ret_isr": ret_isr, "referencia": referencia_xml
    }

def load_folder(folder):
    rows = []
    for f in os.listdir(folder):
        full_path = os.path.join(folder, f)
        if f.lower().endswith(".xml"):
            try: rows.append(parse_xml(full_path))
            except Exception: pass
        elif f.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(full_path, 'r') as z:
                    for xml_name in z.namelist():
                        if xml_name.lower().endswith(".xml"):
                            with z.open(xml_name) as xml_file:
                                try: rows.append(parse_xml(xml_file))
                                except Exception: pass
            except Exception: pass
    return rows

def es_pago(tipo): return tipo == "P"