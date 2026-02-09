# AUDITORÍA Y ROADMAP — importar_xml_a_contabilidad (v2)

> **Qué es este documento.** Spec autónomo para que Claude Sonnet 5 u Opus ejecuten el
> fortalecimiento de esta app SIN necesitar la conversación original. Léelo completo antes
> de tocar código. El repo vive en `D:\repos\importar_xml_a_contabilidad`.
> Complemento obligatorio: `ROADMAP.md` (decisiones fiscales/de negocio ya tomadas — NO
> reabrirlas sin avisar al dueño) e `INSTRUCCIONES.md` (flujo de uso).
>
> **Alcance:** este documento cubre ARREGLOS Y MEJORAS sobre la app existente, que ya
> funciona y está en uso real. NO es una reescritura desde cero; no rediseñes lo que sirve.
>
> **v2 — reemplaza por completo la versión anterior.** Correcciones clave respecto a v1:
> 1. **NO existe ningún "selector de modelo de IA"** en esta app (eso era confusión de otra
>    sesión con otra app). El problema UX real está en la §8.1.
> 2. **NO hay bug de "freeze".** El dueño lo probó con datos reales y no ocurre. Queda solo
>    una nota de robustez opcional (§6, R-1). No lo trates como bug ni lo llames crítico.
> 3. El lanzador es **`run.bat`** (no `run_gui.bat`; ese archivo pertenece a otra app).
> 4. **cfdi-app es un proyecto totalmente independiente** (ver §2.1). Prohibido acoplarlos.

---

## 1. REGLAS DE ESTILO DE CÓDIGO — NO NEGOCIABLES

El dueño (svei, contador) revisa este código solo, tiempo después, sin el modelo presente.
TODO el código que generes debe cumplir:

1. **Funciones pequeñas.** Una función hace UNA cosa clara. Nada de funciones de 200 líneas.
2. **Comentarios que explican el PORQUÉ**, como si explicaras un problema de matemáticas a un
   salón paso a paso — no como un revisor terso. El "qué" ya se ve en el código; el "por qué" no.
3. **Nombres planos y legibles**, casi como se dirían en voz alta (híbrido español-inglés que
   el dueño usa: `cargar_catalogo`, `construir_referencia`). Nada de abreviaturas crípticas.
4. **Cero listeza por lucirse.** La forma aburrida y obvia gana sobre la elegante-críptica.
5. **Cada módulo se entiende solo**, sin cargar toda la app en la cabeza.

Reglas de proceso:
- **Proponer y acordar ANTES de implementar.** No reescribas lógica que ya funciona.
- Un cambio → una prueba → un commit. Nunca mezclar refactor con cambio de comportamiento.
- Cada fase termina con la app **corriendo y usable** (shippable).
- Si algo fiscal o de CONTPAQi no lo puedes verificar, DILO y pide probarlo en una empresa
  de prueba antes de tocar datos reales. No afirmes con confianza lo que no verificaste.

---

## 2. CONTEXTO

**Qué hace la app:** lee CFDI 4.0 (XML del SAT que el usuario descarga manualmente del portal),
valida el estatus en el SAT, clasifica la cuenta de gasto con ML (solo gastos/recibidas),
y genera: Excel de revisión, TXT de pólizas de ancho fijo para **CONTPAQi Contabilidad 18.5.2**
y TXT de **DIOT** (54 columnas). Estado: **funcionalmente completa y en uso real**. Etapa
actual: endurecimiento (bugs, bordes, UX) antes de darla por terminada.

### 2.1 Restricción: independencia de cfdi-app
`cfdi-app` es OTRO proyecto. No comparten código, carpetas ni lógica. El único enlace futuro
planeado es que cfdi-app quizá **escriba XMLs en una carpeta que esta app lee** — un enlace de
sistema de archivos, manual, NO una dependencia de código. Por lo tanto:
- La entrada de esta app **es y seguirá siendo una carpeta** (con XML sueltos y/o ZIPs).
- **No** diseñes imports, APIs compartidas ni módulos comunes entre ambas.
- **No** asumas arquitectura compartida. Si un cambio "prepararía la integración", NO lo hagas.

### 2.2 Mapa de módulos (verificado contra el repo)

| Archivo | Rol | Estado |
|---|---|---|
| `main.py` (~516 líneas) | UI Tkinter + orquestación (`process_folder`) | Funciona; mezcla UI y negocio (§5.A) |
| `xml_processor.py` | Parser CFDI 4.0; lee XML y ZIP; **reporta archivos fallidos** | OK |
| `sat_validator.py` | Estatus SAT por UUID (HTTP GET, retry, timeout 10s) | Funciona; sin caché (§6 R-1) |
| `ml_model.py` | ML **por empresa** (`empresas/<RFC>/modelo.pkl`) | OK |
| `db.py` | SQLite por empresa: facturas, etiquetas, DIOT, alias/tipo/cuenta de terceros | OK; excepts silenciosos (§6 B-7) |
| `export.py` (~24 KB) | Árbol Debe/Haber, Excel, TXT pólizas ancho fijo, validación de cuadre | OK; grande pero funcional |
| `diot.py` | DIOT: 1 fila por RFC, base de flujo (PUE+REP), omite gobierno sin IVA | OK (endurecido recientemente) |
| `terceros.py` | Alias, Title Case, Referencia `RFC-ALIAS` | OK |
| `config.py` | settings.json + catálogo + validación de cuenta | **Defaults obsoletos** (§6 B-1) |
| `validar_layout.py` | Verificador externo del TXT (columnas + cuadre) | OK (script manual) |
| `dashboard.py` | Visor Dash/Plotly opcional | **Roto** (§6 B-8) |
| `run.bat` / `run.sh` | Lanzador: venv + pip install inline + `python main.py` | Funciona; sin pins (§6 B-2) |

**Regla de oro del TXT (ya resuelta, NO tocar):** el TXT de CONTPAQi es de ANCHO FIJO — campo
cuenta = 31 caracteres, importe en col 67, bloque `0.0` en col 99. Cualquier cambio en
`export.py::exportar_txt_contpaqi` debe validarse con `validar_layout.py` contra un TXT bueno.

### 2.3 Cómo aprende el ML (aclaración pedida por el dueño — no lo cambies)

- **El ML es POR EMPRESA** (`empresas/<RFC>/modelo.pkl`) y es DELIBERADO: antes existía un
  `modelo.pkl` global y fue un bug que se arregló (contaminaba predicciones entre clientes).
- **Por qué no puede ser global:** las etiquetas que el modelo aprende y predice SON números
  de cuenta (`texto de factura → cuenta`), y los números de cuenta pertenecen al COA de UNA
  empresa. Un modelo general predeciría cuentas de la empresa A en los libros de la empresa
  B (mismo tipo de contaminación que B-12). Además, dos empresas pueden clasificar
  legítimamente distinto el mismo gasto (política contable propia).
- **El ML solo predice la cuenta de GASTO.** Las `cuentas_default` (bancos, IVA, ventas,
  clientes, proveedores, retenciones, IEPS) son el ESQUELETO fijo de toda póliza: el ML
  jamás las toca y NUNCA dejan de ser necesarias, por muy entrenado que esté el modelo.
  Lo único que el ML va desplazando con el tiempo es el fallback de `gastos_generales`.
- 💡 Idea madurable (NO comprometida): una capa de "sugerencia general" entre empresas
  usando el código agrupador del SAT como etiqueta neutra (gasto genérico → luego mapear al
  COA de cada empresa). Solo si algún día se comercializa; no construir ahora.

---

## 3. ESTADO VERIFICADO DEL REPO (hechos, no suposiciones)

- Lanzador: **`run.bat`** (instala pandas, scikit-learn, requests, openpyxl inline, sin
  versiones fijas, con `>nul 2>&1` que oculta errores de pip).
- **No hay `requirements.txt`**. OJO: `.gitignore` contiene `*.txt`, así que si se crea
  `requirements.txt` hay que agregar la excepción `!requirements.txt` o git lo ignora.
- `.gitignore` también ignora `settings.json` y `empresas/` → en un clon limpio la app se
  configura desde los defaults de `config.py` (que están desactualizados → §6 B-1).
- `modelo.pkl` en la raíz está **muerto** (los modelos viven en `empresas/<RFC>/modelo.pkl`).
- No existe carpeta `tests/`.
- La UI usa **widgets clásicos `tk.*`** (`tk.Button/Label/Frame/Text`) con colores hex
  hardcodeados (paleta oscura tipo Catppuccin). Solo usa `ttk` en `Treeview` y `Combobox`.
  Este hecho es CENTRAL para el veredicto de tema (§8.2).

---

## 4. HALLAZGOS DE ARQUITECTURA (lo que dolerá después)

**A. `main.py` mezcla UI + orquestación + negocio.** `process_folder` hace I/O de archivos,
red (SAT), ML, BD y exportación, e imprime a un `sys.stdout` redirigido al widget de log.
Consecuencia práctica: el núcleo no se puede probar sin abrir la ventana. La salida correcta
es extraer un núcleo testeable (§9 Fase 4) — **motivado por testeabilidad, NO por cfdi-app**.

**B. El esquema de settings no tiene fuente única de verdad.** Las claves y defaults viven
regados en `.get(clave, default)` por `export.py` y `main.py`, y el default que escribe
`config.py` en instalación limpia está desincronizado del esquema real (§6 B-1).

**C. El RFC de empresa se deduce del nombre de archivo.** `learn_from_excel_ui` obtiene el RFC
partiendo el nombre del Excel (`partes[2]`). Si el usuario renombra el archivo, el flujo de
aprendizaje truena o aprende bajo otra empresa (§6 B-5).

**D. Una carpeta = una empresa (supuesto implícito).** `process_folder` toma el RFC de empresa
de `rows[0]`. Si la carpeta mezcla XMLs de dos empresas, todo cae bajo la primera (§6 B-6).

**E. Errores silenciosos residuales.** `db.py` tiene `except Exception: pass` en
`limpiar_etiquetas` y `get_training_data`; `export.py` tiene un par de `except` amplios.
El parser ya NO traga errores (se arregló), pero estos puntos aún esconden fallas (§6 B-7).

**F. RESTRICCIÓN ARQUITECTÓNICA (orden del dueño): separación núcleo/GUI.** El dueño quiere
poder cambiar de GUI en el futuro (uniformar el look de todas sus apps) sin reescribir la
lógica. Esto es el patrón estándar de "arquitectura en capas / separación de
responsabilidades" que usan los despachos de programación, y aplica así:
- **Buena noticia verificada:** la MAYORÍA de los módulos YA son núcleo puro sin GUI
  (`xml_processor`, `export`, `diot`, `db`, `terceros`, `ml_model`, `validar_layout`).
  Tkinter NO está regado por todo el código; está enredado en DOS lugares:
  `main.py` (orquestación `process_folder` mezclada con ventanas) y `config.py`
  (el diálogo `Tk()` de B-3).
- **Regla desde YA para todo código nuevo:** la lógica de negocio JAMÁS importa `tkinter`
  ni llama `messagebox`/`filedialog`. La UI llama al núcleo, nunca al revés. El núcleo
  reporta por callback de log y valores de retorno.
- **La Fase 4 materializa el split completo.** Terminada esa fase, cambiar de GUI
  (customtkinter, PySide6, lo que sea) = reescribir SOLO la capa de UI.

---

## 5. LO QUE **NO** ES UN BUG (corrección explícita de v1)

- **"Freeze al procesar": NO confirmado. El dueño lo probó con lotes reales y NO ocurre.**
  El razonamiento de v1 ("llamadas SAT secuenciales en el hilo de UI ⇒ se congela") era una
  inferencia de lectura de código presentada indebidamente como bug crítico. La realidad
  medida por el dueño manda. Queda como nota de robustez R-1 (§6), estrictamente opcional.
- **"Selector de modelo de IA confundible con selector de carpetas": NO existe tal control.**
  La barra izquierda tiene 5 botones y las carpetas se eligen con `filedialog`. El problema
  UX real y confirmado por el dueño es la AGRUPACIÓN de la barra (§8.1).

---

## 6. LISTA DE BUGS Y RIESGOS (verificados contra el código, por severidad)

| ID | Sev | Problema | Cómo reproducir | Arreglo propuesto |
|---|---|---|---|---|
| B-1 | **ALTO** | **Instalación limpia genera config inválida.** `config.py::load_settings` escribe defaults viejos: `bancos: "10201000"` (cuenta de MAYOR, no afectable — CONTPAQi la rechaza) y FALTAN llaves que el código ya usa: `ventas`, `clientes`, `clientes_extranjero`, `ieps_acreditable`, `ret_isr_honorarios`, `ret_iva`, `ret_isr_nomina`, `acredita_ieps`, `nomina_modo`, `proveedores`. Como `settings.json` está en `.gitignore`, TODA máquina nueva arranca rota. | Renombrar `settings.json`, abrir la app, procesar | Definir `DEFAULT_SETTINGS` completo en `config.py` (copiar el esquema real del settings.json vigente) + `validar_settings()` al arranque que rellene llaves faltantes SIN borrar valores del usuario. |
| B-2 | **ALTO** | **Dependencias sin fijar.** `run.bat` hace `pip install pandas scikit-learn requests openpyxl >nul 2>&1`: sin versiones (drift de API de sklearn/pandas romperá el modelo o el Excel algún día) y con errores de pip OCULTOS. | Instalar en equipo nuevo meses después | Crear `requirements.txt` con versiones fijas probadas + `!requirements.txt` en `.gitignore` + `run.bat` instala desde ahí y SIN silenciar errores. |
| B-3 | MEDIO | **Segundo `Tk()` root.** `config.cargar_catalogo()` crea `root = Tk(); root.withdraw()` cuando falta el catálogo — dentro de una app que YA tiene root. Dos roots Tk = comportamiento errático conocido (diálogos huérfanos, cierres raros). | Quitar `catalogo_path` de settings y procesar | El diálogo de catálogo vive en la UI (ya existe en Configuración); `cargar_catalogo()` solo lee de settings y devuelve DataFrame vacío + aviso si falta. |
| B-4 | MEDIO | **Aviso de fin puede aparecer sin foco / detrás.** `messagebox.askyesno` al final de `process_folder` se invoca sin `parent=`, puede quedar detrás de la ventana. Menor pero visible. | Procesar con otra ventana encima | Pasar `parent` explícito. |
| B-5 | MEDIO | **RFC de empresa deducido del nombre del archivo Excel.** `learn_from_excel_ui`: `rfc = filename.split("_")[2]`. Renombrar el Excel rompe el aprendizaje o aprende en la empresa equivocada. | Renombrar el Excel corregido y cargarlo | Escribir el RFC DENTRO del Excel (hoja RESUMEN, celda fija) al exportar, y leerlo de ahí al aprender; el nombre queda solo como respaldo. |
| B-6 | MEDIO | **Lote con XMLs de 2+ empresas se procesa TODO bajo la primera.** `empresa_rfc = rows[0][...]`. Riesgo LEGAL para un despacho (revolver contabilidades de dos RFC). | Mezclar XMLs de 2 RFCs de empresa en una carpeta | RESUELTO (§7-Q3): detectar N>1 RFCs de empresa → ABORTAR listando los RFCs. Es guard anti-accidente; la app sigue siendo multi-empresa. |
| B-7 | BAJO | **Excepts silenciosos** en `db.py::limpiar_etiquetas` / `get_training_data` (y un par en `export.py`). Violan la regla de "no tragar errores". | Corromper la BD y llamar | Loggear el error (`print` al log) en vez de `pass`; NO cambiar el flujo. |
| B-8 | BAJO | **`dashboard.py` roto:** llama `get_conn()` sin RFC (la API es multi-empresa desde hace meses). Archivo suelto que nada en la app invoca. | `python dashboard.py` | RESUELTO (§7-Q1): BORRAR. |
| B-9 | BAJO | **`modelo.pkl` muerto en la raíz.** Confunde a quien lea el repo. | — | Borrar el archivo. |
| B-10 | BAJO | **`settings.json` se escribe sin encoding explícito** (`open(..., "w")` → cp1252 en Windows). Hoy no truena porque `json.dump` escapa ASCII, pero es una mina si algún valor lleva acentos con `ensure_ascii=False` futuro. | — | `open(..., "w", encoding="utf-8")` en load/save. |
| B-12 | **ALTO** | **La configuración fiscal (`cuentas_default`, `catalogo_path`, `acredita_ieps`, `nomina_modo`) es GLOBAL en `settings.json`, NO por empresa.** Verificado: hoy solo existe EEA251205CR8, así que nunca se nota. El día que se dé de alta un segundo RFC, ese cliente heredaría SILENCIOSAMENTE el catálogo y las cuentas de EEA (banco, ventas, retenciones…) — pólizas fiscalmente incorrectas sin ningún aviso. | Dar de alta una 2da empresa y procesar | RESUELTO (§7-Q4): mover esta config a `settings["empresas"][RFC]`, con migración NO destructiva del `settings.json` actual (ver Fase 2). |
| B-11 | MEDIO (fiscal) | **CFDI CANCELADO genera póliza igual.** Hoy solo imprime alerta y sigue; el cancelado entra a pólizas y (si es recibida con IVA) a la DIOT. | Procesar un XML cancelado | RESUELTO (§7-Q2): EXCLUIR de pólizas y DIOT, con conteo visible en Log + hoja RESUMEN. La validación se queda en esta app. |

### Notas de robustez (NO bugs; opcionales, decisión del dueño)
| ID | Nota |
|---|---|
| R-1 | La validación SAT es secuencial (1 GET por UUID, `Session` nueva cada vez, timeout 10s, sin caché). **El dueño confirma que a sus volúmenes reales NO congela ni estorba.** Mejora opcional si algún día molesta: `Session` única a nivel módulo + caché `{uuid: estatus}` para no revalidar + toggle "Validar en SAT" en Configuración. NO lo implementes sin que el dueño lo pida. |
| R-2 | El widget de log crece sin límite en sesiones muy largas. Irrelevante en uso normal. |
| R-3 | `run.bat` corre `pip install` en cada arranque (lento tras la primera vez). Cosmético. |

---

## 7. DECISIONES YA RESUELTAS POR EL DUEÑO (ejecútalas tal cual, no las reabras)

- **Q1 — `dashboard.py`: BORRAR.** Aclaración importante: `dashboard.py` NO es el menú
  principal (ese vive en `main.py`) ni el botón bajo "Inteligencia Artificial". Es un visor
  web suelto (Dash/Plotly) que ningún botón de la app llama, solo correría a mano, y está
  roto desde la migración multi-empresa. El dueño ni sabía que existía = no se usa. Se borra
  (y `dash`/`plotly` NO van en `requirements.txt`).
- **Q2 — CFDI cancelados: EXCLUIR de pólizas y DIOT**, con conteo visible en el Log y en la
  hoja RESUMEN (que se VEA cuántos se excluyeron, nunca silencioso). Además: la validación de
  estatus SAT **vive en ESTA app y se queda aquí** — esta app produce los entregables
  fiscales y debe defenderse sola sin importar de dónde vengan los XML. Si cfdi-app algún día
  valida al descargar, será un segundo filtro, NO un reemplazo. No acoples nada por esto.
- **Q3 — La app ES y SEGUIRÁ SIENDO multi-empresa; lo que nunca se mezcla es EL LOTE.**
  Igual que los productos CONTPAQi (Contabilidad, Nóminas, Facturación), esta app maneja
  varias empresas — y YA lo hace: BD, modelo ML y alias viven por RFC en `empresas/<RFC>/`,
  y la bóveda de XMLs del dueño llega separada por RFC
  (`C:\AdminXML\BovedaCFDI\<RFC>\Emitidas|Recibidas\<año>\<mes>`). La regla operativa es:
  **una corrida = una empresa = una carpeta con XMLs de UN solo RFC.** Si en la carpeta
  seleccionada aparecen XMLs de 2+ RFCs de empresa, ABORTAR con aviso que liste los RFCs
  detectados — eso es un ACCIDENTE del usuario (eligió mal la carpeta), no un modo de
  operación. Razón del dueño (real, legal): un despacho lleva varias empresas y revolver
  comprobantes de dos RFC en una contabilidad puede escalar a problema legal. El guard es
  un cinturón de seguridad contra ese descuido — **NO una limitación del multi-empresa.**
  **DECISIÓN ADICIONAL del dueño: selector de empresa ESTILO CONTPAQi** (primero abres la
  empresa, luego trabajas dentro de ella). Ver construcción en Fase 2: empresa activa en la
  ventana principal, los diálogos abren directo en la bóveda de ese RFC, y el lote se valida
  contra la empresa activa (doble candado).

- **Q4 — Alta de empresa (nueva, NO estaba cubierta en v2 — el dueño la pidió expresamente):**
  "➕ Nueva empresa…" NO puede ser solo "pide RFC y carpeta". Debe:
  1. **Validar el RFC** (12 caracteres persona moral / 13 persona física, alfanumérico).
  2. **Pedir/crear la carpeta bóveda** (`Emitidas/` y `Recibidas/` si no existen).
  3. **Crear su entrada de configuración PROPIA y VACÍA** — nunca copiar las cuentas de otra
     empresa (eso es justo el bug B-12). El catálogo (`cuentas.txt`) y las `cuentas_default`
     (bancos, ventas, clientes, retenciones…) arrancan **sin configurar**, y la UI lo dice
     claramente ("⚠️ Configura el catálogo y las cuentas de esta empresa antes de procesar").
  4. Crear su carpeta `empresas/<RFC>/` (BD/modelo ML) — `db.init_db(rfc)` ya lo hace, solo
     hay que asegurarse de que el alta la dispare.
  5. Quedar seleccionable de inmediato en el combobox de empresa activa.
  **Salida de la migración:** el `settings.json` actual del dueño (EEA con su catálogo y
  cuentas ya configuradas) se convierte en la primera entrada de `empresas`, sin perder nada.

---

## 8. UX Y FRAMEWORK

### 8.1 Fix UX inmediato — reagrupar la barra izquierda (el problema real)
En `main.py` (~líneas 486-488) el encabezado **"Inteligencia Artificial:"** cubre DOS botones:
"🧠 Aprender de Excel Corregido" (sí es IA) y "👥 Administrar Clientes y Proveedores" (NO es
IA: es un catálogo determinista RFC→alias/cuenta). El usuario interpreta el segundo como
función de IA. **Fix:** dejar bajo "Inteligencia Artificial" SOLO "Aprender…", y crear una
sección **"Catálogos"** (o "Datos") para "Administrar Clientes y Proveedores". Es mover
2-3 líneas de `pack()`; cero lógica.

Micro-mejoras opcionales del mismo pase (baratas, no obligatorias):
- Los botones EMITIDAS/RECIBIDAS abren un `filedialog` directo; un subtítulo pequeño
  "elige la carpeta de XML del mes" bajo el encabezado "Procesamiento:" elimina dudas.
- `parent=` en todos los `messagebox` (ver B-4).

### 8.2 Veredicto de framework y tema — QUEDARSE EN TKINTER; tema vía customtkinter
**Requisito:** toggle claro/oscuro con default = seguir el tema del SO al arrancar, y tintes
suavizados (azuloso/violáceo) — el negro puro cansa la vista del público objetivo (contadores
40-60 años).

**Hecho técnico que descarta la opción "barata":** la UI actual usa widgets **clásicos
`tk.*` con colores hex**, no `ttk`. `sv_ttk` (y los temas ttk de ttkbootstrap) **solo
tematizan widgets ttk** — ponerlos encima NO cambiaría la mayoría de esta interfaz. Cualquier
camino de tema implica tocar los widgets. Las opciones reales:

| Opción | Costo | Qué da | Veredicto |
|---|---|---|---|
| **(A) customtkinter** | Medio-bajo: reemplazo mecánico `tk.Button→CTkButton`, etc., pantalla por pantalla; la lógica, threading y bindings NO cambian (sigue siendo Tkinter debajo) | `set_appearance_mode("System")` nativo (sigue al SO), toggle Light/Dark/System de fábrica, temas de color propios (los tintes), look moderno vendible | **RECOMENDADO** |
| (B) Paleta propia + `darkdetect` | Bajo: diccionarios de colores claro/oscuro + función que re-pinta widgets + `darkdetect` para el default del SO | Control total de tintes, cero dependencias de UI nuevas, conserva el diseño actual exacto | Alternativa válida si (A) da problemas; más código artesanal que mantener |
| (C) ttkbootstrap | Medio: requiere convertir widgets a ttk/ttkbootstrap (escala similar a A) | Muchos temas listos claro+oscuro | Sin ventaja clara sobre (A) para esta app |
| (D) Migrar a PySide6 | ALTO: reescribir TODA la capa de UI (ventana principal + 2 Toplevels + log + threading/eventos) | Light y dark nativos, estética más "pro", mejor para producto comercial | **DIFERIDO** — no se justifica hoy |

**Razonamiento del veredicto (no "PySide es más bonito"):** la app está terminada y en uso;
hoy tiene UN usuario (el dueño); el único driver del tema se satisface DENTRO de Tkinter con
(A) a una fracción del costo de (D). Migrar a PySide6 ahora = pagar una reescritura completa
de UI que funciona, a cambio de un beneficio estético para un futuro comercial que aún no se
decide. PySide6 sí soporta claro y oscuro nativos — el punto no es capacidad, es costo/beneficio.
**Disparador para reabrir (D):** decisión firme de vender versión de paga ("PRO"). En ese
momento se planifica la migración como proyecto propio (estimación: días, no horas — 3
ventanas + puente de log + empaquetado). Nota de negocio del dueño: vender requiere además un
documento legal que lo deslinde de errores de los contadores usuarios — fuera de alcance
técnico, no lo olvides en la planeación comercial.

---

## 9. ROADMAP POR FASES (cada fase es independientemente shippable)

> Puedes DETENERTE al final de cualquier fase y la app sigue funcionando.

**Fase 0 — Higiene (riesgo cero).** Borrar `modelo.pkl` raíz (B-9); crear `requirements.txt`
con versiones fijas + excepción en `.gitignore` (B-2); `run.bat` instala desde requirements y
sin `>nul` en pip; encoding utf-8 en settings (B-10).
*Salida:* clon limpio + `run.bat` → la app abre sin errores. Ship.

**Fase 1 — Instalación y configuración a prueba de máquina nueva.** `DEFAULT_SETTINGS`
completo + `validar_settings()` (B-1); eliminar el segundo `Tk()` (B-3); `parent=` en
messageboxes (B-4); excepts silenciosos → log (B-7); borrar `dashboard.py` (B-8, §7-Q1).
*Salida:* borrar `settings.json` y arrancar produce config válida y completa; sin roots
duplicados; los errores de BD se VEN en el log. Ship.

**Fase 2 — Robustez de datos + empresas por config propia.** Config por empresa en
`settings.json` con migración no destructiva (B-12); selector de empresa + alta de empresa
estilo ContpaqI (§7-Q3, §7-Q4): empresa activa + bóveda automática + doble candado
lote-vs-empresa (cubre B-6); RFC dentro del Excel y leerlo al aprender (B-5); cancelados →
EXCLUIR de pólizas y DIOT con conteo visible (B-11, §7-Q2).
*Salida:* el settings.json actual migra sin perder nada; eliges empresa y la app te lleva a
SU bóveda; dar de alta un RFC nuevo lo deja vacío y avisado hasta configurarlo (nunca hereda
cuentas de otra empresa); un lote ajeno o mixto aborta listando RFCs; renombrar el Excel no
rompe el aprendizaje; los cancelados no entran a pólizas/DIOT y se ven contados. Ship.

**Fase 3 — UX + Tema.** Reagrupar la barra (§8.1); migrar widgets a customtkinter pantalla
por pantalla (main → Configuración → Clientes/Proveedores); toggle Light/Dark/System con
default **System**; tema de color con los tintes suavizados.
*Salida:* la barra ya no confunde; los tres modos se ven y se leen bien; arranca siguiendo
el tema del SO. Ship.

**Fase 4 — Separación núcleo/GUI (restricción §4.F) + endurecimiento.** Materializar el
split en capas: extraer el pipeline de `process_folder` a `pipeline.py` SIN Tkinter (recibe
carpeta+tipo+config+callback de log, devuelve resultado; `messagebox` se queda en la UI);
`main.py` queda como capa de GUI delgada que solo llama al núcleo. Estructura objetivo
(puede ser plana o con carpetas `core/` y `ui/` — lo importante es la regla de dependencia:
UI → núcleo, nunca al revés). Crear `tests/` con 3-5 XML de muestra y pruebas de: cuadre
Debe=Haber, DIOT (omite gobierno sin IVA; base col 12 / IVA col 31 / col 54), retenciones,
PPD+REP, exclusión de cancelados.
*Salida:* `pytest` verde; la UI se comporta idéntica; y la prueba de fuego del dueño:
**cambiar de GUI ahora = reescribir solo la capa de UI** (customtkinter, PySide6 o la que
sea, para uniformar sus apps). Ship.

**Fase opcional B — Migración a PySide6.** SOLO si se decide vender PRO. Proyecto aparte con
su propio plan; nada de las fases 0-4 se desperdicia (el pipeline extraído en Fase 4 es
agnóstico de UI).

---

## 10. MÉTODO DE CONSTRUCCIÓN POR FASE (orden y checkpoints)

**Regla transversal:** después de CUALQUIER cambio que toque `export.py`, correr
`python validar_layout.py <txt generado>` contra un lote real y confirmar cuadre.

### Fase 0
1. `git rm modelo.pkl` (verificar antes que `empresas/<RFC>/modelo.pkl` existe).
2. Congelar versiones actuales del venv (`pip freeze` filtrado a las 4 libs + sus mayores) →
   `requirements.txt`. Agregar `!requirements.txt` al `.gitignore` (¡el patrón `*.txt` lo
   ignoraría!).
3. Editar `run.bat`: `pip install -r requirements.txt` (sin `>nul 2>&1`).
4. `config.py`: agregar `encoding="utf-8"` en los `open()` de load/save.
   **Checkpoint:** borrar `venv/`, correr `run.bat`, la app abre y procesa un lote de prueba.

### Fase 1
1. `config.py`: copiar el esquema REAL del `settings.json` vigente a `DEFAULT_SETTINGS`;
   escribir `validar_settings(s)` que agregue llaves faltantes (sin pisar valores existentes)
   y se llame en `load_settings()`.
   **Checkpoint:** renombrar `settings.json` → arrancar → diff contra el original: solo
   difieren rutas personales.
2. `config.cargar_catalogo()`: quitar `Tk()/withdraw/askopenfilename`; si no hay catálogo,
   devolver DataFrame vacío + mensaje que dirija a Configuración (la selección YA existe ahí).
   **Checkpoint:** sin catálogo configurado, procesar no crea segunda ventana ni truena.
3. `main.py`: `parent=` en todos los `messagebox`.
4. `db.py`: reemplazar `except Exception: pass` por log del error preservando el flujo.
5. Borrar `dashboard.py` (decisión §7-Q1) y confirmar que nada lo importa (`grep dashboard`).

### Fase 2
1. `export.py`: al escribir la hoja RESUMEN, incluir fila `"EmpresaRFC": <rfc>`.
   `main.py::learn_from_excel_ui`: leer el RFC de esa celda; usar el nombre de archivo solo
   como respaldo con aviso.
   **Checkpoint:** renombrar un Excel corregido a `x.xlsx` y aprender → funciona.
2. **Rediseñar `settings.json` a config POR EMPRESA (arregla B-12 + habilita Q3/Q4 juntos).**
   Estructura nueva:
   ```json
   {
     "empresa_activa": "EEA251205CR8",
     "empresas": {
       "EEA251205CR8": {
         "boveda_path": "C:/AdminXML/BovedaCFDI/EEA251205CR8",
         "catalogo_path": "D:/.../cuentas.txt",
         "last_ingresos_path": "...", "last_egresos_path": "...",
         "cuentas_default": { "bancos": "10201001", "...": "..." },
         "acredita_ieps": false, "nomina_modo": "contpaqi"
       }
     },
     "output_path": "D:/Downloads"
   }
   ```
   (`output_path` se queda global — es solo dónde caen los archivos exportados, no una
   cuenta contable; si el dueño luego quiere carpetas de salida distintas por empresa,
   es un cambio menor y aislado, no bloquea nada.)

   a. **Migración NO destructiva al arrancar:** si `settings.json` tiene las llaves viejas
      sueltas (`catalogo_path`, `cuentas_default`, etc. en la raíz) y NO tiene `"empresas"`,
      moverlas automáticamente a `empresas[<ese RFC>]` (el RFC sale de `last_ingresos_path`
      o de `db.list_empresas()`), y avisar en el Log qué se migró. **Nunca perder la
      configuración ya hecha del dueño (EEA).**
   b. **Alta de empresa (§7-Q4), botón "➕ Nueva empresa…":** valida RFC (12/13 chars
      alfanumérico) → pide/crea la carpeta bóveda con `Emitidas/`+`Recibidas/` → crea su
      entrada en `empresas` **VACÍA** (catálogo sin definir, `cuentas_default` vacío) →
      `db.init_db(rfc)` → aparece en el combobox y queda como candidata "sin configurar".
      La UI debe advertir claramente si intentas procesar una empresa sin catálogo/cuentas
      configurados ("Configura esta empresa en ⚙️ Configuración antes de procesar").
   c. UI: combobox "Empresa:" ARRIBA de EMITIDAS/RECIBIDAS, con las llaves de `empresas`
      + "➕ Nueva empresa…". Configuración (⚙️) edita SIEMPRE la empresa activa, mostrando
      su nombre para evitar editar la cuenta de un cliente pensando que es otro.
   d. Al pulsar EMITIDAS/RECIBIDAS: el diálogo abre directo en
      `<boveda_de_la_activa>\Emitidas|Recibidas\` — se acaba la cacería de carpetas.
   e. Doble candado tras parsear: TODOS los XML del lote deben pertenecer al RFC activo
      (emisor en emitidas, receptor en recibidas). Si hay ajenos o mezcla → ABORTAR
      listando los RFCs encontrados; no se genera NADA.
   f. **Editor de configuración de la empresa (botón en la UI) — MUST, prometido al dueño
      desde hace tiempo y omitido en versiones anteriores de este doc.** Dentro de
      ⚙️ Configuración, sección "Cuentas de la empresa activa": campos editables para TODAS
      las `cuentas_default` (bancos, ventas, clientes, clientes_extranjero, iva_acreditable,
      gastos_generales, ret_isr_honorarios, ret_iva, ret_isr_nomina, ieps_acreditable).
      Junto a cada campo, mostrar el NOMBRE de la cuenta buscándola en el catálogo (confirma
      visualmente que 10201001 es "BBVA" y no otra cosa) y validar que exista y sea
      afectable. Incluir un texto explicativo EN la ventana y en el README: "Aquí se dan de
      alta las cuentas por default de cada empresa. Son el esqueleto de toda póliza (bancos,
      IVA, ventas, retenciones…). NO desaparecen cuando el ML aprende: el ML solo predice la
      cuenta de GASTO; el resto siempre sale de aquí." (Ver §2.3.)
   **Checkpoint:** arrancar con el `settings.json` actual del dueño → migra a
   `empresas.EEA251205CR8` sin perder nada; dar de alta un RFC de prueba → queda vacío y
   la app avisa antes de dejarlo procesar; con empresa A activa, elegir carpeta de empresa
   B → aborta con aviso claro; carpeta mixta → aborta; editar una cuenta default desde la
   UI (sin tocar el JSON a mano) se refleja en la siguiente corrida.
3. Cancelados (§7-Q2): filtrarlos ANTES de pólizas y DIOT; conteo visible en el Log y en la
   hoja RESUMEN ("Cancelados excluidos: N"); dejarlos visibles en la hoja BASE con su estatus
   para que el dueño los pueda revisar (excluir del asiento ≠ ocultar la evidencia).
   **Checkpoint:** lote con 1 cancelado → no aparece en POLIZAS_CONTPAQI ni en DIOT, y el
   RESUMEN lo cuenta.

### Fase 3
1. Reagrupar la barra (solo `Label`s y orden de `pack()`; NO tocar comandos).
   **Checkpoint visual:** "Inteligencia Artificial" tiene UN botón; "Catálogos" tiene el otro.
2. `pip install customtkinter` (agregarlo a requirements). Migrar pantalla por pantalla:
   ventana principal → Configuración → Clientes/Proveedores. En cada una: `Tk→CTk`,
   `Button→CTkButton`, `Frame→CTkFrame`, `Label→CTkLabel`, conservando textos y comandos.
   `Treeview` no tiene equivalente CTk: se queda ttk y se le da estilo acorde.
   **Checkpoint por pantalla:** misma funcionalidad, sin errores en consola.
3. Toggle de apariencia (menú o botón): Light/Dark/System; default `System`; guardar la
   elección en settings (`"tema": "system"`). Definir el tema de color con los tintes
   suavizados (JSON de tema customtkinter).
   **Checkpoint:** con Windows en oscuro la app abre oscura; cambiar a Light re-pinta TODO
   (buscar widgets olvidados); contraste legible en ambos modos.

### Fase 4
1. Crear `pipeline.py`: mover el cuerpo de `process_folder` con firma
   `procesar_carpeta(carpeta, tipo, config, log)` — `log` es un callback (la UI le pasa el
   suyo); PROHIBIDO importar tkinter ahí; los `messagebox` se quedan en `main.py`.
2. `main.py::process_folder` queda como envoltorio delgado que llama al pipeline.
   **Checkpoint:** la UI se comporta idéntica a antes del refactor (mismo lote → mismos
   archivos, diff limpio contra salidas previas).
3. `tests/` con XMLs de muestra (anonimizados) + pruebas: PPD+REP cuadran; retención cuadra;
   DIOT omite tercero sin IVA y reporta TME en col 12/31/54; layout del TXT pasa
   `validar_layout`.
   **Checkpoint:** `pytest` verde; correr el pipeline desde un script SIN abrir ventana.

---

## 11. RECORDATORIOS FINALES PARA EL EJECUTOR

- `ROADMAP.md` contiene decisiones fiscales CERRADAS (DIOT excluye contribuciones de
  gobierno; clientes con cuenta por RFC + fallback 10501999; nómina la hace CONTPAQi Nóminas
  salvo toggle; retenciones configurables; etc.). No las reabras.
- La app se está usando EN PRODUCCIÓN con datos fiscales reales de clientes del dueño. Ante
  la duda entre "mejorar" y "no romper": **no romper**.
- El dueño quiere pushback honesto, no validación refleja — pero también quiere acordar antes
  de que toques cualquier cosa. Propón, espera el sí, ejecuta, prueba, muestra.
