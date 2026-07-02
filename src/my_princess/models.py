"""Enums y contratos de datos del pipeline."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AssetStatus(str, Enum):
    DETECTED = "DETECTED"
    DUPLICATE = "DUPLICATE"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBED = "TRANSCRIBED"
    STRUCTURING = "STRUCTURING"
    PENDING_VALIDATION = "PENDING_VALIDATION"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class AssetCategory(str, Enum):
    NEWS = "NEWS"
    SPORTS = "SPORTS"
    ENTERTAINMENT = "ENTERTAINMENT"
    DOCUMENTARY = "DOCUMENTARY"
    OTHER = "OTHER"


class AssetMetadata(BaseModel):
    """Contrato estricto de salida del LLM (ver JSON Schema en el prompt)."""

    title: str = Field(max_length=120)
    summary_short: str = Field(min_length=1)
    summary_long: str = Field(min_length=1)
    tags: list[str] = Field(min_length=3, max_length=10)
    staff: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
