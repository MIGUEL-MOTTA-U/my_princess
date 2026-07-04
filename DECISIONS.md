# DECISIONS.md — decisiones técnicas y justificación

## Persistencia: MongoDB (migrado desde SQLite)
La elección inicial fue SQLite porque Docker no estaba disponible en la
máquina de la demo. Cuando Docker quedó operativo se migró a **MongoDB**
(la opción preferida del enunciado), levantado con `docker-compose.yml`
(imagen `mongo:7`, volumen persistente). La migración confirmó la apuesta
de diseño original: la interfaz `Database` era el único punto de contacto,
así que solo se reescribió `db.py` — el grafo, el watcher y los tests de
las demás capas no cambiaron.
- Colecciones `assets` y `transform_logs` con índices en `id_asset`
  (único), `source_path`, `file_hash` y `asset_id`.
- `tags`/`staff` ahora son arrays nativos (antes JSON serializado); las
  fechas siguen siendo strings ISO-8601 para mantener el contrato.
- Conexión configurable con `MP_MONGO_URI` / `MP_MONGO_DB`; Mongo local de
  la demo corre sin autenticación (documentado: producción requiere auth).
- Tests con `mongomock` (base en memoria, sin servidor): la suite corre
  sin Docker y sigue la regla de no depender de servicios reales.

## ffmpeg: binario empaquetado (`imageio-ffmpeg`) con fallback a PATH
ffmpeg no estaba en el PATH del entorno. En lugar de exigir instalación
manual, `audio.py` resuelve primero `ffmpeg` del PATH y, si no existe, usa
el binario que trae el paquete `imageio-ffmpeg`. La demo corre con
`pip install` y nada más.

## Detección: polling con tamaño estable, sin watchdog/inotify
Polling con intervalo configurable (`MP_POLL_INTERVAL_SECONDS`, default 2 s)
es portable (Windows/Linux/NAS montados por red, donde inotify no funciona),
trivial de testear y suficiente para el volumen de una demo. Un archivo se
registra solo cuando su tamaño no cambió entre dos escaneos consecutivos,
para no ingerir archivos aún en copia.

## Deduplicación: SHA-256 + source_path
- El watcher no re-registra un `source_path` que ya tiene asset (idempotencia
  del polling).
- El nodo `dedupe` del grafo calcula el SHA-256 del archivo y marca
  `DUPLICATE` si **otro** asset ya tiene el mismo hash (copia del mismo
  contenido con otro nombre) o el mismo `source_path`.

## LLM: agnóstico al proveedor vía LiteLLM
Requisito explícito: el modelo debe poder ser de Gemini, Ollama, OpenAI,
Anthropic, etc. En lugar de escribir un cliente por proveedor se usa
**LiteLLM**, una librería probada que expone la misma interfaz sobre ~100
proveedores; `build_llm_client` compone el identificador
`{MP_LLM_PROVIDER}/{MP_LLM_MODEL}` sin whitelist (cualquier proveedor que
LiteLLM soporte funciona) y la API key se toma de la variable estándar de
cada proveedor (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`;
Ollama no usa key y admite endpoint custom vía `MP_LLM_API_BASE`).
El default es Gemini (`gemini-2.5-flash`), el proveedor con el que se
prueba la demo. El contrato con el resto del sistema sigue siendo el
protocolo `LLMClient` (`complete(system, user) -> str`):
- el prompt pide JSON puro y documenta el criterio de `confidence_score`
  (longitud/integridad de la transcripción, ambigüedad temática,
  confiabilidad de nombres propios, ruido);
- el parseo tolera fences de markdown y valida con **pydantic** contra el
  schema estricto;
- si no valida, se reintenta **una vez** con un prompt de corrección que
  incluye el error; si vuelve a fallar → `NEEDS_REVIEW`.
Cambiar de proveedor = cambiar dos variables de entorno, sin tocar código.
Los tests usan un cliente falso (dos implementaciones reales del
protocolo: la de LiteLLM y la fake, lo que justifica la interfaz).

## Errores: transporte ≠ schema
Un error de red/API en la estructuración es transitorio → se reintenta
hasta `MP_MAX_RETRIES` (default 3) y luego `FAILED`. Una respuesta que no
valida contra el schema no es transitoria (reintentarla igual suele
devolver lo mismo) → `NEEDS_REVIEW` tras el único reintento de corrección.
La transcripción reintenta hasta `MP_MAX_RETRIES` incrementando
`retry_count` y termina en `FAILED`. `process_asset` captura cualquier
excepción residual y marca `FAILED`: un archivo corrupto nunca tumba el
loop de polling.

## Archivo de salida: JSON
JSON en vez de Markdown porque el consumidor natural es el MAM u otro
sistema downstream (y un humano puede leerlo igual). Un archivo
`{id_asset}.json` por asset en `MP_OUTPUT_DIR` (default `output/`), con
transcripción completa + metadata estructurada.

## Reintentos dentro del nodo, no como ciclos del grafo
LangGraph permite modelar reintentos como aristas de vuelta al mismo nodo,
pero eso complica el estado sin beneficio: el loop `for attempt in range()`
dentro del nodo es más simple, mantiene el grafo legible y `retry_count`
queda persistido igual.

## Tests: mocks para modelos, ffmpeg real
faster-whisper y el LLM se mockean en toda la suite (requisito de
cobertura sin llamadas reales). ffmpeg sí se ejercita de verdad: los tests
generan un mp4 sintético (tono de 440 Hz + video negro) con el binario
empaquetado, de modo que la extracción de audio se prueba end-to-end.
La carga real del modelo whisper y la llamada real a Anthropic quedan
excluidas de cobertura (`pragma: no cover`), son las únicas líneas no
ejercitadas. Cobertura actual: **98%**.

## Triage automático por confianza: carpeta, no estado
El agente decide la ruta de salida según `confidence_score` contra
`MP_CONFIDENCE_THRESHOLD` (default 0.8): a `MP_APPROVED_DIR` si lo supera,
a `MP_OUTPUT_DIR` si no. Se decidió **no** introducir un estado nuevo
(p. ej. `AUTO_APPROVED`) para no alterar la máquina de estados existente:
la aprobación final sigue siendo humana (`PENDING_VALIDATION` en ambos
casos) y el triage solo prioriza la cola. La decisión queda auditada en
`validation_notes`, `transform_logs` y `ai_notes.md`.

## Sin infraestructura extra
Sin colas, sin microservicios, sin contenedores: un proceso, un loop de
polling, una base SQLite. Es lo que la demo necesita y lo más fácil de
extender después.
