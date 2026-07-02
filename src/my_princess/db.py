"""Persistencia en SQLite: tablas `assets` y `transform_logs`.

SQLite se eligio sobre MongoDB porque no hay Docker disponible en el entorno
de la demo (ver DECISIONS.md). El esquema es equivalente al documental:
los campos tags/staff se serializan como JSON.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AssetStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id_asset TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    title TEXT,
    transcript TEXT,
    summary_short TEXT,
    summary_long TEXT,
    tags TEXT,
    staff TEXT,
    confidence_score REAL,
    status TEXT NOT NULL,
    validation_notes TEXT,
    approved_by TEXT,
    approved_at TEXT,
    published_at TEXT,
    error_code TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    duration_minutes REAL,
    category TEXT,
    file_hash TEXT,
    intake_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transform_logs (
    id_transform_log TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(id_asset),
    stage TEXT NOT NULL,
    status_from TEXT,
    status_to TEXT NOT NULL,
    intake_date TEXT NOT NULL,
    processing_date TEXT NOT NULL,
    duration_ms INTEGER,
    error_detail TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# columnas actualizables de `assets`; un typo en update_asset debe fallar
# ruidosamente en vez de actualizar nada en silencio
_ASSET_COLUMNS = frozenset({
    "source_path", "title", "transcript", "summary_short", "summary_long",
    "tags", "staff", "confidence_score", "status", "validation_notes",
    "approved_by", "approved_at", "published_at", "error_code",
    "retry_count", "duration_minutes", "category", "file_hash",
})


class Database:
    """Acceso a datos. Una instancia por proceso; conexion por operacion no es
    necesaria en la demo (un solo hilo procesa el pipeline)."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- assets ---------------------------------------------------------

    def create_asset(self, source_path: str) -> str:
        asset_id = str(uuid.uuid4())
        now = _now()
        self._conn.execute(
            "INSERT INTO assets (id_asset, source_path, status, intake_date, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (asset_id, source_path, AssetStatus.DETECTED.value, now, now, now),
        )
        self._conn.commit()
        return asset_id

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM assets WHERE id_asset = ?", (asset_id,)
        ).fetchone()
        return self._row_to_asset(row) if row else None

    def update_asset(self, asset_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - _ASSET_COLUMNS
        if unknown:
            raise ValueError(f"Columnas desconocidas en update_asset: {sorted(unknown)}")
        serialized: dict[str, Any] = {}
        for key, value in fields.items():
            if key in ("tags", "staff") and value is not None:
                value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, AssetStatus):
                value = value.value
            elif isinstance(value, datetime):
                value = value.isoformat()
            serialized[key] = value
        serialized["updated_at"] = _now()
        assignments = ", ".join(f"{k} = ?" for k in serialized)
        self._conn.execute(
            f"UPDATE assets SET {assignments} WHERE id_asset = ?",
            (*serialized.values(), asset_id),
        )
        self._conn.commit()

    def find_asset_by_source_path(self, source_path: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM assets WHERE source_path = ? ORDER BY created_at LIMIT 1",
            (source_path,),
        ).fetchone()
        return self._row_to_asset(row) if row else None

    def find_duplicate(self, asset_id: str, source_path: str, file_hash: str) -> dict[str, Any] | None:
        """Otro asset (distinto id) con el mismo source_path o el mismo hash."""
        row = self._conn.execute(
            "SELECT * FROM assets WHERE id_asset != ? AND (source_path = ? OR file_hash = ?)"
            " ORDER BY created_at LIMIT 1",
            (asset_id, source_path, file_hash),
        ).fetchone()
        return self._row_to_asset(row) if row else None

    # -- transform_logs -------------------------------------------------

    def log_transition(
        self,
        asset_id: str,
        stage: str,
        status_from: AssetStatus | None,
        status_to: AssetStatus,
        duration_ms: int | None = None,
        error_detail: str | None = None,
    ) -> str:
        asset = self.get_asset(asset_id)
        log_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO transform_logs (id_transform_log, asset_id, stage, status_from,"
            " status_to, intake_date, processing_date, duration_ms, error_detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log_id,
                asset_id,
                stage,
                status_from.value if status_from else None,
                status_to.value,
                asset["intake_date"] if asset else _now(),
                _now(),
                duration_ms,
                error_detail,
            ),
        )
        self._conn.commit()
        return log_id

    def get_logs(self, asset_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM transform_logs WHERE asset_id = ? ORDER BY processing_date",
            (asset_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> dict[str, Any]:
        asset = dict(row)
        for key in ("tags", "staff"):
            if asset.get(key):
                asset[key] = json.loads(asset[key])
        return asset
