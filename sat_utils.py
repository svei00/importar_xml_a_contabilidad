import requests

def validar_uuid(uuid, re, rr, tt):
    url = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"

    params = {
        "re": re,
        "rr": rr,
        "tt": tt,
        "id": uuid
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        if "Vigente" in r.text:
            return "Vigente"
        elif "Cancelado" in r.text:
            return "Cancelado"
        else:
            return "Desconocido"
    except:
        return "Error"