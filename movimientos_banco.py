"""
movimientos_banco.py - Hoja MOVIMIENTOS_BANCO (regla G, primera parte).

Problema (caso G): un retiro en ventanilla de 2,354.78 pago varias cosas a la vez
(IMSS 2,108.78 + 246.00 de otro concepto). La app genera una poliza por 2,108.78 contra
banco, y ese cargo nunca existio en el estado de cuenta. Mientras la app no lea los
estados de cuenta (Parte 2), esta hoja deja ver TODO lo que las polizas cargan o abonan
a banco, dia por dia con su suma, para compararlo contra el estado de cuenta de un vistazo.

Se consideran cuentas de banco las que empiezan con 102 (codigo agrupador SAT 102 = Bancos).
Solo cuentan las polizas que SI entran al TXT (las bloqueadas no se importan).
"""
import pandas as pd

PREFIJO_BANCOS = "102"
COLUMNAS = ["Fecha", "Cuenta", "Referencia", "Concepto", "Cargo", "Abono", "UUID"]


def es_cuenta_de_banco(cuenta):
    """'10201001' o '102-01-001' -> True."""
    return str(cuenta).replace("-", "").strip().startswith(PREFIJO_BANCOS)


def _fila_de_total(fecha, cuenta, cargo, abono):
    """Renglon 'TOTAL DEL DIA' con el neto (cargos - abonos) en el concepto."""
    neto = round(cargo - abono, 2)
    return {"Fecha": fecha, "Cuenta": cuenta, "Referencia": "",
            "Concepto": f"TOTAL DEL DIA (neto {neto:+.2f})",
            "Cargo": round(cargo, 2), "Abono": round(abono, 2), "UUID": ""}


def construir_movimientos_de_banco(polizas_df, numeros_excluidos=()):
    """
    Una fila por cada linea a banco (ordenadas por fecha y cuenta) y, despues de las de
    cada (fecha, cuenta), un renglon TOTAL DEL DIA. Devuelve un DataFrame (vacio si no hay).
    """
    if polizas_df is None or polizas_df.empty:
        return pd.DataFrame(columns=COLUMNAS)
    excluidos = set(numeros_excluidos)
    lineas = polizas_df[polizas_df["Cuenta"].apply(es_cuenta_de_banco)
                        & ~polizas_df["Numero"].isin(excluidos)]
    if lineas.empty:
        return pd.DataFrame(columns=COLUMNAS)

    filas = []
    for (fecha, cuenta), grupo in lineas.sort_values(["Fecha", "Cuenta", "Numero"], kind="mergesort") \
                                        .groupby(["Fecha", "Cuenta"], sort=False):
        for _, r in grupo.iterrows():
            filas.append({"Fecha": fecha, "Cuenta": cuenta, "Referencia": r.get("Referencia", ""),
                          "Concepto": r.get("Concepto", ""), "Cargo": round(float(r["Debe"]), 2),
                          "Abono": round(float(r["Haber"]), 2), "UUID": r.get("UUID", "")})
        filas.append(_fila_de_total(fecha, cuenta, float(grupo["Debe"].sum()), float(grupo["Haber"].sum())))
    return pd.DataFrame(filas, columns=COLUMNAS)
