"""Escritor de ai_notes.md: bitacora legible por humanos, una entrada por evento."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class AINotes:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("# AI Notes — my_princess\n\n", encoding="utf-8")

    def log(
        self,
        asset_id: str | None,
        stage: str,
        message: str,
        transition: str | None = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = [f"## {timestamp} — {stage}\n"]
        if asset_id:
            lines.append(f"- **Asset**: `{asset_id}`\n")
        if transition:
            lines.append(f"- **Transición**: {transition}\n")
        lines.append(f"- {message}\n\n")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.writelines(lines)
