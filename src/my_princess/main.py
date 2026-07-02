"""Punto de entrada: loop de polling sobre el watchfolder.

Uso:
    python -m my_princess.main            # loop infinito
    python -m my_princess.main --cycles 3 # N ciclos y termina (util en pruebas)
"""
from __future__ import annotations

import argparse
import time

from .config import Settings
from .db import Database
from .graph import Pipeline
from .llm import LLMClient, build_llm_client
from .notes import AINotes
from .transcriber import Transcriber
from .watcher import Watcher


def build_components(settings: Settings, llm: LLMClient | None = None):
    """Construye las piezas del pipeline. `llm` es inyectable para tests."""
    settings.ensure_dirs()
    db = Database(settings.db_path)
    notes = AINotes(settings.ai_notes_path)
    watcher = Watcher(settings.watch_dir, db, notes)
    if llm is None:
        llm = build_llm_client(
            settings.llm_provider, settings.llm_model, api_base=settings.llm_api_base
        )
    transcriber = Transcriber(settings.whisper_model)
    pipeline = Pipeline(db, notes, transcriber, llm, settings)
    return db, notes, watcher, pipeline


def run(settings: Settings, cycles: int | None = None, llm: LLMClient | None = None) -> None:
    db, notes, watcher, pipeline = build_components(settings, llm=llm)
    notes.log(
        None, "startup",
        f"Pipeline iniciado. watchfolder=`{settings.watch_dir}` "
        f"intervalo={settings.poll_interval_seconds}s modelo_whisper={settings.whisper_model}",
    )
    completed = 0
    try:
        while cycles is None or completed < cycles:
            for asset_id in watcher.scan():
                final = pipeline.process_asset(asset_id)
                print(f"[{asset_id}] -> {final}")
            completed += 1
            if cycles is None or completed < cycles:
                time.sleep(settings.poll_interval_seconds)
    except KeyboardInterrupt:  # pragma: no cover - interactivo
        notes.log(None, "shutdown", "Pipeline detenido por el usuario.")
    finally:
        db.close()


def main() -> None:  # pragma: no cover - CLI delgado
    parser = argparse.ArgumentParser(description="Pipeline de documentalizacion")
    parser.add_argument("--cycles", type=int, default=None,
                        help="numero de ciclos de escaneo (default: infinito)")
    args = parser.parse_args()
    run(Settings(), cycles=args.cycles)


if __name__ == "__main__":  # pragma: no cover
    main()
