"""Contratos de entrada/salida de la API (pydantic -> OpenAPI)."""
from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from ..models import AssetStatus

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Envoltura estandar de paginacion para todas las listas."""

    items: list[T]
    page: int = Field(description="Pagina actual (1-based)")
    size: int = Field(description="Tamano de pagina solicitado")
    total_items: int
    total_pages: int


class OutputFolder(str, Enum):
    """Carpetas de salida consultables."""

    output = "output"
    approved = "approved"


class AssetSummary(BaseModel):
    id_asset: str
    source_path: str
    status: AssetStatus
    title: str | None = None
    confidence_score: float | None = None
    error_code: str | None = None
    retry_count: int = 0
    duration_minutes: float | None = None
    intake_date: str
    created_at: str
    updated_at: str


class AssetDetail(AssetSummary):
    transcript: str | None = None
    summary_short: str | None = None
    summary_long: str | None = None
    tags: list[str] | None = None
    staff: list[str] | None = None
    validation_notes: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    published_at: str | None = None
    category: str | None = None
    file_hash: str | None = None


class TransformLogOut(BaseModel):
    id_transform_log: str
    asset_id: str
    stage: str
    status_from: AssetStatus | None = None
    status_to: AssetStatus
    intake_date: str
    processing_date: str
    duration_ms: int | None = None
    error_detail: str | None = None


class OutputFileOut(BaseModel):
    asset_id: str
    folder: OutputFolder
    filename: str
    size_bytes: int
    modified_at: str


class UploadOut(BaseModel):
    filename: str
    size_bytes: int
    detail: str


class ConfigOut(BaseModel):
    confidence_threshold: float
    source: str = Field(
        description="'dynamic' si fue configurado via API; 'env_default' si aplica el default de entorno"
    )


class ConfigUpdate(BaseModel):
    confidence_threshold: float = Field(
        ge=0.0, le=1.0,
        description="Umbral de triage del agente: confidence_score >= umbral envia la salida a approved/",
    )


class HealthOut(BaseModel):
    status: str
    database: str
