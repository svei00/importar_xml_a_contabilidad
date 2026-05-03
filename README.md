# SAT → ContpaqI Automator AI

Aplicación de escritorio (Python + Tkinter) que **lee los XML (CFDI 4.0) del SAT**, los
**valida**, **clasifica la cuenta de gasto con Machine Learning** y genera las **pólizas**
y la **DIOT** listas para importar a **ContpaqI Contabilidad 18.5.2**.

El flujo está pensado para mejora continua: cada vez que corriges una cuenta de gasto en el
Excel, la IA aprende y el siguiente mes clasifica mejor.

> **¿Cómo se usa en el día a día (incluido importar y AFECTAR en ContpaqI)?**
> Ver **[`INSTRUCCIONES.md`](INSTRUCCIONES.md)**.
> **Estado de desarrollo / pendientes / ideas:** ver **[`ROADMAP.md`](ROADMAP.md)**.

---

## ¿Qué hace, paso a paso?

1. **Analiza XML.** Recorre una carpeta (XML sueltos o ZIPs) y extrae de cada CFDI: tipo,
   fecha, RFC/nombre de emisor y receptor, subtotal, IVA 16/8, IEPS, retenciones, UUID,
   método de pago (PUE/PPD), código postal, serie/folio y los documentos relacionados de
   los REP. Los XML que no se puedan leer se **reportan en el Log** (no se pierden en silencio).
2. **Valida contra el SAT.** Consulta el estatus de cada UUID (Vigente / Cancelado) y lo marca.
3. **Clasifica con ML (solo gastos).** Un modelo NLP por empresa (TF‑IDF del concepto +
   proveedor, OneHot del CP, LogisticRegression) predice la cuenta de **gasto** en recibidas.
   Las **ventas** van a la cuenta de Ventas y los **clientes** a su cuenta por mapa fijo
   (ver abajo): eso **no** usa ML.
4. **Genera asientos.** Árbol Debe/Haber con NIF: provisión PPD, pago directo PUE, REP,
   notas de crédito (E) y nómina (N). **Acredita las retenciones** (ISR/IVA) en compras.
5. **Valida el cuadre.** Antes de escribir el TXT revisa **Debe = Haber** por póliza y
   avisa de cuentas **PENDIENTE / sin asignar** en el Log.
6. **Exporta los entregables:**
   - **Excel** (`Polizas_<TIPO>_<RFC>_<AAAA>_<MM>.xlsx`) con hojas `RESUMEN`, `BASE`,
     `POLIZAS_CONTPAQI` y (en recibidas) `DIOT_LISTA` — para que **tú revises**.
   - **TXT de pólizas** (`Polizas_CONTPAQi_*.txt`) de ancho fijo, listo para ContpaqI.
   - **TXT de DIOT** (formato batch del SAT, 54 columnas `|`).
7. **Reentrena desde el Excel.** Si corriges cuentas de gasto y vuelves a cargar el Excel
   (*Aprender de Excel Corregido*), la IA memoriza y **regenera el TXT**.

Al terminar, un aviso **"Proceso completo"** te pregunta si abrir la carpeta de salida.

---

## La Referencia de las pólizas: `RFC-ALIAS`

La Referencia es la **clave consistente** para filtrar el reporte de **Auxiliares**. Formato:
`RFC-ALIAS`, p.ej. `CFE370814QI0-LUZ`, `TME840315KT6-TELMEX`.

- El **RFC** va completo (12 = persona moral, 13 = persona física) y en MAYÚSCULAS.
- El **alias** es corto, **sin espacios** (rompen el ancho fijo), sin acentos. Regla de la ñ:
  **solo `AÑO → ANIO`** (para no escribir `ANO`); las demás ñ se vuelven N normal
  (`Muñoz → MUNOZ`). Por defecto se deriva de la primera palabra del nombre del XML.
- Los **nombres** del XML (que vienen en MAYÚSCULAS) se muestran en *Title Case* en los
  conceptos (`Teléfonos de México`), pero el RFC se queda en mayúsculas.
- En **Administrar Clientes y Proveedores** sobreescribes el alias (CFE → LUZ, etc.). Se
  guarda en SQLite por empresa y se rellena solo conforme procesas facturas.

---

## Cuentas: proveedores vs clientes (criterio opuesto a propósito)

- **Proveedores (recibidas):** **una sola** cuenta `20101999` para todos; el detalle por
  proveedor sale de la Referencia en Auxiliares. (Son cientos; no se abre cuenta por cada uno.)
- **Clientes (emitidas):** cuenta **por cliente** (mapa determinista RFC→cuenta que asignas
  en el administrador). Son pocos clientes grandes y conviene verlos separados. Quien no
  tenga cuenta asignada cae en `10501999` (Clientes varios / público); los extranjeros en
  `10502000`. **Esto no usa ML**: es un mapa fijo (un cliente siempre va a su misma cuenta).

---

## Tipos de póliza (campo "Tipo" en ContpaqI)

| Naturaleza del movimiento | Tipo en la app | Código en el TXT |
|---|---|---|
| Entra dinero (cobro, depósito, aportación) | **Ingreso** | `1` |
| Sale dinero (pago a proveedor, gasto pagado) | **Egreso** | `2` |
| No mueve efectivo (provisión PPD, reclasificación, nota de crédito, nómina) | **Diario** | `3` |

---

## ⚠️ El TXT de ContpaqI es de ANCHO FIJO

ContpaqI lee cada dato en una **columna exacta**. Si un campo se corre 1 carácter, se "come"
el primer dígito de los importes (`3915.00 → 915.00`), la póliza queda **descuadrada** y
termina en la **cuenta de cuadre** (`_CU-AD-RE0`) o **rechazada**.

Mapa medido contra una exportación real: el campo **cuenta ocupa 31 caracteres**, el
**importe empieza en la columna 67** y el bloque fiscal `0.0` en la **columna 99**.

Valida el archivo antes de importar:

```
python validar_layout.py "ruta\Polizas_CONTPAQi_....txt"
```

---

## Estructura del proyecto

| Archivo | Rol |
|---|---|
| `main.py` | Orquestador + interfaz Tkinter (Emitidas/Recibidas, Clientes y Proveedores, Configuración, Aprender). |
| `xml_processor.py` | Parser de CFDI 4.0 (REP/Pago, retenciones, IEPS, serie/folio); lee XML y ZIP y **reporta fallos**. |
| `sat_validator.py` | Estatus de cancelación de cada UUID en el SAT. |
| `ml_model.py` | Pipeline ML **por empresa** (TF‑IDF + OneHot + LogisticRegression) para la cuenta de gasto. |
| `db.py` | SQLite por empresa (`empresas/<RFC>/conta_ml.db`): facturas, etiquetas, historial DIOT, y **alias/cuenta de terceros** (tipo Cliente/Proveedor). |
| `export.py` | Árbol Debe/Haber, Excel, TXT de pólizas, validación de cuadre y aliases. |
| `terceros.py` | Normalización de alias, Title Case y construcción de la Referencia `RFC-ALIAS`. |
| `diot.py` | DIOT: agrega **una fila por RFC** (flujo PUE+REP) y escribe el TXT batch de 54 columnas. |
| `validar_layout.py` | Verificador del TXT: columnas de ancho fijo y cuadre. |
| `config.py` | `settings.json`, carga del catálogo (`cuentas.txt`) y validación de cuenta vs catálogo. |
| `dashboard.py` | Visor opcional Dash/Plotly (independiente; ver ROADMAP). |

---

## Instalación y uso

**Requisito:** Python 3 en el PATH.

- **Windows:** doble clic en `run.bat`.  **Mac/Linux:** `./run.sh`.
- Dependencias: `pandas`, `scikit-learn`, `requests`, `openpyxl` (y `dash`, `plotly` solo
  para el dashboard).

### Flujo típico (resumen — detalle en `INSTRUCCIONES.md`)
1. **Configuración** (⚙️): carpeta de salida y catálogo de cuentas (muestra su fecha).
2. **RECIBIDAS** (compras + DIOT) o **EMITIDAS** (ventas) → elige la carpeta de XML.
3. **Administrar Clientes y Proveedores**: alias y, para clientes, su cuenta.
4. Revisa el Excel; corrige cuentas de gasto si hace falta.
5. **Aprender de Excel Corregido** → la IA memoriza y regenera el TXT.
6. `python validar_layout.py <txt>` y luego importa en ContpaqI.

> **Importar en ContpaqI** (Pólizas → Cargar Pólizas / F5): "si ya existe" → **Renumerar**,
> *Diario en Efectivo* → en blanco, **Cargar Sin Afectar**, revisar, y luego **Afectar**.
> Pasos completos en [`INSTRUCCIONES.md`](INSTRUCCIONES.md).

---

## Configuración (`settings.json`)

```json
{
  "catalogo_path": "C:\\...\\cuentas.txt",
  "output_path": "C:\\...\\salida",
  "acredita_ieps": false,
  "nomina_modo": "contpaqi",
  "cuentas_default": {
    "bancos": "10201001",
    "iva_acreditable": "11801000",
    "gastos_generales": "60000000",
    "ventas": "40101000",
    "clientes": "10501999",
    "clientes_extranjero": "10502000",
    "ieps_acreditable": "",
    "ret_isr_honorarios": "21604000",
    "ret_iva": "21610000",
    "ret_isr_nomina": "21601000"
  }
}
```

El **catálogo** se exporta de ContpaqI (`cuentas.txt`). **Usa siempre cuentas afectables
(de detalle), no de mayor** — p.ej. `10201001` (BBVA), no `10201000`.

**Toggles** (en el diálogo Configuración):
- **`acredita_ieps`** (default *off*): si la empresa **es sujeta a IEPS**, sepáralo a su
  cuenta (`ieps_acreditable`). Si no, déjalo apagado (el IEPS queda en el costo).
- **`nomina_modo`** (default `contpaqi`): con CONTPAQi Nóminas la app **no** genera póliza
  de nómina (la hace ese módulo). Ponlo en `xml` solo si quieres armarla desde el CFDI.

---

## Nota sobre la DIOT

`diot.py` agrega **una fila por RFC** sobre base de **flujo** (facturas PUE pagadas + los
REP recibidos; las PPD sin pagar no entran), con el mapa correcto de 54 columnas. Úsalo como
respaldo y cruza contra la DIOT de ContpaqI (configurando tipo de tercero/operación por
proveedor) como fuente principal.
