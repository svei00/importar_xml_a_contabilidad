# Handoff — Reglas contables faltantes (casos A–I) + estados de cuenta

**Proyecto:** `importar_xml_a_contabilidad` (app de escritorio Python + Tkinter, arranque `run.bat`).
**Fecha de la sesión de arquitectura:** 2026-10-08. **Autor de la arquitectura:** Opus 5.5.
**Implementa:** Sonnet 5.5 (fases 1–6 de la Parte 1). Opus 5.5 vuelve para el diseño fino de
la Parte 2 (estados de cuenta) cuando haya un estado de cuenta real en la mesa.

> Este documento es autosuficiente: quien lo siga NO necesita el transcript de la sesión.
> Todas las decisiones de arquitectura ya están tomadas aquí. No las reabras; si algo
> del repo contradice este documento, DETENTE y pregunta a Svei.

**Fuera de alcance — otros proyectos que NO comparten código con éste:** `cfdi-app`
(PySide6), `papeles-trabajo`, la herramienta de descarga SAT/IMSS/INFONAVIT, los blogs.

---

## 0. Cómo usar este documento

1. Lee las secciones 1 (hallazgos), 2 (respuestas de Svei) y 3 (arquitectura).
2. Implementa UNA fase por rama, en el orden de la sección 6. Cada fase deja la app
   funcionando (shippable); puedes detenerte al final de cualquiera.
3. Cada fase tiene un criterio de salida verificable contra los XML reales de agosto 2026
   en `C:\AdminXML\BovedaCFDI\EEA251205CR8\Recibidas\2026\08` y `...\Emitidas\2026\08`.
4. Respeta las reglas de estilo de la sección 9 (obligatorias).

---

## 1. Hallazgos de la Fase 0 (código real, verificado)

### 1.1 Flujo XML → póliza hoy

```
main.py  select_folder_and_run(tipo)                 (UI Tkinter)
  └─ process_folder(folder, tipo)            main.py:28-144
       ├─ xml_processor.load_folder()        → lista de dicts (uno por CFDI)
       ├─ periodo = mes/año del PRIMER XML   main.py:41-43        ← BUG (ver 1.3)
       ├─ por cada fila:
       │    ├─ N  → cuenta 60010000          main.py:62-66
       │    ├─ sat_validator.validar()       main.py:70-75 (solo AVISA si cancelado)
       │    ├─ ingresos → cuenta ventas      main.py:79-84
       │    ├─ egresos  → ml_model.predict() main.py:86  (o gastos_generales)
       │    ├─ P (REP)  → cuenta = bancos    main.py:91-93        ← casos A, B
       │    └─ db.upsert_factura()           main.py:95-101
       ├─ egresos: diot.generar_diot + exportar_txt_sat
       └─ export.exportar(df, ...)           export.py:433-489
            ├─ ordenar_por_fecha (por fecha de EMISIÓN)          ← caso C
            ├─ generar_polizas()             export.py:7-174  (aquí se decide TODO lo demás)
            ├─ validar_balance_polizas()     export.py:393-407
            ├─ Excel: RESUMEN, BASE, POLIZAS_CONTPAQI, DIOT_LISTA
            └─ exportar_txt_contpaqi()       export.py:201-260 (cp1252, errors="replace") ← caso H
```

### 1.2 Puntos de decisión (dónde se decide cada cosa hoy)

| Decisión | Dónde | Cómo lo decide hoy | Caso |
|---|---|---|---|
| Cuenta de gasto | `main.py:86` | Modelo ML (`ml_model.predict`) entrenado con el Excel corregido; fallback `gastos_generales` | E, F |
| Cuenta de proveedor (PPD y REP) | `export.py:19` | SIEMPRE `proveedores` = 20101999, sin importar el RFC ni el documento pagado | A |
| Contrapartida de un pago | `export.py:118`, `:146`, `main.py:92` | SIEMPRE `bancos` | B, G |
| Tipo de póliza | `export.py:101-155` | Por tipo CFDI + método (PUE→Egreso, PPD→Diario, P→Egreso) | B |
| Fecha de póliza | `export.py:87` | `Fecha` de emisión del CFDI | C |
| ¿Ya se importó antes? | — | No existe. `facturas` se sobreescribe (`INSERT OR REPLACE`) en cada corrida | D |
| Validación vs catálogo | `config.py:32-68` | **No funciona** (ver 1.3) | E |
| ¿Hay saldo en el pasivo? | — | No existe | F |
| Codificación del TXT | `export.py:206` | cp1252 con `errors="replace"` (lo no representable se vuelve `?` en silencio) | H |
| ¿Hay algo que generar? | `main.py:32-34` | Solo aborta si NO hay XML; si hay XML pero 0 pólizas, escribe TXT y Excel vacíos | I |

### 1.3 Bugs encontrados de paso (entran al plan)

1. **Validación de catálogo rota.** `config.cargar_catalogo` lee `cuentas.txt` como CSV
   separado por tabuladores, pero el export de CONTPAQi es de **ancho fijo**. Resultado:
   `validar_cuenta_vs_sat` siempre responde "Cuenta no en catálogo". → Fase 4.
2. **Cancelados no se excluyen.** La decisión B-11 de `AUDITORIA_Y_ROADMAP.md` §7-Q2
   (excluir de pólizas y DIOT con conteo visible) NUNCA se implementó: `main.py:73-75`
   solo imprime la alerta. → Fase 1.
3. **Periodo tomado del primer XML.** `main.py:41-43`. Si el primer archivo de la carpeta
   es una reexpedición de julio, el lote completo (y su DIOT) se bautiza como julio. → Fase 1.
4. **Configuración global con dos empresas vivas.** Existe `empresas/GOOH841231EPA/` además
   de EEA. `settings.json` (catálogo, cuentas) es global → esa empresa hereda cuentas de EEA
   (bug B-12 de la auditoría, ya activo). Las llaves NUEVAS de este plan se guardan por
   empresa desde el día uno (sección 3.4). La migración completa de B-12 sigue en el
   roadmap de la auditoría.
5. **Pólizas con cuenta PENDIENTE se escriben descuadradas al TXT.** `exportar_txt_contpaqi`
   salta las líneas con cuenta `PENDIENTE` (export.py:226-227) pero escribe el resto de la
   póliza → CONTPAQi recibe una póliza descuadrada. → Fase 6.

### 1.4 Lo que la app hace BIEN (no romper)

- Layout de ancho fijo `P` / `M1` (cuenta 31 chars, importe en col 67) / `AD` + UUID.
  Protegido por `validar_layout.py`.
- PPD sin REP → IVA a 119-01-000 (pendiente de pago).
- REP → reclasificación 119-01 → 118-01 por el IVA del pago.
- Factura PPD de Telmex en Diario con IEPS dentro de la base (335.34 = 328.44 + 6.90).
- Orden de pólizas por fecha (`ordenar_por_fecha`) — en adelante debe ordenar por
  `fecha_poliza` (la nueva), no por la de emisión.
- DIOT 2025 con el mapa oficial SAT (commit 57e91d9).

### 1.5 Datos reales de agosto 2026 (EEA251205CR8)

**Recibidas/2026/08** (5 XML):

| UUID | Tipo | Emisión | Método/Forma | Serie-Folio | Total | Emisor | Pago (REP) |
|---|---|---|---|---|---|---|---|
| 4295eff7 | P | 02/08 | — | XZ 000124424354 | — | CFE370814QI0 | FechaPago 02/08, Forma 03, 3,907.00 → doc B4CB3AFC (XA 000209486272, julio, total 3,907.58) |
| fad179f3 | P | 05/08 | — | — | — | TME840315KT6 Telmex | FechaPago **03/08**, Forma **04**, 388.99 → doc 1207de06 (julio) |
| d66001ab | I | 14/08 | PPD/99 | FMM 070326080069312 | 388.99 | TME840315KT6 Telmex | — |
| e7e5db0a | I | 12/08 | PUE/03 | A + `202607-H6729812105-06082026-349460` | 2,108.78 | IMS421231I45 IMSS | — |
| fac86dcb | I | 07/08 | PUE/03 | (sin serie) PP347188 | 495.86 | INF7205011ZA INFONAVIT | — |

**Recibidas/2026/07** relevantes: B4CB3AFC (CFE PPD 3,907.58), 1207de06 (Telmex PPD 388.99),
**dos** INFONAVIT PP347188 495.86 (5f09f69b y 63f4f6e1, ambos 15/07), IMSS 419b85ea con folio
`202606-H6729812105-08072026-347188` (2,948.26), SPC130227L99 (Hacienda Jalisco, PUE forma 99).

> Observación: el folio INFONAVIT `PP347188` es la **línea SIPARE 347188**, la misma del CFDI
> del IMSS de julio. Útil para ligar la reexpedición. Svei: confirma que el CFDI de INFONAVIT
> no esté ya incluido dentro del total del CFDI del IMSS de esa misma línea (si lo está, julio
> tiene un doble registro).

**Emitidas/2026/08** (8 XML): **los 8 son nómina (tipo N)**. Con `nomina_modo = "contpaqi"`
no producen pólizas → hoy se escribe un TXT y un Excel vacíos. Es el caso I.

**Catálogo** (`cuentas.txt`, exportado el **20/06/2026**): NO contiene 20101002 (CFE) ni
20501002 (reembolsos socio), que Svei ya creó en CONTPAQi. **Hay que volver a exportarlo
antes de probar la Fase 4.** Contiene 60040001 "Telmex" con agrupador `601.50` (mal: su
espejo sería `600.40`), 60350000 `603.50`, 60326000 `603.26`, 21101000 `211.01`.

---

## 2. Respuestas de Svei (sección 5 del prompt original)

| # | Pregunta | Respuesta |
|---|---|---|
| 1 | ¿Dónde persiste la app lo importado? | (Verificado en repo) SQLite por empresa `empresas/<RFC>/conta_ml.db`. Tablas: `facturas` (uuid PK, sin serie/folio/cuenta/póliza; se sobreescribe en cada corrida), `etiquetas` (uuid→cuenta de gasto, solo del Excel corregido), `historial_diot`, `alias_terceros` (rfc, shortname, tipo C/P, cuenta — hoy la cuenta solo se usa para clientes). No hay registro de qué póliza/cuenta se generó. |
| 2 | ¿Acceso al SQL de CONTPAQi? | **Solo archivos exportados** (balanza de comprobación y `cuentas.txt`). Nada de SQL. |
| 3 | ¿Mapeo RFC → cuenta? | (Verificado) Gasto: lo asigna el modelo ML. Proveedor: fijo 20101999. Cliente: mapa determinista en `alias_terceros.cuenta`. |
| 4 | ¿Una o varias empresas? | (Verificado) Varias, cada una con BD y modelo propios; hoy EEA251205CR8 y GOOH841231EPA. Catálogo y cuentas aún globales (bug B-12). |
| 5 | ¿Pólizas sin CFDI? | **Por lo pronto fuera.** Pero Svei SÍ quiere una **Parte 2: estados de cuenta bancarios** dentro de esta app (ingesta, conciliación y, después, pólizas sin CFDI aprendidas con ML). Ver sección 5. |
| extra | ¿Cuenta para pagos con tarjeta del socio (forma 04/28)? | **205-01-002** (ya existe en CONTPAQi; falta re-exportar `cuentas.txt`). |
| extra | ¿Corrida sin pólizas? | **Avisar y NO generar** ni TXT ni Excel. |

---

## 3. Arquitectura

### 3.1 Principio rector: separar DECIDIR de ESCRIBIR

Hoy `export.generar_polizas` decide (cuenta, fecha, tipo, contrapartida) Y escribe asientos al
mismo tiempo. Eso hace imposible meter reglas nuevas sin volverla ilegible.

**Nueva regla de arquitectura:** antes de `generar_polizas` corre una etapa de **reglas
contables** que agrega a cada fila del DataFrame columnas de decisión ya resueltas.
`generar_polizas` solo LEE esas columnas y arma los asientos. Si una columna nueva no
existe (fase aún no implementada), `generar_polizas` usa su comportamiento actual →
cada fase es incremental y segura.

Columnas de decisión (todas en la hoja BASE del Excel para que Svei las revise):

| Columna | Significado | La llena |
|---|---|---|
| `periodo` | AAAA-MM del lote | Fase 1 |
| `omitir` / `motivo_omision` | La fila no genera póliza ni DIOT (cancelado, reexpedición, nómina en modo contpaqi) | Fases 1, 2 |
| `fecha_poliza` | Fecha que va en la póliza | Fase 3 |
| `tipo_poliza` | Egreso / Ingreso / Diario | Fase 3 |
| `cuenta_contrapartida` | Banco, 205-01-002, o PENDIENTE | Fase 3 |
| `cuenta_tercero` | Cuenta de proveedor/cliente donde vive (o se cancela) el saldo | Fase 2 |
| `aplicaciones_pago` | Para REP: lista de (IdDocumento, ImpPagado, cuenta_tercero) | Fases 2, 3 |
| `cuenta_principal` | Gasto/ingreso ya validado contra catálogo | Fase 4 |

### 3.2 Regla de dependencias

- Los módulos de reglas **NO importan Tkinter** ni muestran ventanas. Reciben datos,
  devuelven datos + excepciones. La UI (`main.py` y ventanas nuevas) es la única que
  muestra `messagebox`.
- Toda situación que la app no puede decidir sola se registra como **excepción**
  (sección 3.5). **Nada se resuelve en silencio.**

### 3.3 Módulos nuevos (archivos chicos, uno por responsabilidad)

Python no puede importar carpetas con guiones, así que los módulos `.py` quedan **planos en
la raíz** en `snake_case` (como el repo actual). Las carpetas que no son paquetes Python sí
van en kebab-case (p. ej. `tests/`).

| Archivo | Responsabilidad única | Fase |
|---|---|---|
| `config_empresa.py` | Leer/escribir la config de UNA empresa (`settings["empresas"][rfc]`) con respaldo a la global | 1 |
| `excepciones.py` | Clase `Excepcion` + colector de la corrida | 1 |
| `periodo_lote.py` | Determinar el periodo del lote y listar XML fuera de periodo | 1 |
| `resumen_corrida.py` | Decidir si la corrida produce algo y redactar el aviso de "mes vacío" | 1 |
| `texto_contpaqi.py` | Normalizar textos a ASCII para el TXT | 1 |
| `registro_contable.py` | Tablas `lotes`, `documentos_contabilizados`, `pagos_aplicados` y sus consultas | 2 |
| `llave_negocio.py` | Construir la llave RFC+Serie+Folio+Total normalizada | 2 |
| `detector_reexpediciones.py` | Caso D | 2 |
| `cuenta_de_tercero.py` | Caso A: dónde vive el saldo de un documento | 2 |
| `sembrar_historial.py` | Cargar meses anteriores al registro (lote `historico`) | 2 |
| `fecha_de_poliza.py` | Caso C (FechaPago del REP, fecha embebida en folio IMSS) | 3 |
| `formas_de_pago.py` | Caso B (contrapartida y tipo de póliza por forma de pago) | 3 |
| `catalogo_contpaqi.py` | Leer `cuentas.txt` de ancho fijo y validar cuentas (caso E) | 4 |
| `balanza_contpaqi.py` | Leer la balanza exportada (caso F) | 5 |
| `cuotas_patronales.py` | Decidir provisión vs. gasto directo (caso F) | 5 |
| `reglas_contables.py` | Orquestador: aplica, en orden, las reglas de las fases 1–5 al DataFrame | 1 (crece en cada fase) |
| `ventana_excepciones.py` | UI Tkinter de la lista de excepciones antes de escribir el TXT | 6 |

Archivos existentes que cambian: `xml_processor.py` (campos nuevos), `main.py`
(orquestación), `export.py` (`generar_polizas` lee columnas de decisión;
`exportar_txt_contpaqi` normaliza y excluye pólizas bloqueadas), `db.py` (columna
`cuenta_gasto` en `alias_terceros` para proveedores), `diot.py` (recibe solo filas no
omitidas; sin cambio de layout).

### 3.4 Configuración por empresa (llaves nuevas)

Todas las llaves NUEVAS de este plan viven en `settings["empresas"][<RFC>]`. Lectura:
`config_empresa.obtener_config_empresa(rfc)` = config global con la de la empresa encima
(lo de la empresa gana). Escritura: siempre en el bloque de la empresa. Migración NO
destructiva: si el bloque no existe, se crea vacío; no se copia nada de otra empresa.

Ejemplo para EEA251205CR8 (valores reales acordados):

```json
"empresas": {
  "EEA251205CR8": {
    "catalogo_espejo_agrupador": true,
    "cuentas_retiradas": ["60040001"],
    "conceptos_ascii": true,
    "balanza_path": "",
    "formas_pago": {
      "02": {"cuenta": "bancos",   "tipo_poliza": "Egreso"},
      "03": {"cuenta": "bancos",   "tipo_poliza": "Egreso"},
      "04": {"cuenta": "20501002", "tipo_poliza": "Diario"},
      "28": {"cuenta": "20501002", "tipo_poliza": "Diario"},
      "99": {"cuenta": "bancos",   "tipo_poliza": "Egreso", "advertir": true}
    },
    "cuotas_patronales": {
      "rfcs": ["IMS421231I45", "INF7205011ZA"],
      "cuenta_pasivo": "21101000",
      "cuenta_gasto": "60326000",
      "sin_balanza": "gasto_directo"
    }
  }
}
```

- `"cuenta": "bancos"` es un alias que resuelve a `cuentas_default.bancos`.
- Una forma de pago que NO está en el mapa → contrapartida `PENDIENTE` + excepción bloqueante.

### 3.5 Excepciones (nada en silencio)

`excepciones.py` define:

- `Excepcion(codigo, severidad, uuid, mensaje, sugerencia)` donde `severidad` es
  `"bloqueante"` (la póliza NO va al TXT) o `"informativa"` (va al TXT, pero se avisa).
- `ColectorDeExcepciones` con `agregar(...)`, `bloqueantes()`, `por_uuid(uuid)`, `todas()`.

Desde la Fase 1 cada excepción se imprime en el Log y se escribe en una hoja
**EXCEPCIONES** del Excel. En la Fase 6 se agrega la ventana previa al TXT.

Códigos (cada fase agrega los suyos):

| Código | Severidad | Fase |
|---|---|---|
| `CANCELADO` | informativa (la fila se omite) | 1 |
| `ESTATUS_SAT_DESCONOCIDO` | informativa | 1 |
| `FUERA_DE_PERIODO` | informativa | 1 |
| `REEXPEDICION` | informativa (la fila se omite) | 2 |
| `PAGO_DE_DOCUMENTO_NO_REGISTRADO` | informativa | 2 |
| `SALDO_INSOLUTO` | informativa | 3 |
| `FORMA_PAGO_SIN_MAPEO` | bloqueante | 3 |
| `FORMA_PAGO_ADVERTIDA` | informativa | 3 |
| `REP_CON_VARIOS_PAGOS` | bloqueante | 3 |
| `PAGO_DE_PERIODO_ANTERIOR` | informativa | 3 |
| `CUENTA_INVALIDA` | bloqueante | 4 |
| `PASIVO_SIN_SALDO` | informativa | 5 |
| `PASIVO_SALDO_PARCIAL` | bloqueante | 5 |

### 3.6 Esquema de persistencia (Fase 2) — DECIDIDO

Vive en la misma BD por empresa (`empresas/<RFC>/conta_ml.db`). Creación con
`CREATE TABLE IF NOT EXISTS` (no destructivo).

```sql
CREATE TABLE IF NOT EXISTS lotes (
    lote_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_operacion  TEXT NOT NULL,      -- 'ingresos' | 'egresos'
    periodo         TEXT NOT NULL,      -- 'AAAA-MM'
    carpeta_origen  TEXT,
    archivo_txt     TEXT,
    generado_en     TEXT NOT NULL,      -- ISO 8601
    estado          TEXT NOT NULL       -- 'vigente' | 'reemplazado' | 'historico' | 'sin_movimientos'
);

CREATE TABLE IF NOT EXISTS documentos_contabilizados (
    uuid                     TEXT NOT NULL,
    lote_id                  INTEGER NOT NULL,
    llave_negocio            TEXT,      -- 'RFC|SERIE|FOLIO|TOTAL' (ver regla D)
    tipo_cfdi                TEXT,      -- I, E, P, N
    metodo_pago              TEXT,
    forma_pago               TEXT,
    rfc_tercero              TEXT,
    serie                    TEXT,
    folio                    TEXT,
    total                    REAL,
    fecha_cfdi               TEXT,
    fecha_poliza             TEXT,
    tipo_poliza              TEXT,
    numero_poliza_en_lote    INTEGER,
    cuenta_principal         TEXT,      -- gasto / ingreso
    cuenta_tercero           TEXT,      -- proveedor / cliente donde vive el saldo
    cuenta_contrapartida     TEXT,      -- banco / 205-01-002 / ...
    resultado                TEXT NOT NULL,  -- 'contabilizado' | 'reexpedicion' | 'cancelado' | 'omitido_nomina' | 'bloqueado'
    documento_original_uuid  TEXT,      -- solo para reexpediciones
    PRIMARY KEY (uuid, lote_id)
);
CREATE INDEX IF NOT EXISTS ix_doc_llave ON documentos_contabilizados(llave_negocio);
CREATE INDEX IF NOT EXISTS ix_doc_uuid  ON documentos_contabilizados(uuid);

CREATE TABLE IF NOT EXISTS pagos_aplicados (
    uuid_pago          TEXT NOT NULL,   -- UUID del REP
    lote_id            INTEGER NOT NULL,
    id_documento       TEXT NOT NULL,   -- IdDocumento del DoctoRelacionado
    imp_pagado         REAL,
    imp_saldo_insoluto REAL,
    cuenta_cancelada   TEXT,            -- cuenta de proveedor/cliente que se canceló
    PRIMARY KEY (uuid_pago, lote_id, id_documento)
);
```

**Ciclo de vida del lote (idempotencia):**
- Cada corrida crea un lote nuevo. Al terminar con éxito, los lotes anteriores del mismo
  `(tipo_operacion, periodo)` pasan a `reemplazado`. → Correr agosto dos veces NO genera
  falsos duplicados contra sí mismo.
- **Lotes vigentes** = `vigente` + `historico` (+ `sin_movimientos`, sin documentos).
  Las búsquedas de los casos A y D solo miran lotes vigentes.
- No hay botón "confirmar importación": la app no puede saber si Svei importó a CONTPAQi;
  la última corrida del periodo es la verdad.

**Por qué tablas nuevas y no ampliar `facturas`:** `facturas` se escribe al PARSEAR
(`INSERT OR REPLACE` en cada corrida, incluidos cancelados) y alimenta al modelo ML.
Mezclar "visto" con "contabilizado" rompería la idempotencia y la detección de duplicados.
`documentos_contabilizados` registra el RESULTADO contable; `facturas` sigue igual.

**Cómo entra la historia que ya existe (julio y antes):**
1. `sembrar_historial.py` + botón "📚 Sembrar historial…" (HECHO en Fase 2): Svei elige una
   carpeta de XML de un mes ya contabilizado. Se crea un lote `historico` con SOLO qué
   comprobantes ya se contabilizaron (UUID, llave, fecha, total); **sin cuentas**.
   *Decisión tomada con datos reales:* el TXT de pólizas de julio NO coincide con los libros
   (mandó CFE a 20101999 y Telmex a 60040001, pero la balanza de julio muestra 201-01-002 y
   603-50-000: Svei corrigió a mano en CONTPAQi). Sembrar cuentas desde un TXT viejo
   metería datos falsos, así que la cuenta de tercero sale del alias.
2. (DESCARTADO) Que `learn_from_excel_ui` actualice el registro: innecesario con el alias.
3. Respaldo determinista (HECHO): `alias_terceros.cuenta` se habilita también para PROVEEDORES
   (hoy solo clientes) y se agrega la columna `cuenta_gasto`. Svei captura en la ventana de
   Clientes/Proveedores: CFE370814QI0 → cuenta 20101002; TME840315KT6 → cuenta_gasto 60350000.

---

## 4. Reglas contables — especificación verificable

Cada regla: **Disparador → Acción → Excepción → Prueba (agosto 2026)**.

### Regla A — El pago cancela la cuenta donde vive el documento
- **Disparador:** REP (tipo P) recibido o emitido.
- **Acción:** por cada `DoctoRelacionado` del pago, `cuenta_de_tercero.buscar(IdDocumento)`
  en este orden:
  1. La factura se registró en ESTA misma corrida (ya tiene cuenta).
  2. Registro: `documentos_contabilizados.cuenta_tercero` del `uuid = IdDocumento` en un
     lote vigente o histórico (si es NULL —documento sembrado— se pasa al siguiente).
  3. Mapa del tercero: `alias_terceros.cuenta` del RFC.
  4. Default (`proveedores` / `clientes`).
  El cargo (recibidas) o abono (emitidas) al tercero se divide por documento según
  `ImpPagado`, cada parte contra su cuenta. Se guarda en `pagos_aplicados`.
- **Excepción:** si se llegó al paso 4 Y el documento no está en el registro →
  `PAGO_DE_DOCUMENTO_NO_REGISTRADO` (informativa; un documento sembrado sin cuenta NO avisa):
  "El REP {uuid} paga {IdDocumento} que no está en el registro: se usó {cuenta}".
- **Factura PPD nueva:** su `cuenta_tercero` = paso 2 o 3 (para que su futuro REP la encuentre).
- **Prueba:** REP CFE 4295eff7 → cargo **201-01-002 3,907.00** (vía registro sembrado de julio
  o vía alias CFE).

### Regla B — Forma de pago que no es banco de la empresa
- **Disparador:** REP (`Pago@FormaDePagoP`) o factura PUE (`Comprobante@FormaPago`).
- **Acción:** `formas_de_pago.resolver(forma, config_empresa)` → `(cuenta_contrapartida,
  tipo_poliza)` según el mapa `formas_pago` (sección 3.4). Contrapartida ≠ banco →
  `tipo_poliza = "Diario"`.
- **Excepciones:** forma no mapeada → `FORMA_PAGO_SIN_MAPEO` (bloqueante, contrapartida
  PENDIENTE). Forma con `"advertir": true` → `FORMA_PAGO_ADVERTIDA`. Pago con tarjeta del socio
  mayor a $2,000 → nota en la misma excepción: "revisar requisitos de forma de pago de la
  deducción (LISR 27 fr. III)".
- **Prueba:** REP Telmex fad179f3 (forma 04) → **Diario**, abono **205-01-002 388.99**, cero
  movimientos a 102-01-001.

### Regla C — La fecha de la póliza es la del pago
- **REP:** `fecha_poliza = Pago@FechaPago` (nunca emisión ni timbrado). Si el REP trae más de
  un nodo `Pago` con distinta fecha o forma → `REP_CON_VARIOS_PAGOS` (bloqueante). Con un
  solo `Pago` (el caso normal) → una póliza.
- **IMSS** (emisor en `cuotas_patronales.rfcs` y folio con el patrón): se une
  `Serie + "-" + Folio` y se valida contra
  `^A-(?P<periodo>\d{6})-(?P<registro_patronal>[A-Z0-9]{11})-(?P<fecha_pago>\d{8})-(?P<linea_sipare>\d+)$`.
  `fecha_poliza` = `fecha_pago` (DDMMAAAA). El concepto agrega
  `"Cuotas IMSS {AAAA-MM} SIPARE {linea}"`. Si el patrón no coincide → fecha de emisión +
  excepción informativa.
- **Resto:** `fecha_poliza` = fecha de emisión (sin cambio).
- **Pago de periodo anterior:** si `fecha_poliza` cae en un mes anterior al `periodo` del
  lote → `PAGO_DE_PERIODO_ANTERIOR` (informativa: ese IVA y esa DIOT son del otro mes).
- **Saldo insoluto:** si `DoctoRelacionado@ImpSaldoInsoluto > 0` → `SALDO_INSOLUTO`
  (informativa). Nota (verificada en el XML real): el REP de CFE trae ImpSaldoAnt 3,907.00
  e ImpSaldoInsoluto 0.00; los 0.58 de diferencia con la factura (3,907.58) NO los reporta
  el REP, así que esta excepción no se dispara con el caso de agosto. El saldo 0.87 que
  queda en 201-01-002 (0.58 + 0.29 de arrastre) es una diferencia de CFE, no de la app.
- `ordenar_por_fecha` ordena por `fecha_poliza`.
- **Prueba:** REP Telmex → **03/08**; IMSS e7e5db0a → **06/08** con línea SIPARE 349460.

### Regla D — Reexpedición: mismo pago, UUID distinto
- **Llave de negocio:** `RFC_EMISOR|SERIE|FOLIO|TOTAL` con RFC y serie en mayúsculas sin
  espacios, serie vacía = `""`, folio sin espacios, total con 2 decimales.
  Ej.: `INF7205011ZA||PP347188|495.86`. Solo aplica a tipo I y E (los REP se comparan por UUID).
- **Acción:**
  1. UUID ya registrado en un lote vigente de OTRO periodo → omitir (`resultado =
     'reexpedicion'`, `documento_original_uuid` = ese mismo).
  2. Misma llave en un lote vigente de otro periodo → omitir como reexpedición, ligada al
     UUID original.
  3. Misma llave repetida DENTRO del lote → se contabiliza la de fecha de emisión más
     antigua; las demás se omiten como reexpedición.
- **Excepción:** `REEXPEDICION` (informativa): "UUID {nuevo} es reexpedición de {original}
  (póliza del {fecha} lote {periodo}). No se generó póliza: liga este XML con un AD a la
  póliza original en CONTPAQi."
- Las filas omitidas NO van a la DIOT.
- **Prueba:** con julio sembrado, INFONAVIT fac86dcb → **sin póliza** y excepción que
  menciona 5f09f69b (o 63f4f6e1).

### Regla E — Cuenta obsoleta o inválida
- **Lectura del catálogo** (`catalogo_contpaqi.leer`): solo líneas que empiezan con `C  `.
  Posiciones medidas sobre el `cuentas.txt` real de EEA (índice base 0):
  `cuenta = linea[3:34].strip()`, `nombre = linea[34:85].strip()`,
  `nombre_ingles = linea[85:136].strip()`, `cuenta_mayor = linea[136:167].strip()`;
  `linea[167:].split()` da los campos restantes: `[tipo, bandera_1, nivel, bandera_2,
  fecha_alta, ...]` y el **último** es el código agrupador (`603.50`). Encoding `latin1`.
  Posiciones VERIFICADAS el 2026-10-08 sobre el `cuentas.txt` real de EEA, p. ej.:
  `['60350000', 'Teléfono, internet', 'Telephone, Internet', '60300000',
  ['G','0','2','0','20260213','11','1','0','0','0','0','603.50']]`.
  Si un catálogo de otra empresa no coincide, ajusta y documenta aquí; nunca adivines.
- **Hipótesis empírica a confirmar con Svei** (no codificar como verdad sin confirmar):
  `nivel = 1` aparece en cuentas de mayor (60100000, 60300000) y `2` en subcuentas;
  `bandera_1 = 0` en todas (¿baja?). Si Svei no puede confirmarlo, la regla de
  "acumulativa" se resuelve así: **una cuenta es acumulativa si otra cuenta del catálogo
  la tiene como `cuenta_mayor`**. Eso no depende de banderas.
- **Una cuenta es inválida para movimientos si:**
  1. No existe en el catálogo.
  2. Es acumulativa (tiene hijas).
  3. Está en `cuentas_retiradas` de la empresa.
  4. Su agrupador no tiene punto (nivel 1, p. ej. `601`).
  5. Si `catalogo_espejo_agrupador = true`: el agrupador no es `cuenta[0:3] + "." + cuenta[3:5]`.
     (60040001 tiene `601.50`, su espejo sería `600.40` → inválida. 60350000 `603.50` ✓).
- **Orden de asignación de la cuenta de gasto:** `alias_terceros.cuenta_gasto` del RFC
  (determinista) → ML → `gastos_generales`. La cuenta resultante SIEMPRE se valida.
- **Excepción:** `CUENTA_INVALIDA` (bloqueante) con el motivo (1–5) y una sugerencia
  (mismo nombre en el catálogo o el alias).
- **Limpieza:** `db.limpiar_etiquetas` también borra etiquetas cuyo destino es una cuenta
  inválida, y se reentrena → el ML deja de proponer 60040001.
- **Prueba:** con `cuentas_retiradas` y/o espejo, 60040001 se rechaza; con el alias Telmex →
  60350000 la factura d66001ab sale en **603-50-000 335.34**.

### Regla F — Pago de cuota sin provisión
- **Disparador:** CFDI cuyo emisor está en `cuotas_patronales.rfcs`.
- **Saldo disponible del pasivo** (`cuenta_pasivo`, p. ej. 21101000) =
  saldo acreedor de la **balanza exportada** al cierre del mes anterior (si
  `balanza_path` está configurado)
  + provisiones que la app registró en el periodo
  − pagos que la app ya cargó a esa cuenta en el periodo.
- **Acción:**
  - saldo ≥ importe → cargo a `cuenta_pasivo`.
  - saldo = 0 → cargo a `cuenta_gasto` (60326000) + `PASIVO_SIN_SALDO` (informativa).
  - 0 < saldo < importe → `PASIVO_SALDO_PARCIAL` (bloqueante; Svei decide).
  - Sin balanza configurada → según `sin_balanza`: `"gasto_directo"` (default EEA) carga a
    gasto con excepción informativa.
- **Layout de la balanza (VERIFICADO el 2026-10-08 con `stuff/Balanza de Comprobacion
  07-2026.xlsx` y `08-2026.xlsx`):** Excel exportado de CONTPAQi, UNA hoja, 8 columnas
  (índice base 0), encabezados en las filas 0 a 6 y datos desde la fila 7:
  `0` cuenta con guiones (`211-01-000`; para compararla con el catálogo se quitan los
  guiones → `21101000`), `1` nombre, `2` saldo inicial deudor, `3` saldo inicial acreedor,
  `4` cargos, `5` abonos, `6` saldo actual deudor, `7` saldo actual acreedor. Las celdas sin
  saldo vienen vacías (NaN). Al final hay dos filas de totales (`Sumas Iguales:`, sin
  cuenta) que se ignoran. El título dice `Balanza de comprobación al 31/Jul/2026`.
  Al leer con pandas aparece un warning de openpyxl (`no default style`): es inofensivo.
  **Saldo de una cuenta de pasivo** = `acreedor actual − deudor actual` de la balanza
  del cierre del mes anterior (julio para correr agosto).
  **Dato real que valida la regla:** en la balanza de julio `211-01-000` cerró en 0 → el
  IMSS de agosto (2,108.78) va directo a `603-26-000`. En agosto, CONTPAQi Nóminas abonó
  3,129.15 a `211-01-000` (esa es la provisión de agosto; NO afecta el pago de julio).
  Como la balanza es del cierre del MES ANTERIOR, un pago a principios de mes no "ve" la
  provisión del mes en curso: es el comportamiento correcto para pagar cuotas del mes previo.
- **Prueba:** IMSS e7e5db0a → **Egreso 06/08, cargo 603-26-000 2,108.78 / abono 102-01-001**.

### Regla G — Un movimiento de banco, varias pólizas (DECISIÓN)
- **Decisión:** la conciliación contra el estado de cuenta **SÍ vivirá en esta app**, como
  **Parte 2** (sección 5), porque Svei quiere que la app lea estados de cuenta y, después,
  genere pólizas sin CFDI. **Razonamiento:** el estado de cuenta es la única fuente de
  verdad de cómo se agruparon los pagos (2,354.78 = 2,108.78 + 246.00) y de los movimientos
  sin CFDI (ISR, SPEI al socio, comisiones). Un CFDI nunca puede decir con qué otros pagos
  se juntó en un retiro, así que ninguna regla basada en el XML lo resuelve.
- **Mientras llega la Parte 2 (Fase 6):** hoja **MOVIMIENTOS_BANCO** en el Excel = todas las
  líneas a la cuenta de banco agrupadas por `fecha_poliza` con su suma diaria. Así Svei
  compara contra el estado de cuenta en un vistazo. La póliza del IMSS se genera normal.

### Regla H — Codificación del concepto
- **Decisión:** con `conceptos_ascii = true` (default), `exportar_txt_contpaqi` pasa
  Concepto de póliza y de movimiento por `texto_contpaqi.a_ascii()`: quita acentos,
  `ñ → n`, `Ñ → N`, conserva mayúsculas y minúsculas, y elimina lo que no sea ASCII
  imprimible. El Excel conserva los acentos.
- **Razonamiento:** hoy cp1252 con `errors="replace"` convierte en `?` cualquier carácter
  no representable sin avisar, y no hay forma de confirmar desde aquí que todas las
  versiones de CONTPAQi de Svei importan bien. Las Referencias ya son ASCII. ASCII nunca
  falla.
- **Reversible:** si Svei importa una póliza de prueba con "Reclasificación" y se ve bien,
  pone `conceptos_ascii = false`.
- **Prueba:** el TXT de agosto no contiene bytes > 0x7F.

### Regla I — Corrida que no produce pólizas (pedida por Svei)
- **Disparador:** (a) la carpeta no tiene XML/ZIP válidos, o (b) después de aplicar las
  reglas, todas las filas quedaron omitidas (nómina en modo contpaqi, cancelados,
  reexpediciones).
- **Acción:** NO se escriben TXT de pólizas, Excel ni TXT de DIOT. Se muestra un
  `messagebox` (no solo el Log) con el desglose. Ejemplo para las emitidas de agosto:
  > **Sin ingresos que contabilizar — 08/2026 (EEA251205CR8)**
  > Se leyeron 8 XML: 8 nómina (CONTPAQi Nóminas genera esas pólizas), 0 facturas de venta,
  > 0 cobros (REP), 0 cancelados.
  > No se generó archivo de pólizas.
- En recibidas el texto dice "egresos" y agrega: "No se generó TXT de DIOT."
- Se registra un lote con estado `sin_movimientos` (para que el mes conste como revisado).
- Caso (a) sin XML: no se puede deducir el periodo; el aviso dice la carpeta revisada.
  **Mejora:** si la carpeta sigue la bóveda (`...\<RFC>\Emitidas|Recibidas\<AAAA>\<MM>`), se
  toman RFC y periodo del path.
- **Prueba:** procesar Emitidas/2026/08 → aparece el aviso; en la carpeta de salida NO aparece
  ningún `Polizas_INGRESOS_EEA251205CR8_2026_08.*`.

### Reglas de cimientos (Fase 1)
- **Periodo del lote:** `periodo_lote.determinar(filas)` = el AAAA-MM más frecuente entre las
  fechas de emisión (empate → el más reciente). Cada XML de otro mes → `FUERA_DE_PERIODO`.
- **Cancelados (B-11):** estatus SAT `CANCELADO` → `omitir = True` (`resultado =
  'cancelado'`), fuera de pólizas y DIOT, con conteo en Log y hoja RESUMEN. Estatus
  `ERROR`/`DESCONOCIDO` → se contabiliza, con `ESTATUS_SAT_DESCONOCIDO`.

---

## 5. Parte 2 — Estados de cuenta bancarios (acordada; diseño fino pendiente)

**Por qué la app necesita los estados de cuenta:** sin ellos sólo conoce lo que tiene CFDI.
El estado de cuenta le da: (1) la agrupación real de pagos (caso G), (2) los movimientos sin
CFDI (pago de ISR, SPEI al socio, comisiones, intereses), (3) la confirmación de que lo que
la app mandó a banco sí salió del banco, con fecha e importe.

**Cómo se los pasa Svei (orden de preferencia):**
1. **Export CSV/Excel de la banca en línea** (BBVA Net Cash/Empresas suele permitir
   descargar movimientos). Es lo más confiable: ya trae columnas.
2. **PDF con texto seleccionable** → la app lo convierte con un parser por banco
   (`pdfplumber`) a un CSV normalizado.
3. **Copiar y pegar** el texto del PDF en una ventana de la app (respaldo).
4. PDF escaneado (imagen): fuera de alcance al inicio (requiere OCR).

**Validación obligatoria de toda ingesta:** saldo inicial + abonos − cargos = saldo final del
estado de cuenta. Si no cuadra, no se importa (evita movimientos perdidos por un mal parseo).

**Fases (después de la Parte 1):**

| Fase | Contenido | Modelo |
|---|---|---|
| 7 — Ingesta | Tabla `movimientos_bancarios` (cuenta_banco, fecha, descripcion, referencia, cargo, abono, saldo, origen, lote_estado_cuenta) + parser BBVA (CSV primero, PDF después) + validación de saldos | Opus 5.5 diseña con un estado de cuenta real; Sonnet 5.5 implementa |
| 8 — Conciliación | Emparejar pólizas con contrapartida banco ↔ movimientos (monto exacto, ventana de fechas, RFC/nombre en la descripción). Soporta N pólizas : 1 movimiento (caso G) y 1 : N. Hoja CONCILIACION y lo no conciliado de ambos lados | Opus 5.5 |
| 9 — Pólizas sin CFDI | Reglas + ML (descripción del movimiento → cuenta, mismo patrón que `ml_model.py` pero con modelo aparte) para proponer pólizas de los movimientos no conciliados. Siempre pasan por la ventana de excepciones antes del TXT | Opus 5.5 diseña, Sonnet 5.5 implementa |

**Estados de cuenta reales disponibles (agosto 2026)** en `stuff/` (carpeta ignorada por git,
NUNCA se sube): BBVA pesos (7 páginas), BBVA dólares (6 páginas) y Banamex (7 páginas).
Verificado el 2026-10-08: **los tres PDF tienen texto seleccionable** (no requieren OCR).
Implicaciones para el diseño de la Fase 7:
- Un parser por banco (BBVA y Banamex tienen layouts distintos); BBVA puede además venir en
  CSV desde la banca en línea.
- La cuenta en **dólares** obliga a que `movimientos_bancarios` guarde `moneda` y que la
  conciliación/pólizas manejen tipo de cambio (y, en la Fase 9, la revaluación mensual).

---

## 6. Roadmap Parte 1 (todas las fases: Sonnet 5.5)

> Todas las decisiones de arquitectura de la Parte 1 ya están en este documento, por eso
> todas sus fases las implementa **Sonnet 5.5**. Si una fase encuentra algo que contradice
> el documento, se detiene y pregunta (no improvisa arquitectura).

**Estado y prerrequisitos de Svei:**
- HECHO: `cuentas.txt` re-exportado (NextCloud, 20/10/2026 16:24; trae 20101002 y 20501002),
  balanzas de julio y agosto en `stuff/`, estados de cuenta en `stuff/`.
- Fase 1 HECHA (rama `fase-1-cimientos-mes-vacio`). Fase 2 HECHA (rama
  `fase-2-registro-contabilizados`).
- Antes de correr un mes real con la Fase 2: (a) botón "📚 Sembrar historial…" con la
  carpeta del mes anterior (y los meses que puedan traer reexpediciones), (b) en
  "Administrar Clientes y Proveedores": CFE370814QI0 → Cuenta tercero 20101002.
- Para las Fases 4 y 5 capturar además: TME840315KT6 → Cuenta gasto 60350000.

| Fase | Rama | Contenido | Criterio de salida (agosto 2026) |
|---|---|---|---|
| **1 — Cimientos y mes vacío** | `fase-1-cimientos-mes-vacio` | `config_empresa.py`, `excepciones.py` (+ hoja EXCEPCIONES), `periodo_lote.py`, `resumen_corrida.py`, `texto_contpaqi.py`, esqueleto de `reglas_contables.py`. Parser: `serie`, `folio`, `forma_pago`, `fecha_timbrado`, y por REP `pagos` (FechaPago, FormaDePagoP, Monto, doctos con IdDocumento/ImpPagado/ImpSaldoInsoluto/Serie/Folio). Cancelados excluidos (B-11). Reglas H e I | Emitidas 08 → aviso de "Sin ingresos" y **ningún archivo**. Recibidas 08 → la hoja BASE muestra las columnas nuevas; el TXT no tiene bytes > 0x7F; las pólizas generadas son las mismas que hoy (sin regresión) |
| **2 — Registro de lo contabilizado** | `fase-2-registro-contabilizados` | Esquema 3.6, ciclo de lote, `llave_negocio.py`, `detector_reexpediciones.py`, `cuenta_de_tercero.py`, `sembrar_historial.py` + botón, `learn_from_excel_ui` actualiza el registro, `alias_terceros` con cuenta de proveedor y `cuenta_gasto` en la ventana. Reglas A y D | Sembrar julio; correr agosto: INFONAVIT sin póliza + `REEXPEDICION`; REP CFE carga 20101002. Correr agosto otra vez: mismo resultado, cero falsas reexpediciones |
| **3 — Fecha y forma de pago** | `fase-3-fecha-y-forma-de-pago` | `fecha_de_poliza.py`, `formas_de_pago.py`, REP repartido por documento, `generar_polizas` lee `fecha_poliza` / `tipo_poliza` / `cuenta_contrapartida` / `aplicaciones_pago`. Reglas B y C | Filas 1 y 2 de la tabla final exactas (fechas 02/08 y 03/08, Telmex en Diario contra 205-01-002) |
| **4 — Validación de catálogo** | `fase-4-validacion-catalogo` | `catalogo_contpaqi.py` (ancho fijo), reemplaza `config.cargar_catalogo` / `validar_cuenta_vs_sat`, orden alias → ML → default, limpieza de etiquetas. Regla E | 60040001 rechazada con motivo; fila 4 exacta (603-50-000) con el alias de Telmex |
| **5 — Saldos de pasivo** | `fase-5-saldos-pasivo` | Documentar layout de balanza (sección 4-F), `balanza_contpaqi.py`, `cuotas_patronales.py`. Regla F | Fila 3 exacta (603-26-000 2,108.78, 06/08) |
| **6 — Ventana de excepciones** | `fase-6-ventana-excepciones` | `ventana_excepciones.py` antes de escribir el TXT (lista agrupada por severidad, botón "Generar TXT sin las bloqueadas" / "Cancelar"); el TXT excluye pólizas con excepción bloqueante (corrige el bug 1.3-5); hoja MOVIMIENTOS_BANCO (regla G, parte 1) | Ninguna póliza con cuenta PENDIENTE llega al TXT; todo lo que la app no decidió aparece en la ventana |

**Criterio de salida global de la Parte 1:** correr Recibidas/2026/08 (con julio sembrado,
catálogo re-exportado y alias capturados) y obtener **exactamente estas 4 pólizas**, ninguna
de INFONAVIT:

| Fecha | Tipo | Cargo | Abono |
|---|---|---|---|
| 02/08 | Egresos | 201-01-002 3,907.00 · 118-01-000 538.98 | 102-01-001 3,907.00 · 119-01-000 538.98 |
| 03/08 | Diario | 201-01-999 388.99 · 118-01-000 53.65 | 205-01-002 388.99 · 119-01-000 53.65 |
| 06/08 | Egresos | 603-26-000 2,108.78 | 102-01-001 2,108.78 |
| 14/08 | Diario | 603-50-000 335.34 · 119-01-000 53.65 | 201-01-999 388.99 |

Y en Emitidas/2026/08: el aviso de la regla I, sin archivos.

**Pruebas automatizadas:** carpeta `tests/` con `pytest`. Las funciones puras (llave de
negocio, regex IMSS, lectura de catálogo, formas de pago, periodo, ASCII) se prueban con
datos sintéticos. La prueba de aceptación de agosto lee los XML reales desde la variable de
entorno `BOVEDA_CFDI` y se salta si no existe. **Los XML y Excel reales NUNCA se suben al
repo** (datos fiscales confidenciales).

---

## 7. Notas fiscales que la implementación debe respetar

- IVA en flujo de efectivo (LIVA 1-B y 5 fr. III): el IVA de un PPD se queda en
  119-01 hasta su REP; la reclasificación a 118-01 ocurre en la `fecha_poliza` del pago
  (FechaPago), que es también la que define el mes de la DIOT.
- Un pago con tarjeta del socio sigue siendo un pago efectivo del proveedor (el IVA se
  acredita); lo que cambia es la contrapartida (deuda con el socio, 205-01-002), no el IVA.
- CFDI a RFC genérico XAXX010101000 en recibidas: no deducible / IVA no acreditable
  (CFF 29-A fr. IV, LISR 27 fr. III, LIVA 5 fr. II). Si aparece, excepción informativa.
- Reexpediciones y cancelados no van a la DIOT (no son operaciones nuevas).

---

## 8. Git

Rama por fase (nombres en la tabla de la sección 6). Probar local contra los XML de agosto
2026 antes de merge a `main`. Nada se mezcla a `main` sin pasar el criterio de salida de su
fase.

**Mensajes de commit (preferencia firme de Svei):** UNA sola línea, entre comillas
simples, sin acentos, sin comillas dobles ni caracteres especiales, y SIN la línea
`Co-Authored-By`. Ejemplo:
`git add archivo.py && git commit -m 'Fase 1: cimientos, cancelados excluidos y aviso de mes vacio'`

---

## 9. Reglas de estilo de código de Svei (obligatorias, íntegras)

- Funciones pequeñas de propósito único.
- Comentarios explicativos estilo "profesor de salón de clases" — el código
  debe poder debuggearse en una sesión fresca de IA sin contexto previo.
- Nombres en lenguaje natural, descriptivos.
- Prohibidos los patrones ingeniosos-pero-crípticos.
- Archivos chicos, arquitectura modular, separación de responsabilidades (SRP).
- Carpetas: lowercase kebab-case. Python: snake_case. Sin espacios,
  acentos ni caracteres especiales en nombres de archivos.

(Aclaración técnica: como Python no importa carpetas con guiones, los módulos `.py` viven
planos en la raíz con `snake_case`; el kebab-case aplica a carpetas que no son paquetes.)
