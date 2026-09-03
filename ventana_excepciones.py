"""
ventana_excepciones.py - Pantalla de revision ANTES de escribir los archivos.

Regla de oro del proyecto: nada se resuelve en silencio. Aqui Svei ve, de un vistazo,
todo lo que la app no pudo decidir sola o dejo fuera a proposito:
  * BLOQUEANTES (rojo): esas polizas NO entraran al TXT hasta que Svei las resuelva.
  * INFORMATIVAS (amarillo): la app ya decidio algo (omitio una reexpedicion, mando un
    pago a la cuenta del socio...) y quiere que lo sepas.

Dos botones: continuar y generar los archivos, o cancelar sin escribir nada.

El texto que se muestra lo arma construir_texto_de_resumen (logica pura, con pruebas);
la ventana solo lo dibuja.
"""
import tkinter as tk
from tkinter import Frame, Button, Label, Text, Scrollbar

from excepciones import BLOQUEANTE, INFORMATIVA

FONDO = "#1E1E2E"
TEXTO = "#CDD6F4"
ROJO = "#F38BA8"
AMARILLO = "#F9E2AF"
GRIS = "#A6ADC8"


def construir_texto_de_resumen(total_polizas, polizas_bloqueadas):
    """Frase de arriba: cuantas polizas se generan y cuantas quedan fuera por avisos bloqueantes."""
    if polizas_bloqueadas:
        verbo = "quedara" if polizas_bloqueadas == 1 else "quedaran"
        return (f"{total_polizas - polizas_bloqueadas} de {total_polizas} polizas se generaran; "
                f"{polizas_bloqueadas} {verbo} FUERA del TXT por avisos bloqueantes.")
    return f"Las {total_polizas} polizas se generaran. Revisa los avisos informativos."


def texto_del_boton_de_continuar(hay_bloqueantes):
    return "Generar TXT sin las bloqueadas" if hay_bloqueantes else "Generar archivos"


def lineas_de_una_excepcion(excepcion):
    """Lo que se escribe para cada aviso: encabezado, mensaje y (si hay) sugerencia."""
    corto = excepcion.uuid[:8] if excepcion.uuid else "lote"
    lineas = [(f"{excepcion.codigo}  ({corto})", "titulo"), (f"   {excepcion.mensaje}", "mensaje")]
    if excepcion.sugerencia:
        lineas.append((f"   -> {excepcion.sugerencia}", "sugerencia"))
    return lineas


def _escribir_seccion(texto, titulo, excepciones, color_etiqueta):
    """Una seccion (bloqueantes o informativas) dentro del cuadro de texto."""
    if not excepciones:
        return
    texto.insert(tk.END, f"{titulo} ({len(excepciones)})\n", color_etiqueta)
    for excepcion in excepciones:
        for linea, etiqueta in lineas_de_una_excepcion(excepcion):
            texto.insert(tk.END, linea + "\n", etiqueta)
        texto.insert(tk.END, "\n")


def mostrar_ventana_de_excepciones(titulo, resumen, colector):
    """
    Muestra la ventana (modal) y devuelve True si Svei decide continuar, False si cancela.
    `titulo` y `resumen` son textos ya armados; `colector` trae las excepciones.
    """
    por_severidad = colector.por_severidad()
    hay_bloqueantes = bool(por_severidad[BLOQUEANTE])
    decision = {"continuar": False}

    ventana = tk.Toplevel()
    ventana.title(titulo)
    ventana.geometry("860x560")
    ventana.configure(bg=FONDO)

    Label(ventana, text="Revisión antes de generar los archivos", bg=FONDO, fg=AMARILLO,
          font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    Label(ventana, text=resumen, bg=FONDO, fg=ROJO if hay_bloqueantes else TEXTO,
          font=("Segoe UI", 10, "bold"), wraplength=820, justify="left").pack(anchor="w", padx=14)

    marco = Frame(ventana, bg=FONDO)
    marco.pack(fill="both", expand=True, padx=14, pady=10)
    barra = Scrollbar(marco)
    barra.pack(side=tk.RIGHT, fill=tk.Y)
    cuadro = Text(marco, bg="#181825", fg=TEXTO, font=("Consolas", 10), wrap="word",
                  relief="flat", yscrollcommand=barra.set)
    cuadro.pack(fill="both", expand=True)
    barra.config(command=cuadro.yview)

    cuadro.tag_configure("bloqueante", foreground=ROJO, font=("Consolas", 11, "bold"))
    cuadro.tag_configure("informativa", foreground=AMARILLO, font=("Consolas", 11, "bold"))
    cuadro.tag_configure("titulo", foreground=TEXTO, font=("Consolas", 10, "bold"))
    cuadro.tag_configure("mensaje", foreground=TEXTO)
    cuadro.tag_configure("sugerencia", foreground=GRIS)
    _escribir_seccion(cuadro, "BLOQUEANTES: estas polizas NO van al TXT", por_severidad[BLOQUEANTE], "bloqueante")
    _escribir_seccion(cuadro, "INFORMATIVAS: la app ya decidio, solo para que lo sepas", por_severidad[INFORMATIVA], "informativa")
    cuadro.config(state="disabled")

    def continuar():
        decision["continuar"] = True
        ventana.destroy()

    botones = Frame(ventana, bg=FONDO)
    botones.pack(fill="x", padx=14, pady=(0, 12))
    Button(botones, text=texto_del_boton_de_continuar(hay_bloqueantes), bg="#38A169", fg="white",
           font=("Segoe UI", 10, "bold"), relief="flat", pady=6, command=continuar).pack(side=tk.LEFT)
    Button(botones, text="Cancelar (no generar nada)", bg="#45475A", fg="white",
           font=("Segoe UI", 10, "bold"), relief="flat", pady=6,
           command=ventana.destroy).pack(side=tk.LEFT, padx=10)

    ventana.transient()
    ventana.grab_set()
    ventana.wait_window()
    return decision["continuar"]
