"""Orquestacion del pipeline con LangGraph.

Grafo (ver docs/graph.md):

    dedupe ──(duplicado o error de archivo)──▶ END  [DUPLICATE | FAILED]
      │
    transcribe ──(agota reintentos)──▶ END  [FAILED]
      │   DETECTED → TRANSCRIBING → TRANSCRIBED
    structure ──(schema invalido)──▶ END  [NEEDS_REVIEW]
      │   TRANSCRIBED → STRUCTURING          (transporte agota reintentos → FAILED)
    write_output ──▶ END  [PENDING_VALIDATION]

Cada nodo persiste su transicion en transform_logs y en ai_notes.md.
Ningun error de un asset debe escapar del grafo: `process_asset` captura
cualquier excepcion residual y marca el asset como FAILED.
"""
from __future__ import annotations

import time
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .audio import extract_audio
from .config import Settings
from .db import Database
from .llm import LLMClient, structure_metadata
from .models import AssetStatus
from .notes import AINotes
from .output import write_output_file
from .transcriber import Transcriber
from .watcher import compute_file_hash


class PipelineState(TypedDict, total=False):
    asset_id: str
    final_status: str  # presente solo cuando el flujo termina antes del final


class Pipeline:
    def __init__(
        self,
        db: Database,
        notes: AINotes,
        transcriber: Transcriber,
        llm: LLMClient,
        settings: Settings,
    ):
        self.db = db
        self.notes = notes
        self.transcriber = transcriber
        self.llm = llm
        self.settings = settings
        self.audio_dir = settings.db_path.parent / "audio"
        self.graph = self._build_graph()

    # -- construccion del grafo ------------------------------------------

    def _build_graph(self):
        graph = StateGraph(PipelineState)
        graph.add_node("dedupe", self._dedupe)
        graph.add_node("transcribe", self._transcribe)
        graph.add_node("structure", self._structure)
        graph.add_node("write_output", self._write_output)

        graph.set_entry_point("dedupe")
        continue_or_end = lambda state: END if state.get("final_status") else "continue"  # noqa: E731
        graph.add_conditional_edges(
            "dedupe", continue_or_end, {END: END, "continue": "transcribe"}
        )
        graph.add_conditional_edges(
            "transcribe", continue_or_end, {END: END, "continue": "structure"}
        )
        graph.add_conditional_edges(
            "structure", continue_or_end, {END: END, "continue": "write_output"}
        )
        graph.add_edge("write_output", END)
        return graph.compile()

    # -- API publica ------------------------------------------------------

    def process_asset(self, asset_id: str) -> str:
        """Ejecuta el grafo para un asset. Nunca propaga excepciones: un
        archivo fallido no debe tumbar el loop de polling."""
        try:
            result = self.graph.invoke({"asset_id": asset_id})
            if result.get("final_status"):
                return result["final_status"]
            return self.db.get_asset(asset_id)["status"]
        except Exception as exc:  # ultima linea de defensa
            current = self.db.get_asset(asset_id)
            status_from = AssetStatus(current["status"]) if current else None
            self.db.update_asset(
                asset_id,
                status=AssetStatus.FAILED,
                error_code=f"UNHANDLED_ERROR: {type(exc).__name__}",
            )
            self.db.log_transition(
                asset_id, "pipeline", status_from, AssetStatus.FAILED,
                error_detail=str(exc)[:1000],
            )
            self.notes.log(
                asset_id, "pipeline",
                f"Error no manejado, asset marcado FAILED: {exc}",
                transition=f"{status_from.value if status_from else '?'} → FAILED",
            )
            return AssetStatus.FAILED.value

    # -- nodos -------------------------------------------------------------

    def _dedupe(self, state: PipelineState) -> PipelineState:
        asset_id = state["asset_id"]
        asset = self.db.get_asset(asset_id)
        started = time.monotonic()
        try:
            file_hash = compute_file_hash(asset["source_path"])
        except OSError as exc:
            self.db.update_asset(
                asset_id, status=AssetStatus.FAILED, error_code="FILE_ACCESS_ERROR"
            )
            self.db.log_transition(
                asset_id, "dedupe", AssetStatus.DETECTED, AssetStatus.FAILED,
                duration_ms=_elapsed_ms(started), error_detail=str(exc),
            )
            self.notes.log(
                asset_id, "dedupe", f"No se pudo leer el archivo: {exc}",
                transition="DETECTED → FAILED",
            )
            return {"final_status": AssetStatus.FAILED.value}

        self.db.update_asset(asset_id, file_hash=file_hash)
        duplicate = self.db.find_duplicate(asset_id, asset["source_path"], file_hash)
        if duplicate:
            self.db.update_asset(asset_id, status=AssetStatus.DUPLICATE)
            self.db.log_transition(
                asset_id, "dedupe", AssetStatus.DETECTED, AssetStatus.DUPLICATE,
                duration_ms=_elapsed_ms(started),
                error_detail=f"duplicado de {duplicate['id_asset']}",
            )
            self.notes.log(
                asset_id, "dedupe",
                f"Contenido duplicado del asset `{duplicate['id_asset']}` "
                f"(hash o source_path coincide); flujo detenido.",
                transition="DETECTED → DUPLICATE",
            )
            return {"final_status": AssetStatus.DUPLICATE.value}
        return {}

    def _transcribe(self, state: PipelineState) -> PipelineState:
        asset_id = state["asset_id"]
        asset = self.db.get_asset(asset_id)

        self.db.update_asset(asset_id, status=AssetStatus.TRANSCRIBING)
        self.db.log_transition(
            asset_id, "transcription", AssetStatus.DETECTED, AssetStatus.TRANSCRIBING
        )
        self.notes.log(
            asset_id, "transcription", "Inicia extraccion de audio y transcripcion.",
            transition="DETECTED → TRANSCRIBING",
        )

        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            started = time.monotonic()
            try:
                wav_path = extract_audio(asset["source_path"], self.audio_dir)
                result = self.transcriber.transcribe(wav_path)
                self.db.update_asset(
                    asset_id,
                    status=AssetStatus.TRANSCRIBED,
                    transcript=result.text,
                    duration_minutes=result.duration_minutes,
                    error_code=None,
                )
                self.db.log_transition(
                    asset_id, "transcription",
                    AssetStatus.TRANSCRIBING, AssetStatus.TRANSCRIBED,
                    duration_ms=_elapsed_ms(started),
                )
                self.notes.log(
                    asset_id, "transcription",
                    f"Transcripcion completada en el intento {attempt} "
                    f"({len(result.text)} caracteres, {result.duration_minutes} min).",
                    transition="TRANSCRIBING → TRANSCRIBED",
                )
                return {}
            except Exception as exc:
                last_error = exc
                retry_count = self.db.get_asset(asset_id)["retry_count"] + 1
                self.db.update_asset(
                    asset_id,
                    retry_count=retry_count,
                    error_code=f"TRANSCRIPTION_ERROR: {type(exc).__name__}",
                )
                self.notes.log(
                    asset_id, "transcription",
                    f"Intento {attempt}/{self.settings.max_retries} fallo: {exc}",
                )

        self.db.update_asset(asset_id, status=AssetStatus.FAILED)
        self.db.log_transition(
            asset_id, "transcription", AssetStatus.TRANSCRIBING, AssetStatus.FAILED,
            error_detail=str(last_error)[:1000],
        )
        self.notes.log(
            asset_id, "transcription",
            f"Reintentos agotados ({self.settings.max_retries}); asset FAILED.",
            transition="TRANSCRIBING → FAILED",
        )
        return {"final_status": AssetStatus.FAILED.value}

    def _structure(self, state: PipelineState) -> PipelineState:
        asset_id = state["asset_id"]
        asset = self.db.get_asset(asset_id)

        self.db.update_asset(asset_id, status=AssetStatus.STRUCTURING)
        self.db.log_transition(
            asset_id, "structuring", AssetStatus.TRANSCRIBED, AssetStatus.STRUCTURING
        )
        self.notes.log(
            asset_id, "structuring", "Enviando transcripcion al LLM.",
            transition="TRANSCRIBED → STRUCTURING",
        )

        started = time.monotonic()
        # Errores de transporte (red, API caida) se reintentan; un fallo de
        # validacion de schema NO es transitorio y va directo a NEEDS_REVIEW.
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                metadata, error_code = structure_metadata(self.llm, asset["transcript"])
                break
            except Exception as exc:
                last_error = exc
                retry_count = self.db.get_asset(asset_id)["retry_count"] + 1
                self.db.update_asset(
                    asset_id,
                    retry_count=retry_count,
                    error_code=f"LLM_TRANSPORT_ERROR: {type(exc).__name__}",
                )
                self.notes.log(
                    asset_id, "structuring",
                    f"Intento {attempt}/{self.settings.max_retries} fallo (transporte): {exc}",
                )
        else:
            self.db.update_asset(asset_id, status=AssetStatus.FAILED)
            self.db.log_transition(
                asset_id, "structuring", AssetStatus.STRUCTURING, AssetStatus.FAILED,
                duration_ms=_elapsed_ms(started), error_detail=str(last_error)[:1000],
            )
            self.notes.log(
                asset_id, "structuring",
                f"Reintentos agotados ({self.settings.max_retries}); asset FAILED.",
                transition="STRUCTURING → FAILED",
            )
            return {"final_status": AssetStatus.FAILED.value}

        if metadata is None:
            self.db.update_asset(
                asset_id, status=AssetStatus.NEEDS_REVIEW, error_code=error_code[:500]
            )
            self.db.log_transition(
                asset_id, "structuring", AssetStatus.STRUCTURING, AssetStatus.NEEDS_REVIEW,
                duration_ms=_elapsed_ms(started), error_detail=error_code[:1000],
            )
            self.notes.log(
                asset_id, "structuring",
                "La respuesta del LLM no valido contra el schema tras el "
                "reintento de correccion; requiere revision humana.",
                transition="STRUCTURING → NEEDS_REVIEW",
            )
            return {"final_status": AssetStatus.NEEDS_REVIEW.value}

        self.db.update_asset(
            asset_id,
            title=metadata.title,
            summary_short=metadata.summary_short,
            summary_long=metadata.summary_long,
            tags=metadata.tags,
            staff=metadata.staff,
            confidence_score=metadata.confidence_score,
            error_code=None,
        )
        self.notes.log(
            asset_id, "structuring",
            f"Metadata validada (confidence={metadata.confidence_score}).",
        )
        return {}

    def _write_output(self, state: PipelineState) -> PipelineState:
        asset_id = state["asset_id"]
        started = time.monotonic()
        self.db.update_asset(asset_id, status=AssetStatus.PENDING_VALIDATION)
        asset = self.db.get_asset(asset_id)
        path = write_output_file(asset, self.settings.output_dir)
        self.db.log_transition(
            asset_id, "output", AssetStatus.STRUCTURING, AssetStatus.PENDING_VALIDATION,
            duration_ms=_elapsed_ms(started),
        )
        self.notes.log(
            asset_id, "output",
            f"Archivo de salida generado: `{path}`. Listo para validacion humana.",
            transition="STRUCTURING → PENDING_VALIDATION",
        )
        return {"final_status": AssetStatus.PENDING_VALIDATION.value}


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
