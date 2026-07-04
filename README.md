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
- **Persistencia**: MongoDB (colecciones `assets` + `transform_logs`) vía
  Docker Compose; los tests usan `mongomock` (sin servidor). Ver `DECISIONS.md`
- **LLM**: agnóstico al proveedor vía LiteLLM (Gemini, OpenAI, Anthropic, Ollama…)
- **Bitácora**: `ai_notes.md` (una entrada por evento) + `transform_logs`

## Requisitos

- Python 3.11+ (probado con 3.12)
- Docker (para MongoDB vía `docker-compose.yml`)
- Una API key del proveedor LLM elegido (Gemini por defecto: `GEMINI_API_KEY`);
  con Ollama local no se necesita key
- En Windows: [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
  (lo requiere `ctranslate2`, el motor de faster-whisper; suele estar ya instalado)
- Nada más: ffmpeg viene empaquetado

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

`pyproject.toml` es la fuente de verdad de las dependencias;
`requirements.txt` es un snapshot congelado (`pip freeze`) para
instalaciones reproducibles: `pip install -r requirements.txt`.

Levanta MongoDB antes de ejecutar el pipeline:

```powershell
docker compose up -d      # Mongo 7 en localhost:27017 (volumen persistente)
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
| `MP_MONGO_URI` | `mongodb://localhost:27017` | URI de MongoDB |
| `MP_MONGO_DB` | `my_princess` | Nombre de la base de datos |
| `MP_WATCH_DIR` | `watchfolder` | Carpeta vigilada |
| `MP_OUTPUT_DIR` | `output` | Salida estándar (revisión manual completa) |
| `MP_APPROVED_DIR` | `approved` | Salida cuando el agente aprueba por confianza |
| `MP_CONFIDENCE_THRESHOLD` | `0.8` | Umbral de triage **inicial**; en runtime se cambia vía `PUT /api/v1/config` (el valor dinámico tiene prioridad) |
| `MP_WORK_DIR` | `data` | Directorio de trabajo (WAV temporales) |
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
3. El archivo `{id_asset}.json` con transcripción completa + metadata validada,
   enrutado por el **triage del agente** según la confianza de la metadata:
   - `confidence_score >= MP_CONFIDENCE_THRESHOLD` → `approved/` (cola priorizada)
   - por debajo del umbral → `output/` (revisión manual completa)
   En ambos casos el estado es `PENDING_VALIDATION` (la aprobación final es
   humana) y la decisión queda auditada en `validation_notes` y `ai_notes.md`.
4. `ai_notes.md` con el historial legible.

Para inspeccionar la base:

```powershell
# assets
python -c "from pymongo import MongoClient; [print(a['id_asset'], a['status'], a.get('title')) for a in MongoClient()['my_princess']['assets'].find({}, {'_id':0})]"
# transform_logs
python -c "from pymongo import MongoClient; [print(l['stage'], l['status_from'], '->', l['status_to']) for l in MongoClient()['my_princess']['transform_logs'].find({}, {'_id':0}).sort('processing_date',1)]"
# o con mongosh dentro del contenedor:
docker exec my_princess_mongo mongosh my_princess --quiet --eval "db.assets.find({}, {_id:0, id_asset:1, status:1, title:1})"
```

`python -m my_princess.main --cycles 5` ejecuta 5 ciclos de escaneo y termina.

## API para el frontend

La capa REST expone el pipeline a clientes de UI (carga de archivos,
consulta de estados, trazabilidad y configuración del agente). Corre como
proceso aparte del pipeline, compartiendo el mismo MongoDB y las carpetas:

```powershell
# terminal 1: pipeline           # terminal 2: API
python -m my_princess.main       uvicorn my_princess.api.app:create_app --factory --port 8000
```

**Documentación automática para el cliente front**: Swagger UI en
[`http://localhost:8000/docs`](http://localhost:8000/docs) (interactiva) y
ReDoc en `/redoc`; el schema OpenAPI está en `/openapi.json`.

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/api/v1/videos` | Sube un `.mp4` al watchfolder (multipart). `400` si no es mp4, `409` si el nombre ya existe |
| `GET` | `/api/v1/assets` | Lista paginada de assets; filtro `?status=` (enum del pipeline) |
| `GET` | `/api/v1/assets/{id}` | Detalle completo: transcripción, metadata, `validation_notes` |
| `GET` | `/api/v1/assets/{id}/logs` | Trazabilidad del asset (transiciones de `transform_logs`) |
| `GET` | `/api/v1/logs` | Feed global de trazabilidad, más reciente primero |
| `GET` | `/api/v1/outputs/{folder}` | Archivos en `output/` o `approved/` (folder = `output` \| `approved`) |
| `GET` | `/api/v1/outputs/{folder}/{id}` | Contenido JSON de la salida de un asset |
| `GET` | `/api/v1/config` | Configuración actual del agente (umbral + origen) |
| `PUT` | `/api/v1/config` | Cambia el umbral de confianza **en caliente** (0–1); el pipeline lo aplica en el siguiente asset |
| `GET` | `/api/v1/health` | Estado del servicio y de la base |

Todas las listas usan el mismo envoltorio de paginación:
`{items, page, size, total_items, total_pages}` con `?page=` (1-based) y
`?size=` (máx. 100). CORS está abierto para desarrollo del front.

## Códigos de error (`assets.error_code`)

| Código | Etapa | Significado |
|---|---|---|
| `FILE_ACCESS_ERROR` | dedupe | El archivo no se pudo leer para calcular su hash |
| `TRANSCRIPTION_ERROR: <tipo>` | transcription | Falló ffmpeg o faster-whisper (se reintenta hasta `MP_MAX_RETRIES`) |
| `LLM_TRANSPORT_ERROR: <tipo>` | structuring | Error de red/API del proveedor LLM (se reintenta) |
| `LLM_SCHEMA_VALIDATION_FAILED: <detalle>` | structuring | La respuesta del LLM no validó contra el schema tras el reintento de corrección → `NEEDS_REVIEW` |
| `UNHANDLED_ERROR: <tipo>` | pipeline | Excepción no prevista; el asset queda `FAILED` sin tumbar el loop |

## Tests y cobertura

La suite mockea faster-whisper y el LLM (sin llamadas reales ni descarga de
modelos) y usa `mongomock` como base Mongo en memoria (no requiere Docker);
ffmpeg sí se ejercita con un mp4 sintético generado al vuelo.

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
  db.py           # MongoDB: assets, transform_logs, log de transiciones
  notes.py        # escritor de ai_notes.md
  watcher.py      # polling + estabilidad + SHA-256
  audio.py        # extracción de audio (ffmpeg)
  transcriber.py  # wrapper faster-whisper (carga perezosa)
  llm.py          # estructuración de metadata, agnóstico al proveedor
  output.py       # JSON de salida por asset
  graph.py        # grafo LangGraph
  main.py         # loop de polling (CLI)
  api/            # capa REST para el front (FastAPI)
    app.py          #   composition root (create_app)
    controllers.py  #   routers HTTP (verbos, códigos, validación)
    services.py     #   lógica de aplicación (paginación, archivos, config)
    repositories.py #   patrón repository sobre Database
    schemas.py      #   contratos pydantic → OpenAPI
tests/            # unitarios por módulo + e2e
docs/graph.md     # diagrama y documentación del grafo
DECISIONS.md      # decisiones técnicas justificadas
ai_notes.md       # bitácora de implementación + eventos de runtime
```
