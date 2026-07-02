"""Configuracion del pipeline via variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    watch_dir: Path = field(default_factory=lambda: Path(_env("MP_WATCH_DIR", "watchfolder")))
    output_dir: Path = field(default_factory=lambda: Path(_env("MP_OUTPUT_DIR", "output")))
    db_path: Path = field(default_factory=lambda: Path(_env("MP_DB_PATH", "data/my_princess.db")))
    ai_notes_path: Path = field(default_factory=lambda: Path(_env("MP_AI_NOTES_PATH", "ai_notes.md")))
    poll_interval_seconds: float = field(
        default_factory=lambda: float(_env("MP_POLL_INTERVAL_SECONDS", "2"))
    )
    max_retries: int = field(default_factory=lambda: int(_env("MP_MAX_RETRIES", "3")))
    whisper_model: str = field(default_factory=lambda: _env("MP_WHISPER_MODEL", "base"))
    llm_provider: str = field(default_factory=lambda: _env("MP_LLM_PROVIDER", "gemini"))
    llm_model: str = field(default_factory=lambda: _env("MP_LLM_MODEL", "gemini-2.5-flash"))
    # opcional: endpoint custom (p. ej. Ollama en otro host); vacio = default
    llm_api_base: str | None = field(
        default_factory=lambda: _env("MP_LLM_API_BASE", "") or None
    )

    def ensure_dirs(self) -> None:
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
