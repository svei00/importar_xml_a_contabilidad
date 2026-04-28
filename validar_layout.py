"""
validar_layout.py — Verificador del TXT de pólizas para CONTPAQi.

CONTPAQi importa las pólizas con un formato de ANCHO FIJO: lee cada dato en una
columna exacta. Si un campo se corre aunque sea 1 carácter, CONTPAQi se "come" el
primer dígito de los importes (3915.00 -> 915.00), la póliza queda descuadrada y
termina usando la cuenta de cuadre o rechazando el asiento.

Este script valida un TXT generado y avisa ANTES de subirlo a CONTPAQi:
  1. Que el importe de cada movimiento (M1) empiece en la COLUMNA 67 (índice 0).
  2. Que el bloque fiscal "0.0" caiga en la columna 99.
  3. Que cada póliza (P ... sus M1) cuadre: suma de Cargos == suma de Abonos.

Uso:
    python validar_layout.py "ruta\\Polizas_CONTPAQi_....txt"

Columnas de referencia obtenidas midiendo una exportación real de CONTPAQi.
"""
import sys
import re

# --- Mapa de columnas FIJO (índice base 0), medido contra un export real de CONTPAQi ---
COL_CUENTA = 3      # la cuenta arranca aquí
ANCHO_CUENTA = 31   # campo cuenta: 31 caracteres
COL_REF = 34        # referencia arranca aquí (3 + 31)
ANCHO_REF = 31
COL_NATURALEZA = 65  # '0' = Cargo, '1' = Abono
COL_IMPORTE = 67     # el importe DEBE empezar aquí
COL_BLOQUE_00 = 99   # el bloque fiscal "0.0" cae aquí


def parse_importe(linea):
    """Lee el importe del M1 desde la columna fija y lo regresa como float."""
    trozo = linea[COL_IMPORTE:COL_IMPORTE + 21].strip()
    try:
        return float(trozo.split()[0])
    except (ValueError, IndexError):
        return None


def validar(path):
    with open(path, "r", encoding="windows-1252", errors="replace") as f:
        lineas = f.read().splitlines()

    errores = []
    advertencias = []
    pol_actual = None          # (num_linea, etiqueta)
    cargos = abonos = 0.0
    n_polizas = n_mov = 0

    def cerrar_poliza():
        nonlocal cargos, abonos
        if pol_actual is not None:
            dif = round(cargos - abonos, 2)
            if abs(dif) >= 0.01:
                errores.append(
                    f"  Póliza '{pol_actual[1]}' (línea {pol_actual[0]}) DESCUADRADA: "
                    f"Cargos={cargos:.2f}  Abonos={abonos:.2f}  Dif={dif:+.2f}"
                )
        cargos = abonos = 0.0

    for i, linea in enumerate(lineas, start=1):
        if linea.startswith("P "):
            cerrar_poliza()
            n_polizas += 1
            etiqueta = linea[40:80].strip() or f"#{n_polizas}"
            pol_actual = (i, etiqueta)
        elif linea.startswith("M1"):
            n_mov += 1
            # 1) Columna del importe
            nat = linea[COL_NATURALEZA] if len(linea) > COL_NATURALEZA else "?"
            if nat not in ("0", "1"):
                errores.append(f"  Línea {i}: naturaleza Cargo/Abono no está en col {COL_NATURALEZA} (se vio '{nat}').")
            # 2) El importe debe empezar en COL_IMPORTE (no un espacio)
            if len(linea) <= COL_IMPORTE or linea[COL_IMPORTE] == " ":
                errores.append(f"  Línea {i}: el importe NO empieza en la columna {COL_IMPORTE}. "
                               f"CONTPAQi se comería el primer dígito.")
            imp = parse_importe(linea)
            if imp is None:
                errores.append(f"  Línea {i}: no se pudo leer el importe en la columna {COL_IMPORTE}.")
            else:
                if nat == "0":
                    cargos += imp
                elif nat == "1":
                    abonos += imp
            # 3) Sanidad del bloque fiscal "0.0"
            if not (len(linea) > COL_BLOQUE_00 and linea[COL_BLOQUE_00:COL_BLOQUE_00 + 3] == "0.0"):
                advertencias.append(f"  Línea {i}: el bloque '0.0' no cae en la columna {COL_BLOQUE_00}.")
            # 4) Cuenta vacía / pendiente
            cuenta = linea[COL_CUENTA:COL_CUENTA + ANCHO_CUENTA].strip()
            if not cuenta or not cuenta.replace("-", "").isdigit():
                errores.append(f"  Línea {i}: cuenta inválida o vacía ('{cuenta}').")

    cerrar_poliza()

    print(f"\n=== Validacion de: {path} ===")
    print(f"Polizas: {n_polizas} | Movimientos: {n_mov}")
    if advertencias:
        print(f"\n[AVISO] {len(advertencias)} advertencia(s):")
        for a in advertencias[:20]:
            print(a)
    if errores:
        print(f"\n[ERROR] {len(errores)} error(es) -- NO subir a CONTPAQi hasta corregir:")
        for e in errores:
            print(e)
        return 1
    print("\n[OK] Layout y cuadre correctos. Listo para importar a CONTPAQi.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python validar_layout.py <ruta_del_TXT>")
        sys.exit(2)
    sys.exit(validar(sys.argv[1]))
