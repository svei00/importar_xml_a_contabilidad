# ROADMAP / Estado del proyecto

Estado interno de desarrollo de **importar_xml_a_contabilidad** (XML CFDI 4.0 → pólizas
ContpaqI 18.5.2 + DIOT). El `README.md` es para el usuario final; este archivo es la
bitácora técnica: qué está hecho, qué falta y qué ideas están "madurando".

> Convención: ✅ hecho · 🚧 en progreso · ⏳ pendiente acordado · 💡 idea por madurar

---

## ✅ Hecho y probado

- **TXT ContpaqI de ancho fijo** — campo cuenta = 31 chars (el bug de truncado quedó
  arreglado; importe en col 67, bloque fiscal en col 99). Guardado por `validar_layout.py`.
- **Referencia `RFC-ALIAS`** + administrador de alias por empresa (GUI). Alias editable
  (CFE→LUZ, etc.). Clientes (emitidas) y proveedores (recibidas) caen en la misma tabla.
- **DIOT 2025** reescrita: una fila por RFC, base de FLUJO (PUE + REP; se omite PPD sin
  pagar), mapa de 54 columnas alineado al instructivo oficial SAT ene-2025:
  base 16% col 12, IVA acreditable 16% col 22 ("exclusiv. gravadas"), IVA acred.
  8% RFN col 18, exentos col 50, tasa 0% col 51, ret IVA col 48, y col 54
  Manifiesto = "01" (Sí). `diot.py`. (Antes caía el IVA acred. en la col 31
  "no objeto / RFN" y el SAT rechazaba la carga.)
- **Validador Debe=Haber** antes de escribir el TXT (`export.py::validar_balance_polizas`)
  + hoja `DIOT_LISTA` en el Excel de egresos.
- **Retención en compras** (honorarios/servicios): se acreditan ret ISR y ret IVA → las
  pólizas con retención ahora cuadran. Cuentas configurables en `settings.json`.
- **Nombres en Title Case** (el XML los trae en MAYÚSCULAS); RFC se queda en mayúsculas.
- **Concepto de pagos (REP)** sin el UUID feo (ahora "Complemento de Pago (REP)").
- **IEPS toggle** (`acredita_ieps`, default OFF = sin cambio). UI en Configuración.
- **Nómina toggle** (`nomina_modo`, default "contpaqi" = NO genera póliza de nómina porque
  CONTPAQi Nóminas ya la hace). "xml" la arma desde el CFDI (parser básico aún).
- **Configuración** (diálogo): carpeta de salida, catálogo COA + fecha de última
  modificación, toggles de IEPS y nómina.
- **Fin de proceso**: messagebox "Proceso completo" + pregunta si abrir carpeta (ya no se
  abre sola).
- **EMITIDAS (ventas)** — la cuenta principal va a Ventas (`ventas`=40101000), ya NO al
  clasificador de gastos. Probado con factura PPD real + su REP: ambas cuadran. (Bug A.)
- **Clientes por cuenta + Tipo (Phase E)** — el administrador ahora distingue Clientes
  (emitidas) y Proveedores (recibidas) con columna Tipo + filtro. Cada CLIENTE puede tener
  su cuenta (mapa determinista RFC->cuenta, NO ML); fallback nacional/público a
  `clientes`=10501999, extranjero a `clientes_extranjero`=10502000. Migración de BD no
  destructiva (ALTER ADD COLUMN tipo/cuenta) + backfill del tipo desde `facturas`. Probado.

## ⏳ Pendiente acordado (próximos pasos)

- **Retención en VENTAS** (cuando al cliente lo retienen): falta asentar "impuestos
  retenidos a favor / por cobrar" (ISR e IVA). El validador marcará el descuadre mientras
  tanto. Necesito los números de cuenta del COA.
- **Confirmar cuentas default de emitidas** contra el COA: clientes 10501001, IVA pdte
  cobro 20901000, IVA trasladado 20801000.
- **Reglas RFC→cuenta para cargas patronales** (SEPAF Jalisco / IMSS / INFONAVIT): llegan
  como CFDI recibido sin IVA; ya se asientan por el flujo normal, pero caen en
  gastos_generales. Mapear sus RFC a su cuenta de gasto. (Falta un XML de muestra.)
- **dashboard.py** roto: llama `get_conn()` sin RFC (API multi-empresa actual lo requiere).
- **Capturar EXENTO / 0% de PROVEEDORES** en el parser (hoy `iva_exento` siempre 0) → para
  reportar en la DIOT col 18 (exento) / 19 (0%) / 22 (no objeto) los proveedores EXENTOS
  legítimos (renta exenta, servicios médicos exentos). Necesita un XML de ejemplo de un
  proveedor exento. (Distinto de las contribuciones de gobierno, que NO van a la DIOT.)
  HECHO ya: las filas DIOT sin IVA/base/retención se OMITEN y se reportan en el Log
  (excluye correctamente derechos/ISN/IMSS/INFONAVIT; fundamento LIVA 32 / RLIVA 59).
- **Crear subcuentas de clientes en ContpaqI** (tarea del usuario): 10501001/002 (clientes
  grandes), 10501003/004 (distribuidora), 10501999 (varios/público). Hoy 10501000 es la
  afectable; al abrir hijas se vuelve mayor.
- **Ventana editora de settings.json** (PROMETIDA al usuario): UI para editar todas las
  cuentas configurables (bancos, IVA, retenciones, ventas, clientes, etc.) sin tocar el
  JSON a mano. Hoy solo el diálogo Configuración cubre carpeta/catálogo/IEPS/nómina.
- **README.md desactualizado**: predata todo el trabajo reciente (dice "ñ→NI", "Administrar
  Alias de Terceros", IEPS sin separar, DIOT doble como pendiente, roadmap viejo). Refrescar.
  La guía de uso del día a día ya vive en `INSTRUCCIONES.md` (incl. importar/afectar en ContpaqI).
- **Nota de Crédito (tipo E) vs IVA pagado**: el asiento de NC reversa las cuentas de IVA
  PENDIENTE (`iva_pdte_pago`/`iva_pdte_cobro`), correcto SOLO si el comprobante original era
  PPD aún sin pagar. Si la NC es contra una PUE (IVA ya acreditable/trasladado) o una PPD ya
  pagada por REP (IVA ya reclasificado), se reversa la cuenta equivocada y queda un fantasma
  en pendientes. Revisar el patrón real de NCs del cliente y, si llegan después del pago,
  rutear la pierna de IVA a la cuenta acreditable/trasladado. (export.py ~131-141.)

## 💡 Ideas por madurar (sin compromiso)

- **Nómina desde XML (1.2)**: el parser aún NO lee el complemento (Percepciones/
  Deducciones/OtrosPagos); el modo "xml" usa subtotal/total/ISR crudo. Solo vale la pena
  si llega un cliente que NO use CONTPAQi Nóminas. Tengo 1 XML de nómina timbrado del
  usuario para cuando se ataque.
- **Módulo de cantidades mensuales de nómina**: alternativa al parseo, para clientes con
  sistemas de nómina de terceros (Aspel, Excel) cuyos XML vienen incompletos. Decidir
  parse-XML vs. captura manual según la calidad real de los datos de ese cliente.
- **Modo "póliza concentradora"** (opcional, sobre todo para comercializar): generar UNA
  póliza que agrupe varias facturas (p.ej. por día/tipo/cuenta) en vez de una por CFDI.
  HOY el default (una póliza por UUID) es el mejor: máxima trazabilidad póliza↔UUID↔XML, y
  200-400/mes no es problema para ContpaqI. El argumento de "menos pólizas" es herencia de
  la captura manual; un generador lo elimina. INCÓGNITA TÉCNICA a probar ANTES de
  construirlo: si ContpaqI importa bien VARIAS líneas `AD <UUID>` dentro de un mismo bloque
  `P` (hoy cada M1 lleva su AD); de eso depende que el modo sea viable y que la contabilidad
  electrónica reciba los UUID. Excepción legítima donde concentrar SÍ es normal: ventas a
  público general (factura global) como una póliza de ingreso diaria/mensual.
- **Pestaña Clientes/Proveedores** en el administrador de alias (requiere etiquetar el rol
  del RFC en la tabla; hoy la lista única ya funciona).
- **IEPS por empresa** (hoy el flag es global en settings.json) y manejo de IEPS en
  PPD/REP (hoy solo PUE).

## 💡 Módulo grande a futuro: Conciliación bancaria (PDF de bancos)

Idea del usuario: leer estados de cuenta (Bancomer, Banamex) en PDF y automatizar.
**Reencuadre clave:** el objetivo correcto NO es "PDF → póliza" (la línea del banco no
dice la contracuenta: ¿depósito = cobro de cliente?, ¿préstamo?, ¿traspaso propio?). Las
pólizas ya las generan los CFDI. El valor real del estado de cuenta es la **CONCILIACIÓN**:
cruzar los movimientos del banco contra las pólizas ya registradas y **detectar lo que falta**
(comisiones, intereses, IVA de comisiones, pagos sin CFDI).

Partes y dificultad (de menor a mayor):
1. PDF con texto (Bancomer) → `pdfplumber`/`camelot` (tablas posicionales). Un parser POR
   banco; se rompen cuando el banco rediseña el formato (mantenimiento continuo).
2. PDF con contraseña (Banamex) → `pikepdf` para descifrar con la clave. Resoluble.
3. PDF como IMAGEN (sin capa de texto) → OCR. Tesseract local se equivoca en columnas de
   dinero; Document AI en la nube es mucho mejor PERO manda estados de cuenta del cliente a
   un tercero (problema de confidencialidad). Tradeoff real, decisión del usuario.
4. NO usar markitdown/office2md aquí (aplana el layout tabular). Usar pdfplumber/camelot.

Secuencia recomendada cuando se ataque:
- (a) PDF→Excel de movimientos (Bancomer primero; pikepdf para Banamex).
- (b) CONCILIAR movimientos vs pólizas del mes (match por importe/fecha/referencia) → marcar
  los no conciliados.
- (c) Auto-asentar SOLO lo determinista (comisión→gasto financiero+IVA, interés ganado); lo
  demás se concilia contra póliza existente, no se recrea.
- (d) Imagen/OCR al final, con revisión humana SIEMPRE.

Regla de oro: la herramienta ASISTE la conciliación; nunca asienta a ciegas desde el PDF.
Tamaño estimado: comparable al resto de la app junta. **No ahora** (primero usar la app
varios meses con datos reales).

## Notas de arquitectura

- Modelo ML y BD son **por empresa**: `empresas/<RFC>/conta_ml.db` y `.../modelo.pkl`.
- Lee carpetas con `.xml` sueltos **y** `.zip` (extrae cada XML interno) — `load_folder`.
- Tipos de póliza: Ingreso=efectivo entra (TXT 1), Egreso=efectivo sale (2),
  Diario=sin movimiento de efectivo (3): PPD provisión, reclasificación, NC, nómina.
