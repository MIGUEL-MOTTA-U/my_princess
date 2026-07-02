"""Generacion del archivo de salida por asset.

Formato JSON (elegido sobre Markdown porque el consumidor natural es el MAM
u otro sistema downstream; ver DECISIONS.md). Incluye la transcripcion
completa y la metadata estructurada ya validada.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_output_file(asset: dict[str, Any], output_dir: Path | str) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id_asset": asset["id_asset"],
        "source_path": asset["source_path"],
        "intake_date": asset["intake_date"],
        "duration_minutes": asset.get("duration_minutes"),
        "transcript": asset.get("transcript"),
        "metadata": {
            "title": asset.get("title"),
            "summary_short": asset.get("summary_short"),
            "summary_long": asset.get("summary_long"),
            "tags": asset.get("tags"),
            "staff": asset.get("staff"),
            "confidence_score": asset.get("confidence_score"),
        },
        "status": asset["status"],
    }
    path = output_dir / f"{asset['id_asset']}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
