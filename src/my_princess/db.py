"""Persistencia en MongoDB: colecciones `assets` y `transform_logs`.

Migrado desde SQLite ahora que hay Docker disponible (ver DECISIONS.md);
la interfaz publica de `Database` es identica, asi que el resto del
pipeline no cambio. `tags`/`staff` se guardan como arrays nativos y las
fechas como strings ISO-8601 (igual que antes, para mantener el contrato).

Los tests usan `mongomock` inyectando `client=`; en runtime se conecta a
`MP_MONGO_URI` (docker-compose.yml levanta el Mongo local).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .models import AssetStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# campos actualizables de `assets`; un typo en update_asset debe fallar
# ruidosamente en vez de actualizar nada en silencio
_ASSET_FIELDS = frozenset({
    "source_path", "title", "transcript", "summary_short", "summary_long",
    "tags", "staff", "confidence_score", "status", "validation_notes",
    "approved_by", "approved_at", "published_at", "error_code",
    "retry_count", "duration_minutes", "category", "file_hash",
})

_NO_MONGO_ID = {"_id": 0}


class Database:
    """Acceso a datos. `client` es inyectable para tests (mongomock)."""

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
        db_name: str = "my_princess",
        client: Any | None = None,
    ):
        if client is None:  # pragma: no cover - conexion real a Mongo
            from pymongo import MongoClient

            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._client = client
        database = client[db_name]
        self._assets = database["assets"]
        self._logs = database["transform_logs"]
        self._config = database["config"]
        self._assets.create_index("id_asset", unique=True)
        self._assets.create_index("source_path")
        self._assets.create_index("file_hash")
        self._logs.create_index("asset_id")
        self._config.create_index("key", unique=True)

    def close(self) -> None:
        self._client.close()

    # -- assets ---------------------------------------------------------

    def create_asset(self, source_path: str) -> str:
        asset_id = str(uuid.uuid4())
        now = _now()
        document = {field: None for field in _ASSET_FIELDS}
        document.update(
            id_asset=asset_id,
            source_path=source_path,
            status=AssetStatus.DETECTED.value,
            retry_count=0,
            intake_date=now,
            created_at=now,
            updated_at=now,
        )
        self._assets.insert_one(document)
        return asset_id

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self._assets.find_one({"id_asset": asset_id}, _NO_MONGO_ID)

    def update_asset(self, asset_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - _ASSET_FIELDS
        if unknown:
            raise ValueError(f"Campos desconocidos en update_asset: {sorted(unknown)}")
        serialized: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(value, AssetStatus):
                value = value.value
            elif isinstance(value, datetime):
                value = value.isoformat()
            serialized[key] = value
        serialized["updated_at"] = _now()
        self._assets.update_one({"id_asset": asset_id}, {"$set": serialized})

    def find_asset_by_source_path(self, source_path: str) -> dict[str, Any] | None:
        return self._assets.find_one(
            {"source_path": source_path}, _NO_MONGO_ID, sort=[("created_at", 1)]
        )

    def find_duplicate(
        self, asset_id: str, source_path: str, file_hash: str
    ) -> dict[str, Any] | None:
        """Otro asset (distinto id) con el mismo source_path o el mismo hash."""
        return self._assets.find_one(
            {
                "id_asset": {"$ne": asset_id},
                "$or": [{"source_path": source_path}, {"file_hash": file_hash}],
            },
            _NO_MONGO_ID,
            sort=[("created_at", 1)],
        )

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
        self._logs.insert_one(
            {
                "id_transform_log": log_id,
                "asset_id": asset_id,
                "stage": stage,
                "status_from": status_from.value if status_from else None,
                "status_to": status_to.value,
                "intake_date": asset["intake_date"] if asset else _now(),
                "processing_date": _now(),
                "duration_ms": duration_ms,
                "error_detail": error_detail,
            }
        )
        return log_id

    def get_logs(self, asset_id: str) -> list[dict[str, Any]]:
        return list(
            self._logs.find({"asset_id": asset_id}, _NO_MONGO_ID).sort(
                "processing_date", 1
            )
        )

    # -- config dinamica -------------------------------------------------

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Configuracion runtime (editable via API sin reiniciar el pipeline)."""
        document = self._config.find_one({"key": key})
        return document["value"] if document else default

    def set_config_value(self, key: str, value: Any) -> None:
        self._config.update_one(
            {"key": key},
            {"$set": {"key": key, "value": value, "updated_at": _now()}},
            upsert=True,
        )

    # -- consultas paginadas (API) ----------------------------------------

    def list_assets(
        self, status: str | None = None, skip: int = 0, limit: int = 20
    ) -> list[dict[str, Any]]:
        query = {"status": status} if status else {}
        return list(
            self._assets.find(query, _NO_MONGO_ID)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

    def count_assets(self, status: str | None = None) -> int:
        query = {"status": status} if status else {}
        return self._assets.count_documents(query)

    def list_logs(
        self, asset_id: str | None = None, skip: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        query = {"asset_id": asset_id} if asset_id else {}
        return list(
            self._logs.find(query, _NO_MONGO_ID)
            .sort("processing_date", -1)
            .skip(skip)
            .limit(limit)
        )

    def count_logs(self, asset_id: str | None = None) -> int:
        query = {"asset_id": asset_id} if asset_id else {}
        return self._logs.count_documents(query)
