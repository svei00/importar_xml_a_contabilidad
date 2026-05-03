# Instrucciones de uso

Guía paso a paso para operar la app y, sobre todo, **cómo importar y afectar las
pólizas en ContpaqI Contabilidad 18.5.2**. (El `README.md` es la descripción general;
este archivo es el "cómo se usa" del día a día.)

---

## 0. Antes de empezar (una sola vez)

1. **Configuración** (botón ⚙️): define la **carpeta de salida** y el **catálogo de
   cuentas** (`cuentas.txt` exportado de ContpaqI). La etiqueta te muestra la fecha de
   última actualización del catálogo: si tiene meses, vuelve a exportarlo.
2. **Crea en ContpaqI las subcuentas de clientes** que vayas a usar (cuentas afectables,
   no de mayor):
   - `10501001`, `10501002` … para tus clientes grandes
   - `10501999` "Clientes varios" para público general (XAXX) y los no mapeados
   - `10502000` clientes extranjeros (XEXX)
3. Revisa que `settings.json` apunte a cuentas **afectables** (de detalle), no de mayor.

---

## 1. Procesar facturas

- **📥 RECIBIDAS (Compras + DIOT):** elige la carpeta con los XML de gasto del mes.
  Genera pólizas de compra, pagos (REP) y el **TXT de DIOT**.
- **📤 EMITIDAS (Ventas):** elige la carpeta con tus XML de venta. Genera pólizas de
  ingreso/cobro. (Las emitidas **no** llevan DIOT.)

La carpeta puede tener XML sueltos **o** ZIPs (la app abre los ZIP y lee los XML dentro).

Al terminar aparece un aviso **"Proceso completo"** y te pregunta si abrir la carpeta de
salida. Revisa el **Log** (panel derecho): ahí se reportan descuadres y cuentas pendientes.

---

## 2. Revisar el Excel antes de importar

Se genera `Polizas_<TIPO>_<RFC>_<AAAA>_<MM>.xlsx` con las hojas:

- **RESUMEN** — conteos del lote.
- **BASE** — los datos crudos de cada CFDI.
- **POLIZAS_CONTPAQI** — el asiento Debe/Haber que se va a importar. **Revisa aquí.**
- **DIOT_LISTA** (solo recibidas) — la DIOT agregada por RFC.

Si una cuenta quedó mal, **corrígela en la hoja POLIZAS_CONTPAQI** y guarda el Excel.

> El Log avisa si alguna póliza **no cuadra** (Debe ≠ Haber) o si hay cuentas
> **PENDIENTE / sin asignar**. No importes con descuadres.

---

## 3. Administrar Clientes y Proveedores (botón 👥)

- Filtra por **Clientes** / **Proveedores** / Todos.
- **Alias:** el apodo corto para la Referencia (`RFC-ALIAS`), p.ej. CFE → LUZ.
- **Cuenta (solo clientes):** asigna a cada cliente grande su cuenta (`10501001`…). Es un
  mapa fijo RFC→cuenta; quien no tenga cuenta cae en `10501999`.

Los terceros se van llenando solos conforme procesas facturas.

---

## 4. Aprender de Excel Corregido (botón 🧠)

Si corregiste cuentas de **gasto** en el Excel, vuelve a cargarlo aquí: la IA memoriza
tus correcciones **y regenera el TXT** con los cambios. (Aplica a gastos/recibidas; las
cuentas de cliente NO usan IA, son el mapa del paso 3.)

---

## 5. Validar el TXT (recomendado)

```
python validar_layout.py "ruta\Polizas_CONTPAQi_....txt"
```

Confirma que las columnas de ancho fijo están alineadas y que cada póliza cuadra.

---

## 6. Importar en ContpaqI  (Pólizas → Cargar Pólizas / **F5**)

1. Abre **Pólizas → Cargar Pólizas** (o **F5**) y selecciona el TXT
   (`Polizas_CONTPAQi_*.txt`).
2. **"Si el dato de entrada ya existe":** elige **Renumerar el dato de entrada**
   (así no pisa pólizas existentes; renumera las que entran).
3. **Diario en Efectivo (F3):** déjalo **en blanco** (el tipo Ingreso/Egreso/Diario ya
   viene definido en cada póliza).
4. Carga **Sin Afectar** — entra sin tocar saldos, para que puedas revisar primero.

---

## 7. Revisar y AFECTAR en ContpaqI

1. Ve al **Listado de Pólizas** y revísalas (fecha, tipo, concepto, cargos = abonos).
   Las que entraron "Sin Afectar" aparecen con ese estatus, sin mover saldos todavía.
2. Cuando estén correctas, **aféctalas** para integrarlas a la contabilidad:
   **Procesos → Afectar pólizas** (equivale a quitar el estatus *Sin afectar* /
   recalcular). A partir de ahí los saldos ya reflejan las pólizas.

> El nombre exacto del menú para afectar puede variar un poco según la versión de
> ContpaqI; la lógica es siempre: **cargar sin afectar → revisar → afectar**.

---

## 8. DIOT

El TXT de DIOT (54 columnas, formato batch del SAT) se genera con las **recibidas**.
Recomendación: úsalo como respaldo y cruza contra la DIOT que arma ContpaqI (configurando
tipo de tercero y operación por proveedor) como fuente principal.

---

## Resumen del ciclo mensual

```
Procesar XML  →  Revisar Excel (corregir cuentas)  →  Aprender (si corregiste)
            →  Validar TXT  →  Cargar en ContpaqI (Renumerar, Sin Afectar)
            →  Revisar Listado de Pólizas  →  Afectar
```
