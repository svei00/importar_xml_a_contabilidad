# xml_processor.py
import os
import xml.etree.ElementTree as ET

NS = {
    'cfdi': 'http://www.sat.gob.mx/cfd/4',
    'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
}

def parse_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()

    tipo = root.attrib.get("TipoDeComprobante")  # I,E,P
    total = float(root.attrib.get("Total", 0))
    subtotal = float(root.attrib.get("SubTotal", 0))
    cp = root.attrib.get("LugarExpedicion", "")

    em = root.find('cfdi:Emisor', NS).attrib
    re = root.find('cfdi:Receptor', NS).attrib

    tfd = root.find('.//tfd:TimbreFiscalDigital', NS)
    uuid = tfd.attrib.get("UUID") if tfd is not None else None

    # concepto principal (simplificado)
    concepto = ""
    c = root.find('cfdi:Conceptos/cfdi:Concepto', NS)
    if c is not None:
        concepto = c.attrib.get("Descripcion", "")

    # IVA real
    iva = 0.0
    for t in root.findall('.//cfdi:Traslado', NS):
        if t.attrib.get("Impuesto") == "002":
            iva += float(t.attrib.get("Importe", 0))

    return {
        "uuid": uuid,
        "tipo": tipo,
        "fecha": root.attrib.get("Fecha"),
        "rfc_emisor": em.get("Rfc"),
        "rfc_receptor": re.get("Rfc"),
        "nombre_emisor": em.get("Nombre",""),
        "nombre_receptor": re.get("Nombre",""),
        "concepto": concepto,
        "subtotal": subtotal,
        "iva": iva,
        "total": total,
        "cp": cp
    }

def load_folder(folder):
    rows = []
    for f in os.listdir(folder):
        if f.lower().endswith(".xml"):
            try:
                rows.append(parse_xml(os.path.join(folder, f)))
            except Exception as e:
                print("Error:", f, e)
    return rows

def es_pago(tipo):
    return tipo == "P"