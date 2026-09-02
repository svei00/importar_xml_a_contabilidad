"""
resumen_corrida.py - Regla I: que hacer cuando una corrida no produce polizas.

Ejemplo real (agosto 2026): la carpeta de EMITIDAS trae 8 XML y los 8 son
nomina. Con nomina_modo = "contpaqi" las polizas de nomina las genera CONTPAQi
Nominas, asi que la app no tiene nada que contabilizar. En vez de escribir un
TXT y un Excel vacios, la app AVISA con el desglose y NO genera archivos.

Este archivo solo cuenta y redacta; la ventana (messagebox) la muestra main.py.
"""

# Palabras para el aviso segun el tipo de corrida.
_NOMBRE_OPERACION = {"ingresos": "ingresos", "egresos": "egresos"}


def desglose_corrida(filas):
    """
    Cuenta que habia en la carpeta. Cada fila trae 'tipo' (I, E, P, N) y la
    bandera 'omitir' con su 'motivo_omision' ('cancelado', 'nomina', ...).
    """
    desglose = {"total_xml": len(filas), "nomina": 0, "cancelados": 0,
                "facturas": 0, "notas_credito": 0, "pagos_rep": 0, "contabilizables": 0,
                "reexpediciones": 0}
    for fila in filas:
        if fila.get("omitir"):
            if fila.get("motivo_omision") == "cancelado":
                desglose["cancelados"] += 1
            elif fila.get("motivo_omision") == "nomina":
                desglose["nomina"] += 1
            elif fila.get("motivo_omision") == "reexpedicion":
                desglose["reexpediciones"] += 1
            continue
        desglose["contabilizables"] += 1
        tipo = fila.get("tipo")
        if tipo == "I":
            desglose["facturas"] += 1
        elif tipo == "E":
            desglose["notas_credito"] += 1
        elif tipo == "P":
            desglose["pagos_rep"] += 1
    return desglose


def hay_algo_que_contabilizar(desglose):
    """True si al menos un CFDI puede producir poliza."""
    return desglose["contabilizables"] > 0


def redactar_aviso_mes_vacio(empresa_rfc, periodo, tipo_operacion, desglose):
    """
    Texto del messagebox. (titulo, mensaje).
    Ejemplo: 'Sin ingresos que contabilizar - 08/2026 (EEA251205CR8)'.
    """
    operacion = _NOMBRE_OPERACION.get(tipo_operacion, tipo_operacion)
    if periodo:
        anio, mes = periodo.split("-")
        etiqueta_periodo = f"{mes}/{anio}"
    else:
        etiqueta_periodo = "periodo desconocido"
    titulo = f"Sin {operacion} que contabilizar - {etiqueta_periodo} ({empresa_rfc})"

    ventas = "facturas de venta" if tipo_operacion == "ingresos" else "facturas de compra"
    cobros = "cobros (REP)" if tipo_operacion == "ingresos" else "pagos (REP)"
    mensaje = (
        f"Se leyeron {desglose['total_xml']} XML: "
        f"{desglose['nomina']} nomina (CONTPAQi Nominas genera esas polizas), "
        f"{desglose['facturas']} {ventas}, "
        f"{desglose['pagos_rep']} {cobros}, "
        f"{desglose['notas_credito']} notas de credito, "
        f"{desglose['cancelados']} cancelados, "
        f"{desglose['reexpediciones']} reexpediciones.\n\n"
        "No se generó archivo de pólizas"
        + (" ni TXT de DIOT." if tipo_operacion == "egresos" else ".")
    )
    return titulo, mensaje


def redactar_aviso_sin_xml(carpeta):
    """Texto cuando la carpeta ni siquiera trae XML o ZIP legibles."""
    return ("Carpeta sin CFDI",
            f"No se encontraron XML ni ZIP validos en:\n{carpeta}\n\n"
            "No se generó ningún archivo.")
