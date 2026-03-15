# sat_validator.py
import requests

URL = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"

def validar(uuid, re, rr, tt):
    try:
        params = {"re": re, "rr": rr, "tt": tt, "id": uuid}
        r = requests.get(URL, params=params, timeout=10)
        txt = r.text.lower()
        if "vigente" in txt:
            return "VIGENTE"
        if "cancelado" in txt:
            return "CANCELADO"
        return "DESCONOCIDO"
    except:
        return "ERROR"