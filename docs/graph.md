# Grafo de orquestación (LangGraph)

Implementado en `src/my_princess/graph.py` como un `StateGraph` cuyo estado
es `{asset_id, final_status?}`. Todo el estado "pesado" (transcripción,
metadata, contadores) vive en la base de datos, no en el grafo: cada nodo
lee y persiste vía `Database`, lo que mantiene el flujo auditable y
reanudable.

## Nodos y transiciones

```
                 ┌─────────┐
   (watcher) ───▶│ dedupe  │── duplicado ─────────────▶ END  [DUPLICATE]
                 └────┬────┘── archivo ilegible ──────▶ END  [FAILED]
                      │
                 ┌────▼───────┐
                 │ transcribe │── agota reintentos ───▶ END  [FAILED]
                 └────┬───────┘   DETECTED → TRANSCRIBING → TRANSCRIBED
                      │
                 ┌────▼──────┐
                 │ structure │── schema inválido ─────▶ END  [NEEDS_REVIEW]
                 └────┬──────┘── transporte agotado ──▶ END  [FAILED]
                      │           TRANSCRIBED → STRUCTURING
                 ┌────▼─────────┐
                 │ write_output │──────────────────────▶ END  [PENDING_VALIDATION]
                 └──────────────┘
```

| Nodo | Responsabilidad | Transiciones que registra |
|---|---|---|
| `dedupe` | SHA-256 del archivo; detecta contenido/ruta ya procesados | `DETECTED → DUPLICATE` o `DETECTED → FAILED` |
| `transcribe` | ffmpeg → WAV 16 kHz mono → faster-whisper, con reintentos | `DETECTED → TRANSCRIBING → TRANSCRIBED` o `→ FAILED` |
| `structure` | LLM + validación pydantic + reintento de corrección | `TRANSCRIBED → STRUCTURING`, luego `→ NEEDS_REVIEW` o `→ FAILED` |
| `write_output` | JSON por asset en la carpeta de salida | `STRUCTURING → PENDING_VALIDATION` |

Las aristas condicionales usan una sola regla: si el nodo dejó
`final_status` en el estado, el flujo termina; si no, continúa al
siguiente nodo.

## Trazabilidad

Cada transición produce:
1. una fila en `transform_logs` (`stage`, `status_from`, `status_to`,
   `duration_ms`, `error_detail`),
2. una entrada en `ai_notes.md` legible por humanos.

`process_asset` envuelve la invocación del grafo: cualquier excepción no
prevista marca el asset `FAILED` con `error_code=UNHANDLED_ERROR` y el
loop de polling sigue con el siguiente archivo.
