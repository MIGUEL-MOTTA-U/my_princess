"""Patron repository de la API.

Los repositories delegan en `Database`, que sigue siendo el unico punto de
acceso a MongoDB de todo el sistema (misma instancia de datos que usa el
pipeline). Esta capa da a los servicios una interfaz de dominio estrecha y
facil de sustituir en tests.
"""
from __future__ import annotations

from typing import Any

from ..db import Database


class AssetRepository:
    def __init__(self, db: Database):
        self._db = db

    def get(self, asset_id: str) -> dict[str, Any] | None:
        return self._db.get_asset(asset_id)

    def list(
        self, status: str | None = None, skip: int = 0, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self._db.list_assets(status=status, skip=skip, limit=limit)

    def count(self, status: str | None = None) -> int:
        return self._db.count_assets(status=status)


class TransformLogRepository:
    def __init__(self, db: Database):
        self._db = db

    def list(
        self, asset_id: str | None = None, skip: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        return self._db.list_logs(asset_id=asset_id, skip=skip, limit=limit)

    def count(self, asset_id: str | None = None) -> int:
        return self._db.count_logs(asset_id=asset_id)


class ConfigRepository:
    def __init__(self, db: Database):
        self._db = db

    def get(self, key: str, default: Any = None) -> Any:
        return self._db.get_config_value(key, default)

    def set(self, key: str, value: Any) -> None:
        self._db.set_config_value(key, value)
