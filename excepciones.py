"""
excepciones.py - Lista de "cosas que la app NO pudo decidir sola".

Idea central (regla de oro del proyecto): NADA se resuelve en silencio.
Cada vez que una regla contable encuentra algo raro (un CFDI cancelado, una
reexpedicion, una forma de pago sin mapeo...) NO lo esconde: lo anota aqui.
Despues la app muestra esta lista en el Log y en la hoja EXCEPCIONES del Excel.

Severidades:
  - "bloqueante":  la poliza NO debe ir al TXT hasta que Svei decida.
  - "informativa": la poliza si va al TXT (o la fila se omitio a proposito),
                   pero Svei debe enterarse.

Este archivo NO importa Tkinter ni pandas: es logica pura y facil de probar.
"""
from dataclasses import dataclass

# --- Severidades -----------------------------------------------------------
BLOQUEANTE = "bloqueante"
INFORMATIVA = "informativa"

# --- Codigos de la Fase 1 (cada fase futura agrega los suyos) ---------------
CANCELADO = "CANCELADO"
ESTATUS_SAT_DESCONOCIDO = "ESTATUS_SAT_DESCONOCIDO"
FUERA_DE_PERIODO = "FUERA_DE_PERIODO"

# --- Codigos de la Fase 2 ---------------------------------------------------
REEXPEDICION = "REEXPEDICION"
PAGO_DE_DOCUMENTO_NO_REGISTRADO = "PAGO_DE_DOCUMENTO_NO_REGISTRADO"
PAGO_DESCUADRADO_CON_DOCUMENTOS = "PAGO_DESCUADRADO_CON_DOCUMENTOS"

# --- Codigos de la Fase 3 ---------------------------------------------------
FORMA_PAGO_SIN_MAPEO = "FORMA_PAGO_SIN_MAPEO"
FORMA_PAGO_ADVERTIDA = "FORMA_PAGO_ADVERTIDA"
REP_CON_VARIOS_PAGOS = "REP_CON_VARIOS_PAGOS"
PAGO_DE_PERIODO_ANTERIOR = "PAGO_DE_PERIODO_ANTERIOR"
SALDO_INSOLUTO = "SALDO_INSOLUTO"
FOLIO_IMSS_ILEGIBLE = "FOLIO_IMSS_ILEGIBLE"

# --- Codigos de la Fase 4 ---------------------------------------------------
CUENTA_INVALIDA = "CUENTA_INVALIDA"
CUENTA_FUERA_DE_ESPEJO = "CUENTA_FUERA_DE_ESPEJO"
CATALOGO_NO_DISPONIBLE = "CATALOGO_NO_DISPONIBLE"

# --- Codigos de la Fase 5 ---------------------------------------------------
PASIVO_SIN_SALDO = "PASIVO_SIN_SALDO"
PASIVO_SALDO_PARCIAL = "PASIVO_SALDO_PARCIAL"
BALANZA_NO_DISPONIBLE = "BALANZA_NO_DISPONIBLE"


@dataclass
class Excepcion:
    """Una sola cosa que la app no decidio sola."""
    codigo: str          # p.ej. "CANCELADO"
    severidad: str       # BLOQUEANTE o INFORMATIVA
    uuid: str            # UUID del CFDI afectado ("" si aplica a todo el lote)
    mensaje: str         # que paso, en lenguaje natural
    sugerencia: str = "" # que deberia hacer Svei


class ColectorDeExcepciones:
    """Junta las excepciones de una corrida completa."""

    def __init__(self):
        self._lista = []

    def agregar(self, codigo, severidad, uuid, mensaje, sugerencia=""):
        """Anota una excepcion nueva."""
        self._lista.append(Excepcion(codigo, severidad, str(uuid or ""), mensaje, sugerencia))

    def todas(self):
        """Todas las excepciones, en el orden en que se anotaron."""
        return list(self._lista)

    def bloqueantes(self):
        """Solo las que impiden mandar la poliza al TXT."""
        return [e for e in self._lista if e.severidad == BLOQUEANTE]

    def por_uuid(self, uuid):
        """Las excepciones de un CFDI en particular."""
        uuid = str(uuid or "")
        return [e for e in self._lista if e.uuid == uuid]

    def uuids_bloqueados(self):
        """UUID de los CFDI que tienen al menos una excepcion bloqueante."""
        return {e.uuid for e in self.bloqueantes() if e.uuid}

    def por_severidad(self):
        """{'bloqueante': [...], 'informativa': [...]} para mostrarlas agrupadas en la ventana."""
        return {BLOQUEANTE: self.bloqueantes(),
                INFORMATIVA: [e for e in self._lista if e.severidad == INFORMATIVA]}

    def cuantas(self):
        return len(self._lista)

    def como_filas(self):
        """Lista de diccionarios lista para convertir en la hoja EXCEPCIONES."""
        return [
            {"Codigo": e.codigo, "Severidad": e.severidad, "UUID": e.uuid,
             "Mensaje": e.mensaje, "Sugerencia": e.sugerencia}
            for e in self._lista
        ]

    def imprimir_en_log(self):
        """Escribe cada excepcion en el Log (print), una por linea."""
        for e in self._lista:
            corto = e.uuid[:8] if e.uuid else "lote"
            print(f"   [{e.severidad.upper()}] {e.codigo} ({corto}): {e.mensaje}")
