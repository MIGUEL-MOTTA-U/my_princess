# Auditoría Técnica — `my_princess`
**Fecha:** 2026-07-02 | **Auditor:** Antigravity (Senior Software Engineer Review)  
**Versión del proyecto:** 0.1.0 | **Repositorio:** `S10/my_princess`

---

## 1. Guía paso a paso para probar el proyecto

### Prerrequisitos verificables

| Requisito | Cómo verificar |
|---|---|
| Python 3.11+ | `python --version` |
| pip actualizado | `python -m pip --version` |
| git | `git --version` |
| API key de Gemini (o Ollama local) | Tener `GEMINI_API_KEY` disponible |
| ~500 MB disco libre | Para el modelo faster-whisper `base` (~145 MB) y dependencias |

> [!IMPORTANT]
> **ffmpeg NO necesita estar instalado manualmente.** El paquete `imageio-ffmpeg` lo provee automáticamente. Solo necesitas Python y pip.

---

### PASO 1 — Ubicarse en la raíz del proyecto

```powershell
cd "C:\Users\migue_7m\Desktop\Documentos Miguel\Universidad\S10\my_princess"
ls   # Debe mostrar: README.md, pyproject.toml, src/, tests/, .env.example
```

---

### PASO 2 — Crear y activar el entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> [!NOTE]
> Si PowerShell bloquea scripts, ejecuta primero:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

Verificar:
```powershell
python --version   # Debe mostrar 3.11.x o superior
where python       # Debe apuntar a .venv\Scripts\python.exe
```

---

### PASO 3 — Instalar dependencias

```powershell
pip install -e ".[dev]"
```

Instala: `langgraph`, `pydantic`, `litellm`, `python-dotenv`, `imageio-ffmpeg`, `faster-whisper`, `pytest`, `pytest-cov`.

Tiempo estimado: **2-5 minutos** (incluye PyTorch para faster-whisper).

Verificar:
```powershell
pip show my-princess
python -c "import my_princess; print('OK')"
```

---

### PASO 4 — Configurar variables de entorno

```powershell
Copy-Item .env.example .env
notepad .env
```

Contenido mínimo del `.env`:
```dotenv
GEMINI_API_KEY=<tu_key_aqui>
MP_LLM_PROVIDER=gemini
MP_LLM_MODEL=gemini-2.5-flash
MP_WATCH_DIR=watchfolder
MP_OUTPUT_DIR=output
MP_DB_PATH=data/my_princess.db
MP_AI_NOTES_PATH=ai_notes.md
MP_POLL_INTERVAL_SECONDS=2
MP_MAX_RETRIES=3
MP_WHISPER_MODEL=base
```

> [!WARNING]
> El `.env` actual solo contiene `GEMINI_API_KEY` pero faltan las demás variables. Funciona por los defaults del código, pero es inconsistente con `.env.example`.

---

### PASO 5 — Ejecutar la suite de tests (sin API real, sin modelos)

```powershell
python -m pytest --cov --cov-report=term-missing
```

**Resultado esperado:**
```
tests/test_audio_transcriber.py  .....
tests/test_db.py                 .........
tests/test_e2e.py                .
tests/test_graph.py              .........
tests/test_llm.py                ..............
tests/test_models_notes.py       .....
tests/test_watcher.py            .......
TOTAL coverage: 98%
```

> [!NOTE]
> El test E2E usa ffmpeg real para generar un `.mp4` sintético de 1 segundo. Whisper y LLM están mockeados. No requiere API key ni modelos descargados.

Tests por categoría:
```powershell
# Solo unitarios (sin E2E)
python -m pytest tests/ -k "not e2e" --cov --cov-report=term-missing

# Solo E2E
python -m pytest tests/test_e2e.py -v

# Un módulo específico
python -m pytest tests/test_graph.py -v
```

---

### PASO 6 — Demo funcional completa (con API real)

```powershell
# Loop controlado de N ciclos
python -m my_princess.main --cycles 10
```

En otra terminal (entorno activo):
```powershell
# Copiar un .mp4 real al watchfolder
Copy-Item "C:\ruta\a\tu\video.mp4" "watchfolder\"
```

**Flujo observable:**
1. **Ciclo 1:** Watcher detecta el archivo, registra su tamaño (no lo procesa aún).
2. **Ciclo 2:** Tamaño estable → asset registrado como `DETECTED`.
3. **Ciclos 3+:** Pipeline: dedupe → transcribe → structure → write_output.
4. **Salida en consola:** `[<uuid>] -> PENDING_VALIDATION`

**Artefactos generados:**

| Artefacto | Ruta | Contenido |
|---|---|---|
| JSON de salida | `output/<uuid>.json` | Transcripción + metadata validada |
| Base SQLite | `data/my_princess.db` | Estado del asset + transform_logs |
| Bitácora | `ai_notes.md` | Historial legible por humanos |

---

### PASO 7 — Inspeccionar resultados

```powershell
# Estado de todos los assets
python -c "import sqlite3; conn = sqlite3.connect('data/my_princess.db'); conn.row_factory = sqlite3.Row; [print(dict(r)) for r in conn.execute('SELECT id_asset,status,title,confidence_score FROM assets').fetchall()]; conn.close()"

# Ver el JSON de salida
python -c "import json,pathlib; out=list(pathlib.Path('output').glob('*.json')); print(json.dumps(json.loads(out[0].read_text(encoding='utf-8')),indent=2,ensure_ascii=False)) if out else print('Sin output')"

# Logs de transiciones
python -c "import sqlite3; conn = sqlite3.connect('data/my_princess.db'); conn.row_factory = sqlite3.Row; [print(dict(r)) for r in conn.execute('SELECT stage,status_from,status_to,duration_ms FROM transform_logs ORDER BY processing_date').fetchall()]; conn.close()"
```

---

### PASO 8 — Probar con Ollama (sin API key)

Editar `.env`:
```dotenv
MP_LLM_PROVIDER=ollama
MP_LLM_MODEL=llama3.1
```

```powershell
ollama serve        # En una terminal
python -m my_princess.main --cycles 5   # En otra
```

---

### PASO 9 — Limpiar para prueba limpia

```powershell
Remove-Item -Recurse -Force data\,output\,watchfolder\ -ErrorAction SilentlyContinue
```

---

## 2. Auditoría Técnica

### 2.1 Arquitectura General — 8.5/10

El proyecto implementa un pipeline de agente de IA de responsabilidad única con separación limpia de capas:

```
CLI (main.py)
  └─ Watcher (polling)
       └─ Pipeline (LangGraph)
            ├─ dedupe       → db.py + watcher.py
            ├─ transcribe   → audio.py + transcriber.py
            ├─ structure    → llm.py + models.py
            └─ write_output → output.py
                           └─ db.py + notes.py (cross-cutting)
```

**Fortalezas:**
- Inyección de dependencias explícita en `build_components()` y `Pipeline.__init__()`.
- Estado persistido en SQLite, no en el grafo: el grafo es stateless salvo `asset_id`, flujo auditable y reanudable.
- `process_asset()` como barrera de error total: ningún asset fallido tumba el loop de polling.

**Deuda arquitectural:**
- `Database` mantiene una conexión SQLite abierta por instancia sin pool ni reconexión. Punto de falla en concurrencia.
- `db.py` devuelve `dict[str, Any]` raw sin tipos de dominio, frágil a cambios de esquema.

---

### 2.2 Compatibilidad — 8/10

| Aspecto | Estado | Detalle |
|---|---|---|
| Python 3.11+ | OK | `requires-python = ">=3.11"` declarado |
| Windows | OK | Polling, ffmpeg empaquetado, `pathlib.Path` |
| Linux/macOS | OK | Sin dependencias win32 |
| LangGraph 0.2+ | Atención | `set_entry_point()` deprecated en 0.3+; conviene anclar versión |
| faster-whisper 1.0+ | OK | API `(segments, info)` estable |
| LiteLLM 1.50+ | OK | Notación `provider/model` estable |
| Pydantic v2 | OK | Usa `model_validate()` y `Field` de v2; sin código v1 residual |

**Problema no documentado:** `faster-whisper` requiere `ctranslate2` que necesita Visual C++ Redistributable en Windows. No está en el README.

---

### 2.3 Configuración — 7.5/10

**Fortalezas:**
- 100% por variables de entorno, patrón correcto para producción.
- `load_dotenv()` solo en CLI, no contamina entorno de tests.
- `ensure_dirs()` crea directorios automáticamente en primer arranque.

**Problemas:**

| Problema | Severidad |
|---|---|
| `.env` real solo contiene `GEMINI_API_KEY`, inconsistente con `.env.example` | Media |
| Sin validación de rangos en `Settings` (`poll_interval=0`, `max_retries=-1` no fallan) | Baja |
| `MP_WHISPER_MODEL` no valida contra modelos soportados | Baja |
| Sin lock file de dependencias (`uv.lock`, `requirements.txt`) | Media |

---

### 2.4 Seguridad — 5.5/10

> [!CAUTION]
> **SEC-001 — CRÍTICO:** El archivo `.env` contiene una API key de Gemini con valor real. Aunque `.gitignore` incluye `.env`, si fue commiteada en algún commit queda en el historial de git. Verificar con `git log --all --full-history -- .env`. Si fue expuesta, **revocar y regenerar la key en Google AI Studio de inmediato**.

| Hallazgo | Severidad | Detalle |
|---|---|---|
| API key en `.env` potencialmente commiteada | Crítica | Ver arriba |
| SQL dinámico con f-string en `update_asset()` | Media | Columnas construidas con f-string de keys de dict; valores parametrizados correctamente con `?`. Sin riesgo inmediato (keys son internas), pero superficie de SQL injection si en el futuro se acepta input externo |
| Sin validación de `source_path` al crear asset | Media | Path traversal posible si el sistema acepta paths de entrada externa |
| `subprocess.run` en `audio.py` | OK | Usa lista, no `shell=True`. Sin riesgo de command injection |
| `error_detail` truncado a 1000 chars | OK | Previene llenado de DB con stacktraces |

---

### 2.5 Escalabilidad — 6/10

El proyecto es explícitamente una demo de un solo proceso, documentado en `DECISIONS.md`. La puntuación refleja limitaciones reales vs. producción:

| Limitación | Impacto | Camino de migración |
|---|---|---|
| SQLite con una conexión sin pool | No concurrente | Reescribir solo `db.py` con PostgreSQL/MongoDB |
| Pipeline secuencial (un asset a la vez) | Cola crece linealmente | `ThreadPoolExecutor` en `main.py` |
| Whisper en CPU (`device="cpu"`) | Lento en videos largos | Parametrizar `device` y `compute_type` via env |
| `data/audio/*.wav` sin cleanup | Disco lleno en producción | Eliminar WAV tras transcripción exitosa |
| `ai_notes.md` sin rotación | Inmanejable con miles de assets | Rotar por fecha o tamaño |

**Fortalezas para escala futura:**
- `LLMClient` (Protocol) permite sustituir proveedor sin tocar el grafo.
- `Database` es el único punto de contacto con SQLite; migración = reescribir un módulo.

---

### 2.6 Flexibilidad — 9/10

| Dimensión | Evaluación |
|---|---|
| Proveedor LLM | Excelente. ~100 proveedores vía LiteLLM; cambiar = 2 líneas en `.env` |
| Modelo Whisper | Correcto. Cualquier modelo de faster-whisper |
| Rutas de datos | Correcto. Todas configurables via env vars |
| Extensión del grafo | Bueno. Patrón `continue_or_end` consistente; agregar nodo es trivial |
| Extensión del schema LLM | Moderado. Cambiar `AssetMetadata` requiere tocar 4 archivos sin migraciones automáticas |
| Reemplazar SQLite | Correcto. Interfaz `Database` como único punto de contacto |

---

### 2.7 Calidad del Código — 8/10

**Fortalezas:**
- Módulos pequeños y de responsabilidad única (ninguno supera 310 líneas).
- Docstrings en todos los módulos y funciones públicas.
- `from __future__ import annotations` consistente.
- Type hints completos en firmas públicas.
- Manejo de errores diferenciado: transitorio (reintentar) vs. determinístico (NEEDS_REVIEW). Distinción correcta y valiosa.

**Problemas de calidad:**

| ID | Archivo | Línea | Detalle |
|---|---|---|---|
| CODE-001 | `graph.py` | 67 | `continue_or_end = lambda state: ...` — PEP 8 desaconseja lambdas asignadas; debería ser `def` |
| CODE-002 | `db.py` | 96 | `update_asset(**fields)` sin whitelist; typo en key no genera error, actualización silenciosa |
| CODE-003 | `graph.py` | 154 | `log_transition(DETECTED → TRANSCRIBING)` semánticamente confuso: el asset pasó por `dedupe` sin cambio de estado; la transición refleja el momento actual, no la etapa anterior |
| CODE-004 | `notes.py` | 29 | Abre/cierra archivo en cada `log()`. Correcto para durabilidad; ineficiente a alto volumen (no aplica en la demo) |
| TEST-001 | `test_watcher.py` | 34 | `assert watcher.scan() != []` — debería ser `assert len(watcher.scan()) == 1` para aserción explícita |

---

### 2.8 Documentación — 9/10

| Documento | Evaluación |
|---|---|
| `README.md` | Excelente. Arquitectura, instalación, configuración, tabla de vars, ejecución, inspección DB, estructura |
| `DECISIONS.md` | Excelente. Cada decisión justificada con razonamiento técnico concreto. Artefacto de ingeniería real |
| `docs/graph.md` | Correcto. Diagrama ASCII + tabla de nodos y transiciones |
| `ai_notes.md` | Útil. Bitácora de implementación + runtime. Doble función bien lograda |
| Docstrings en código | Correcto. Todos los módulos tienen docstring; funciones públicas documentadas |
| Docstrings en tests | Correcto. Cada archivo de test explica qué cubre y qué mockea |
| Lock file de dependencias | Ausente. Sin `requirements.txt`, `uv.lock` ni `poetry.lock` |
| CHANGELOG | Ausente. Aceptable para proyecto universitario |
| Tabla de error_codes | Parcial. Códigos presentes en código pero sin tabla de referencia en docs |

---

### 2.9 Testing — 9.5/10

| Aspecto | Evaluación |
|---|---|
| Cobertura declarada | 98% (`.coverage` presente en el repo, verificable) |
| Test E2E | `test_e2e.py` recorre flujo completo con ffmpeg real; Whisper y LLM mockeados |
| Tests unitarios por módulo | Un archivo de test por módulo de producción |
| Casos negativos | Archivo faltante, transcripción fallida, schema LLM inválido, error de transporte, duplicado por hash, duplicado por path, error no manejado |
| Fixtures aisladas | `tmp_path` de pytest; sin estado compartido entre tests |
| Mocking quirúrgico | `patch.object` y `MagicMock` bien aplicados; sin patches globales |
| Tests parametrizados | `@pytest.mark.parametrize` en `test_llm.py` y `test_models_notes.py` |
| Sin tests contra API real | Correcto para CI/CD; integración real se cubre en demo manual |

**Único gap:** No hay test para `Settings.ensure_dirs()`, pero es código trivial.

---

## 3. Resumen Ejecutivo

### Tabla de puntuaciones

| Dimensión | Puntuación | Estado |
|---|---|---|
| Arquitectura | 8.5/10 | Sólida para el scope declarado |
| Compatibilidad | 8.0/10 | Cross-platform correcto |
| Configuración | 7.5/10 | Lock file ausente, .env incompleto |
| Seguridad | 5.5/10 | API key potencialmente expuesta |
| Escalabilidad | 6.0/10 | Monoproceso por diseño; documentado |
| Flexibilidad | 9.0/10 | Punto más fuerte del proyecto |
| Calidad de código | 8.0/10 | Limpio, tipado, deuda menor |
| Documentación | 9.0/10 | Muy por encima del estándar universitario |
| Testing | 9.5/10 | 98% cobertura, E2E real, mocks quirúrgicos |
| **PROMEDIO** | **7.9/10** | |

---

### Hallazgos por severidad

#### Críticos (acción inmediata)

> [!CAUTION]
> **SEC-001:** Verificar si `.env` fue commiteado: `git log --all --full-history -- .env`. Si fue expuesto, revocar la `GEMINI_API_KEY` en [Google AI Studio](https://aistudio.google.com/) y generar una nueva.

#### Medios (acción recomendada)

1. **DEP-001:** Generar lock file: `pip freeze > requirements.txt` o usar `uv lock`.
2. **DB-001:** Agregar whitelist de columnas permitidas en `update_asset()` de `db.py`.
3. **DISC-001:** Eliminar `data/audio/*.wav` tras transcripción exitosa para evitar crecimiento de disco.
4. **CFG-001:** Completar el `.env` con todas las variables de `.env.example`.

#### Menores (mejoras futuras)

1. **CODE-001:** Convertir la lambda `continue_or_end` a `def` en `graph.py:67`.
2. **CODE-002:** Agregar whitelist de campos en `update_asset()`.
3. **DOC-001:** Documentar requisito de Visual C++ Redistributable en Windows para `faster-whisper`.
4. **DOC-002:** Agregar tabla de `error_code` al README.
5. **TEST-001:** Cambiar `assert watcher.scan() != []` a `assert len(watcher.scan()) == 1` en `test_watcher.py:34`.

---

### Conclusión del auditor

El proyecto `my_princess` es **técnicamente sólido y bien ejecutado** para su alcance declarado: una demo de pipeline de agente de IA para documentalización automática de videos proxy.

La separación de responsabilidades es clara, el testing es riguroso (98% de cobertura con un E2E que ejercita ffmpeg real), la documentación es honesta sobre sus limitaciones de diseño, y las decisiones arquitecturales están explícitamente justificadas en `DECISIONS.md`, lo cual es práctica de ingeniería senior.

El punto débil principal es la seguridad (posible exposición de API key) y la ausencia de lock file de dependencias. Ambos son solucionables sin refactoring del código fuente.

El código está listo para demo funcional. Para producción real, los ejes de Escalabilidad y Seguridad requieren atención antes del deployment.
