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
- **LLM**: agnóstico al proveedor vía LiteLLM (Gemini, OpenAI, Anthropic, Ollama…)
- **Bitácora**: `ai_notes.md` (una entrada por evento) + `transform_logs`

## Requisitos

- Python 3.11+ (probado con 3.12)
- Una API key del proveedor LLM elegido (Gemini por defecto: `GEMINI_API_KEY`);
  con Ollama local no se necesita key
- Nada más: ffmpeg viene empaquetado y SQLite es parte de Python

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuración

Toda la configuración es por variables de entorno. La forma recomendada es
un archivo `.env` en la raíz del proyecto (se carga automáticamente al
arrancar; está en `.gitignore`, así que las keys no se commitean):

```powershell
Copy-Item .env.example .env    # Linux/macOS: cp .env.example .env
# edita .env y pon tu API key
```

Las variables ya exportadas en la shell tienen prioridad sobre `.env`.

| Variable | Default | Descripción |
|---|---|---|
| `MP_WATCH_DIR` | `watchfolder` | Carpeta vigilada |
| `MP_OUTPUT_DIR` | `output` | Carpeta de archivos de salida |
| `MP_DB_PATH` | `data/my_princess.db` | Base SQLite |
| `MP_AI_NOTES_PATH` | `ai_notes.md` | Bitácora legible |
| `MP_POLL_INTERVAL_SECONDS` | `2` | Intervalo de polling |
| `MP_MAX_RETRIES` | `3` | Reintentos por etapa antes de FAILED |
| `MP_WHISPER_MODEL` | `base` | Modelo faster-whisper (`tiny`/`base`/`small`…) |
| `MP_LLM_PROVIDER` | `gemini` | Proveedor LLM (cualquiera soportado por LiteLLM) |
| `MP_LLM_MODEL` | `gemini-2.5-flash` | Modelo del proveedor |
| `MP_LLM_API_BASE` | — | Endpoint custom (p. ej. Ollama en otro host) |

La API key va en la variable estándar de cada proveedor:

| Proveedor (`MP_LLM_PROVIDER`) | Key | Ejemplo de `MP_LLM_MODEL` |
|---|---|---|
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-4-8` |
| `ollama` | no necesita | `llama3.1` (local en `:11434`) |

`MP_LLM_PROVIDER` acepta cualquier proveedor soportado por LiteLLM
(Groq, Mistral, Azure…), no solo los de la tabla.

## Ejecutar la demo

```powershell
# .env con GEMINI_API_KEY ya configurado (ver sección Configuración)
python -m my_princess.main
```

Para cambiar de proveedor basta con editar el `.env`, sin tocar código:

```dotenv
MP_LLM_PROVIDER=ollama
MP_LLM_MODEL=llama3.1
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
