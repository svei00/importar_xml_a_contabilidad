import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"

def obtener_sesion_robusta():
    session = requests.Session()
    # Retry 3 veces, esperando 0.5s, 1s, 2s entre cada intento
    retry = Retry(connect=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def validar(uuid, re, rr, tt):
    try:
        session = obtener_sesion_robusta()
        params = {"re": re, "rr": rr, "tt": tt, "id": uuid}
        
        # Hacemos el GET usando la sesión blindada
        r = session.get(URL, params=params, timeout=10)
        txt = r.text.lower()
        
        if "vigente" in txt:
            return "VIGENTE"
        if "cancelado" in txt:
            return "CANCELADO"
            
        return "DESCONOCIDO"
        
    except requests.exceptions.RequestException as e:
        # En lugar de crashear en silencio, lo mandamos al log
        print(f"⚠️ SAT Error/Timeout para UUID {uuid[:8]}: {e}")
        return "ERROR"