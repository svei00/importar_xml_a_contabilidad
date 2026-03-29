import os
import zipfile
import xml.etree.ElementTree as ET

NS = {
    'cfdi': 'http://www.sat.gob.mx/cfd/4',
    'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
}

def parse_xml(source):
    tree = ET.parse(source)
    root = tree.getroot()

    tipo = root.attrib.get("TipoDeComprobante", "")
    total = float(root.attrib.get("Total", 0))
    subtotal = float(root.attrib.get("SubTotal", 0))
    cp = root.attrib.get("LugarExpedicion", "")

    em = root.find('cfdi:Emisor', NS)
    re = root.find('cfdi:Receptor', NS)
    rfc_emisor = em.attrib.get("Rfc", "") if em is not None else ""
    rfc_receptor = re.attrib.get("Rfc", "") if re is not None else ""
    
    tfd = root.find('.//tfd:TimbreFiscalDigital', NS)
    uuid = tfd.attrib.get("UUID") if tfd is not None else None

    concepto = ""
    c = root.find('cfdi:Conceptos/cfdi:Concepto', NS)
    if c is not None:
        concepto = c.attrib.get("Descripcion", "")

    iva_16, iva_8, iva_exento = 0.0, 0.0, 0.0
    ret_iva, ret_isr = 0.0, 0.0

    for t in root.findall('.//cfdi:Impuestos/cfdi:Traslados/cfdi:Traslado', NS):
        if t.attrib.get("Impuesto") == "002": 
            tasa = t.attrib.get("TasaOCuota", "0")
            importe = float(t.attrib.get("Importe", 0))
            if tasa == "0.160000":
                iva_16 += importe
            elif tasa == "0.080000":
                iva_8 += importe
            elif t.attrib.get("TipoFactor") == "Exento":
                iva_exento += float(t.attrib.get("Base", 0)) 

    for r in root.findall('.//cfdi:Impuestos/cfdi:Retenciones/cfdi:Retencion', NS):
        impuesto = r.attrib.get("Impuesto")
        importe = float(r.attrib.get("Importe", 0))
        if impuesto == "001": 
            ret_isr += importe
        elif impuesto == "002": 
            ret_iva += importe

    return {
        "uuid": uuid, "tipo": tipo, "fecha": root.attrib.get("Fecha"),
        "rfc_emisor": rfc_emisor, "rfc_receptor": rfc_receptor,
        "nombre_emisor": em.attrib.get("Nombre", "") if em is not None else "",
        "nombre_receptor": re.attrib.get("Nombre", "") if re is not None else "", # <--- ¡LA SOLUCIÓN AL KEYERROR!
        "concepto": concepto, "subtotal": subtotal, "total": total, "cp": cp,
        "iva_16": iva_16, "iva_8": iva_8, "iva_exento": iva_exento,
        "ret_iva": ret_iva, "ret_isr": ret_isr
    }

def load_folder(folder):
    rows = []
    for f in os.listdir(folder):
        full_path = os.path.join(folder, f)
        
        if f.lower().endswith(".xml"):
            try:
                rows.append(parse_xml(full_path))
            except Exception as e:
                print(f"❌ Error parseando {f}: {e}")
                
        elif f.lower().endswith(".zip"):
            print(f"📦 Extrayendo facturas de {f}...")
            try:
                with zipfile.ZipFile(full_path, 'r') as z:
                    for xml_name in z.namelist():
                        if xml_name.lower().endswith(".xml"):
                            with z.open(xml_name) as xml_file:
                                try:
                                    rows.append(parse_xml(xml_file))
                                except Exception as e:
                                    print(f"❌ Error leyendo XML dentro de ZIP {xml_name}: {e}")
            except Exception as e:
                print(f"❌ Error al abrir el ZIP {f}: {e}")
                
    return rows

def es_pago(tipo):
    """
    Regla simple: Si el atributo TipoDeComprobante es 'P', es un CFDI de Pago.
    """
    return tipo == "P"