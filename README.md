# my_princess

Agente de IA que automatiza la documentalización de videos proxy (`.mp4`)
para una empresa de televisión y noticias: detección en watchfolder →
transcripción → metadata estructurada vía LLM → asset listo para
validación humana, con trazabilidad completa de cada etapa.

## Arquitectura

```
watchfolder/  ──▶ Watcher (polling, tamaño estable, .mp4)
                    │  asset DETECTED en SQLite
                    ▼
              Grafo LangGraph:  dedupe → transcribe → structure → write_output
                    │             │          │            │
                    │         DUPLICATE   FAILED     NEEDS_REVIEW
                    ▼
              output/{id_asset}.json  +  estado PENDING_VALIDATION
```

- **Orquestación**: LangGraph (`src/my_princess/graph.py`, diagrama en `docs/graph.md`)
- **Transcripción**: faster-whisper (modelo configurable, default `base`)
- **Audio**: ffmpeg (PATH o binario empaquetado de `imageio-ffmpeg`)
- **Persistencia**: SQLite (`assets` + `transform_logs`); ver `DECISIONS.md`
- **LLM**: Anthropic por defecto, detrás de una interfaz intercambiable
- **Bitácora**: `ai_notes.md` (una entrada por evento) + `transform_logs`

## Requisitos

- Python 3.11+ (probado con 3.12)
- API key de Anthropic (`ANTHROPIC_API_KEY`) para la estructuración de metadata
- Nada más: ffmpeg viene empaquetado y SQLite es parte de Python

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Requerida para la llamada real al LLM |
| `MP_WATCH_DIR` | `watchfolder` | Carpeta vigilada |
| `MP_OUTPUT_DIR` | `output` | Carpeta de archivos de salida |
| `MP_DB_PATH` | `data/my_princess.db` | Base SQLite |
| `MP_AI_NOTES_PATH` | `ai_notes.md` | Bitácora legible |
| `MP_POLL_INTERVAL_SECONDS` | `2` | Intervalo de polling |
| `MP_MAX_RETRIES` | `3` | Reintentos por etapa antes de FAILED |
| `MP_WHISPER_MODEL` | `base` | Modelo faster-whisper (`tiny`/`base`/`small`…) |
| `MP_LLM_PROVIDER` | `anthropic` | Proveedor LLM |
| `MP_LLM_MODEL` | `claude-opus-4-8` | Modelo LLM |

## Ejecutar la demo

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m my_princess.main
```

Copia un `.mp4` en `watchfolder/`. En pocos segundos verás:

1. El asset en la base con estado `DETECTED` (y su transición en `transform_logs`).
2. El pipeline avanzando hasta `PENDING_VALIDATION` (o `FAILED`/`NEEDS_REVIEW`
   si algo falla, sin tumbar el proceso).
3. `output/{id_asset}.json` con transcripción completa + metadata validada.
4. `ai_notes.md` con el historial legible.

Para inspeccionar la base:

```powershell
python -c "import sqlite3; [print(dict(r)) for r in sqlite3.connect('data/my_princess.db').execute('SELECT id_asset,status,title FROM assets').fetchall()]"
```

`python -m my_princess.main --cycles 5` ejecuta 5 ciclos de escaneo y termina.

## Tests y cobertura

La suite mockea faster-whisper y el LLM (sin llamadas reales ni descarga de
modelos); ffmpeg sí se ejercita con un mp4 sintético generado al vuelo.

```powershell
python -m pytest --cov --cov-report=term-missing
```

Cobertura actual: **98%** (requisito: ≥85%). Incluye un test de integración
end-to-end (`tests/test_e2e.py`) que recorre el flujo completo desde el
watchfolder hasta el archivo de salida.

## Estructura

```
src/my_princess/
  config.py       # settings por variables de entorno
  models.py       # AssetStatus/AssetCategory (Enum) + contrato AssetMetadata
  db.py           # SQLite: assets, transform_logs, log de transiciones
  notes.py        # escritor de ai_notes.md
  watcher.py      # polling + estabilidad + SHA-256
  audio.py        # extracción de audio (ffmpeg)
  transcriber.py  # wrapper faster-whisper (carga perezosa)
  llm.py          # estructuración de metadata, agnóstico al proveedor
  output.py       # JSON de salida por asset
  graph.py        # grafo LangGraph
  main.py         # loop de polling (CLI)
tests/            # unitarios por módulo + e2e
docs/graph.md     # diagrama y documentación del grafo
DECISIONS.md      # decisiones técnicas justificadas
ai_notes.md       # bitácora de implementación + eventos de runtime
```
