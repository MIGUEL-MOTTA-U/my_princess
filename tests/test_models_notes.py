"""Tests de modelos (contrato LLM) y del escritor de ai_notes."""
import pytest
from pydantic import ValidationError

from my_princess.models import AssetMetadata, AssetStatus
from my_princess.notes import AINotes


VALID = {
    "title": "Noticiero mediodía",
    "summary_short": "Resumen corto.",
    "summary_long": "Resumen largo con más contexto.",
    "tags": ["noticias", "mediodía", "nacional"],
    "staff": ["Juan Gómez"],
    "confidence_score": 0.82,
}


def test_valid_metadata_parses():
    meta = AssetMetadata.model_validate(VALID)
    assert meta.title == "Noticiero mediodía"
    assert 0 <= meta.confidence_score <= 1


@pytest.mark.parametrize(
    "override",
    [
        {"title": "x" * 121},
        {"tags": ["solo", "dos"]},
        {"tags": [f"t{i}" for i in range(11)]},
        {"confidence_score": 1.5},
        {"confidence_score": -0.1},
        {"summary_short": ""},
    ],
)
def test_invalid_metadata_rejected(override):
    with pytest.raises(ValidationError):
        AssetMetadata.model_validate({**VALID, **override})


def test_staff_defaults_to_empty():
    data = dict(VALID)
    del data["staff"]
    assert AssetMetadata.model_validate(data).staff == []


def test_asset_status_enum_members():
    assert AssetStatus.DETECTED.value == "DETECTED"
    assert AssetStatus("PENDING_VALIDATION") is AssetStatus.PENDING_VALIDATION


def test_ai_notes_appends_entries(tmp_path):
    notes = AINotes(tmp_path / "ai_notes.md")
    notes.log("asset-1", "detection", "Archivo detectado", transition="→ DETECTED")
    notes.log(None, "startup", "Pipeline iniciado")
    content = (tmp_path / "ai_notes.md").read_text(encoding="utf-8")
    assert "asset-1" in content
    assert "→ DETECTED" in content
    assert "Pipeline iniciado" in content
    assert content.startswith("# AI Notes")
