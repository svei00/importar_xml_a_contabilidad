# HANDOFF — Orden cronológico de folios de póliza

> Documento standalone para la sesión de implementación (Sonnet 5 u Opus 4.8).
> No requiere el transcript de la sesión de diseño. Fase de diseño cerrada
> el 2026-07-18 con decisiones aprobadas por Svei.

## 1. Diagnóstico confirmado (no re-diagnosticar)

El folio de póliza que llega al TXT de CONTPAQi no guarda relación con la
fecha del documento: una factura del día 23 puede salir con folio 14 y una
del día 3 con folio 27. CONTPAQi NO es el culpable — importa las pólizas
en el orden exacto en que aparecen en el TXT. La cadena del bug en esta app:

1. `xml_processor.py` → `load_folder()` recorre la carpeta con
   `os.listdir()` (línea ~105): orden arbitrario del sistema de archivos,
   esencialmente alfabético por nombre de archivo.
2. `main.py` (línea ~105): `df = pd.DataFrame(enriched)` hereda ese orden.
   Nadie ordena por fecha en ningún punto del pipeline.
3. `export.py` → `generar_polizas()` (líneas ~46-50): `num` arranca en 1
   y avanza por cada documento en el orden en que llega. Ese `num` es el
   folio de póliza.

Dato clave que simplifica el fix: `parse_xml()` guarda el atributo `Fecha`
del CFDI **crudo** (`root.attrib.get("Fecha")`, línea ~92), y en CFDI 4.0
ese atributo es un timestamp ISO completo (`2026-06-23T14:35:12`). El día
solo se recorta en export (`split("T")[0]`). Los strings ISO ordenan
correctamente de forma lexicográfica → **no hay que tocar el parser ni
extraer nada nuevo del XML**.

## 2. Decisiones cerradas con Svei (2026-07-18)

| Decisión | Resolución |
|---|---|
| Criterio de orden | `fecha` completa (timestamp ISO con hora), **ascendente**: documento más antiguo = folio 1. |
| Desempate | `uuid` ascendente cuando dos documentos comparten timestamp exacto. Orden estable (mergesort) como último recurso. |
| Pagos PPD/REP | **Cronológico puro, sin caso especial.** El REP se timbra después del pago y del PPD, así que el orden natural ya lo pone después. La asociación pago-factura en CONTPAQi es por UUID (ADD), no por folio: un folio "fuera de lugar" no rompe nada funcional. Si un REP quedara antes que su factura es escenario de cancelación/retimbrado que se rehace manualmente de todos modos. |
| Nómina (tipo N) | En el modo default `nomina_modo = "contpaqi"` la nómina se brinca (no genera póliza), así que no le aplica orden. En modo `"xml"` (preparado para clientes futuros): misma regla cronológica que todo lo demás, sin agrupamiento especial. |
| Ingresos vs egresos | Ambos flujos pasan por el mismo `generar_polizas()`. Un solo fix cubre los dos. |

## 3. Diseño del cambio

### Dónde ordenar: en `exportar()` de `export.py`, no en `main.py` ni en `load_folder()`

Ordenar el `df` al inicio de `exportar()`, antes de calcular `Sugerencia`
y de llamar `generar_polizas()`. Razones:

- El invariante que protegemos es "folio ascendente por fecha", y el folio
  se asigna en export. Poner el sort junto a la asignación hace el
  invariante inmune a cualquier caller o reordenamiento futuro upstream.
- Ordenar el `df` completo también deja la hoja "Datos" del Excel en orden
  cronológico — la vista de revisión y el TXT cuentan la misma historia.
- Ordenar en `load_folder()` mezclaría responsabilidades (ese módulo solo
  lee y parsea) y dejaría el invariante a merced de cualquier filtro
  intermedio.

### Especificación del sort (descripción, no código)

Sobre el `df` recibido en `exportar()`:

- Ordenar por columna `fecha` ascendente (string ISO, orden lexicográfico
  correcto), con `uuid` como segunda llave de desempate.
- Algoritmo estable (mergesort) para que empates residuales conserven un
  orden determinista.
- Fechas faltantes/nulas al final (`na_position="last"`) — no deben
  reventar el export ni colarse al folio 1.
- Resetear el índice del DataFrame después de ordenar para que la
  iteración y cualquier `iloc` posterior sean coherentes.

`generar_polizas()` NO cambia: sigue iterando el df en orden y asignando
`num` incremental. El orden correcto le llega ya resuelto.

### Invariantes que la implementación debe verificar (no asumir)

1. **Folios consecutivos 1..N sin huecos**: confirmar que en el código
   actual `num` solo avanza cuando el documento SÍ produce renglones de
   póliza (nómina en modo `contpaqi`, documentos ignorados, etc. no deben
   consumir folio). Si hoy ya es así, preservarlo; si no, es bug aparte —
   reportarlo a Svei antes de tocarlo.
2. **Renglones múltiples por póliza**: cada documento genera varios
   renglones Debe/Haber con el mismo `num`. El sort es por documento
   (filas del df de entrada), nunca por renglón generado, así que el
   agrupamiento no se toca.
3. **`validar_balance_polizas()`**: agrupa por `Numero` y no depende del
   orden — debe arrojar exactamente los mismos resultados antes y después
   del fix con los mismos XMLs.
4. **DIOT**: se agrega por proveedor, independiente del orden. No debe
   cambiar ni un centavo.

## 4. Observación fuera de alcance (no implementar sin aprobar con Svei)

`main.py` (líneas ~41-43) detecta empresa y periodo desde `rows[0]` — es
decir, del primer archivo en orden de sistema de archivos. Es la misma
no-determinismo de origen: si la carpeta trae un XML colado de otro mes,
el periodo del nombre de archivo depende de qué archivo listó primero el
OS. Este fix NO lo corrige (el sort vive en export). Posible mejora
futura: derivar el periodo del `min(fecha)` o del mes modal. Anotarlo,
no hacerlo.

## 5. Checklist de validación (correr con Svei antes de dar por bueno)

1. Carpeta de prueba donde el orden alfabético de archivos ≠ orden
   cronológico (renombrar XMLs a propósito). Exportar y confirmar:
   folio 1 = fecha más antigua, folios estrictamente ascendentes por
   fecha+hora.
2. Correr los mismos XMLs antes y después del fix:
   `validar_balance_polizas()` debe reportar cero descuadres nuevos y las
   mismas cuentas pendientes.
3. Mes real con REPs: confirmar que cada REP sale con folio mayor que su
   factura PPD (caso normal).
4. Confirmar folios 1..N sin huecos aun con nóminas brincadas
   (modo `contpaqi`) y documentos cancelados en la carpeta.
5. Hoja "Datos" del Excel en el mismo orden cronológico que las pólizas.
6. Importar el TXT en una empresa de prueba de CONTPAQi: verificar
   visualmente que folio y fecha corren en el mismo sentido.

## 6. Estilo de código (obligatorio en la implementación)

- Funciones pequeñas de propósito único.
- Comentarios explicativos estilo "profesor de salón de clases" — el
  código debe poder debuggearse en una sesión fresca de IA sin contexto
  previo.
- Nombres en lenguaje natural, descriptivos.
- Prohibidos los patrones ingeniosos-pero-crípticos.
- Archivos chicos, arquitectura modular, separación de responsabilidades.
- Carpetas: lowercase kebab-case. Python: snake_case. Sin espacios,
  acentos ni caracteres especiales en nombres de archivo.

## 7. Git

- Rama: `fix/orden-folios-por-fecha`.
- Probar localmente con un mes real de Svei (checklist sección 5) antes
  de mergear a main.
- El commit lo hace Svei; sugerir mensaje sin comillas dobles y sin
  footer de Claude.
