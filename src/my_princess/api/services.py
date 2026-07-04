"""Servicios de aplicacion de la API: paginacion, reglas y archivos."""
from __future__ import annotations

import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from ..config import Settings
from .repositories import AssetRepository, ConfigRepository, TransformLogRepository
from .schemas import OutputFolder

CONFIDENCE_KEY = "confidence_threshold"


def _paginate(total: int, page: int, size: int) -> dict[str, int]:
    return {
        "page": page,
        "size": size,
        "total_items": total,
        "total_pages": math.ceil(total / size) if total else 0,
    }


class AssetNotFoundError(Exception):
    pass


class DuplicateUploadError(Exception):
    pass


class InvalidUploadError(Exception):
    pass


class AssetService:
    """Consultas de assets y su trazabilidad (transform_logs)."""

    def __init__(self, assets: AssetRepository, logs: TransformLogRepository):
        self._assets = assets
        self._logs = logs

    def list_assets(
        self, status: str | None, page: int, size: int
    ) -> dict[str, Any]:
        items = self._assets.list(status=status, skip=(page - 1) * size, limit=size)
        return {"items": items, **_paginate(self._assets.count(status), page, size)}

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self._assets.get(asset_id)
        if asset is None:
            raise AssetNotFoundError(asset_id)
        return asset

    def list_asset_logs(self, asset_id: str, page: int, size: int) -> dict[str, Any]:
        self.get_asset(asset_id)  # 404 si no existe
        items = self._logs.list(asset_id=asset_id, skip=(page - 1) * size, limit=size)
        return {"items": items, **_paginate(self._logs.count(asset_id), page, size)}

    def list_logs(self, page: int, size: int) -> dict[str, Any]:
        """Feed global de trazabilidad (mas reciente primero)."""
        items = self._logs.list(skip=(page - 1) * size, limit=size)
        return {"items": items, **_paginate(self._logs.count(), page, size)}


class FileService:
    """Carga de videos al watchfolder y consulta de las carpetas de salida."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def _folder_path(self, folder: OutputFolder) -> Path:
        return (
            self._settings.approved_dir
            if folder is OutputFolder.approved
            else self._settings.output_dir
        )

    def save_upload(self, filename: str, stream: BinaryIO) -> dict[str, Any]:
        safe_name = os.path.basename(filename or "")
        if not safe_name or not safe_name.lower().endswith(".mp4"):
            raise InvalidUploadError("solo se aceptan archivos .mp4")
        target = self._settings.watch_dir / safe_name
        if target.exists():
            raise DuplicateUploadError(safe_name)
        self._settings.watch_dir.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as fh:
            shutil.copyfileobj(stream, fh)
        return {
            "filename": safe_name,
            "size_bytes": target.stat().st_size,
            "detail": "archivo en watchfolder; el pipeline lo procesara automaticamente",
        }

    def list_outputs(
        self, folder: OutputFolder, page: int, size: int
    ) -> dict[str, Any]:
        base = self._folder_path(folder)
        files = sorted(
            base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ) if base.exists() else []
        start = (page - 1) * size
        items = [
            {
                "asset_id": path.stem,
                "folder": folder,
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            for path in files[start : start + size]
        ]
        return {"items": items, **_paginate(len(files), page, size)}

    def read_output(self, folder: OutputFolder, asset_id: str) -> dict[str, Any]:
        path = self._folder_path(folder) / f"{os.path.basename(asset_id)}.json"
        if not path.exists():
            raise AssetNotFoundError(asset_id)
        return json.loads(path.read_text(encoding="utf-8"))


class ConfigService:
    """Configuracion dinamica del agente (umbral de triage)."""

    def __init__(self, config: ConfigRepository, settings: Settings):
        self._config = config
        self._settings = settings

    def get(self) -> dict[str, Any]:
        value = self._config.get(CONFIDENCE_KEY)
        if value is None:
            return {
                "confidence_threshold": self._settings.confidence_threshold,
                "source": "env_default",
            }
        return {"confidence_threshold": float(value), "source": "dynamic"}

    def update_threshold(self, value: float) -> dict[str, Any]:
        self._config.set(CONFIDENCE_KEY, float(value))
        return self.get()
