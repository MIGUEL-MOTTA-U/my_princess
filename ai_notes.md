# AI Notes — my_princess

Bitácora del agente. Las primeras entradas documentan las decisiones tomadas
durante la implementación (una por fase); a partir del arranque del pipeline,
cada evento de runtime (detección, transiciones, errores) se añade aquí
automáticamente con el mismo formato.

## 2026-07-02T00:00:00Z — implementación / fase 0 (plan)
- Entorno verificado: Python 3.12.5, sin Docker, sin ffmpeg en PATH.
- Decisión: SQLite en lugar de MongoDB (no hay Docker; ver DECISIONS.md).
- Decisión: ffmpeg empaquetado vía `imageio-ffmpeg` con fallback a PATH.
- Decisión: salida en JSON; LLM Anthropic tras interfaz intercambiable.

## 2026-07-02T00:00:00Z — implementación / fase 1 (persistencia)
- Tablas `assets` y `transform_logs` en SQLite; `tags`/`staff` como JSON.
- `AssetStatus`/`AssetCategory` como `Enum`; contrato del LLM como modelo
  pydantic (`AssetMetadata`) con las restricciones del schema (título ≤120,
  3–10 tags, confidence en [0,1]).
- 19 tests unitarios en verde.

## 2026-07-02T00:00:00Z — implementación / fase 2 (detección)
- Polling con tamaño estable entre dos escaneos (evita archivos en copia).
- Solo `.mp4`; rutas ya registradas no se re-registran; pendientes que
  desaparecen del folder se olvidan. SHA-256 para dedup posterior.
- 7 tests en verde.

## 2026-07-02T00:00:00Z — implementación / fase 3 (audio + transcripción)
- Extracción a WAV mono 16 kHz. Error de ffmpeg → `AudioExtractionError`.
- faster-whisper con import/carga perezosa: los tests no descargan pesos.
- Los tests generan un mp4 sintético real (tono 440 Hz) con el ffmpeg
  empaquetado; 5 tests en verde.

## 2026-07-02T00:00:00Z — implementación / fase 4 (estructuración LLM)
- Prompt documenta el cálculo de `confidence_score` (longitud/integridad,
  ambigüedad, nombres dudosos, ruido) para que no sea arbitrario.
- Parseo tolerante a fences markdown; validación pydantic; un reintento de
  corrección con el error; luego `NEEDS_REVIEW`.
- Distinción transporte (reintenta → FAILED) vs schema (→ NEEDS_REVIEW).
- 8 tests en verde con cliente falso.

## 2026-07-02T00:00:00Z — implementación / fase 5 (orquestación)
- Grafo LangGraph `dedupe → transcribe → structure → write_output` con
  salidas condicionales a DUPLICATE/FAILED/NEEDS_REVIEW (docs/graph.md).
- Estado del grafo mínimo (`asset_id`); el estado real vive en la base.
- `process_asset` captura toda excepción residual: un archivo malo nunca
  tumba el loop. 8 tests en verde.

## 2026-07-02T00:00:00Z — implementación / fase 6 (e2e + cobertura)
- Test end-to-end: mp4 sintético en watchfolder → `run()` completo →
  PENDING_VALIDATION + JSON de salida + logs por transición.
- Suite completa: 48 tests, cobertura 98% (objetivo ≥85%). Únicas líneas
  excluidas: carga real del modelo whisper y llamada real a Anthropic.

## 2026-07-02T00:00:00Z — implementación / fase 7 (LLM multi-proveedor)
- Requisito nuevo: el LLM debe ser agnóstico al proveedor (Gemini, Ollama,
  OpenAI, Anthropic...). Se reemplazó el cliente Anthropic directo por
  `LiteLLMClient` (librería LiteLLM, interfaz única multi-proveedor).
- Proveedor/modelo por configuración: `MP_LLM_PROVIDER` + `MP_LLM_MODEL`
  (default: gemini / gemini-2.5-flash) + `MP_LLM_API_BASE` opcional para
  endpoints custom (Ollama remoto). Sin whitelist de proveedores.
- El prompt, el parseo y la validación no cambiaron: ya eran agnósticos.
- Suite: 57 tests, cobertura 99%.

## 2026-07-02T00:00:00Z — implementación / fase 8 (.env)
- `.env.example` con todas las variables documentadas; `python-dotenv`
  carga `.env` en el arranque del CLI (las variables ya exportadas en la
  shell tienen prioridad). `.env` ya estaba cubierto por .gitignore.

## 2026-07-02T00:00:00Z — implementación / fase 9 (respuesta a AUDITORIA.md)
- SEC-001 verificado: `.env` NUNCA fue commiteado (historial de git vacío
  para esa ruta); solo `.env.example`, sin secretos. No hay key expuesta
  y no se requiere revocación.
- Aplicados (bajo costo, sin cambiar flujo ni alcance): whitelist de
  columnas en `update_asset` (DB-001/CODE-002) + test; borrado del WAV
  intermedio tras transcripción exitosa (DISC-001); lambda a `def` y
  `add_edge(START, ...)` en el grafo (CODE-001 + compatibilidad LangGraph,
  pin `>=1,<2`); aserción explícita en test_watcher (TEST-001); nota de
  VC++ Redistributable y tabla de error_codes en README (DOC-001/DOC-002);
  `requirements.txt` congelado con pip freeze (DEP-001).
- Descartados por alcance de demo: pool de conexiones y concurrencia,
  tipos de dominio en db.py, validación de rangos en Settings, rotación
  de ai_notes, device GPU configurable.
- CODE-003 revisado y sin cambio: tras `dedupe` el asset sigue en
  DETECTED (el nodo no cambia estado si no hay duplicado), así que
  DETECTED a TRANSCRIBING es la transición real.
- CFG-001 sin cambio: el `.env` del usuario solo necesita la key; el
  resto opera por defaults documentados en `.env.example`.
- Suite: 58 tests, cobertura 99%.
