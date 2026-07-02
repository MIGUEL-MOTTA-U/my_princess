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
