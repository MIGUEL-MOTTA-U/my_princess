"""Tests del grafo LangGraph con transcriber y LLM mockeados."""
import json
from unittest.mock import MagicMock, patch

import pytest

from my_princess.config import Settings
from my_princess.graph import Pipeline
from my_princess.models import AssetStatus
from my_princess.notes import AINotes
from my_princess.transcriber import TranscriptionError, TranscriptionResult

VALID_METADATA = {
    "title": "Reportaje del día",
    "summary_short": "Resumen corto.",
    "summary_long": "Resumen largo del reportaje.",
    "tags": ["reportaje", "noticias", "actualidad"],
    "staff": [],
    "confidence_score": 0.9,
}


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, system, user):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def settings(tmp_path):
    return Settings(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "out",
        approved_dir=tmp_path / "approved",
        confidence_threshold=0.8,
        work_dir=tmp_path / "data",
        ai_notes_path=tmp_path / "ai_notes.md",
        max_retries=2,
    )


@pytest.fixture
def transcriber_ok():
    transcriber = MagicMock()
    transcriber.transcribe.return_value = TranscriptionResult(
        text="hola desde el noticiero", duration_minutes=0.5, language="es"
    )
    return transcriber


def make_asset(db, tmp_path, name="video.mp4", content=b"fake-video-bytes"):
    video = tmp_path / name
    video.write_bytes(content)
    return db.create_asset(str(video))


def build_pipeline(db, settings, transcriber, llm):
    notes = AINotes(settings.ai_notes_path)
    return Pipeline(db, notes, transcriber, llm, settings)


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_happy_path_reaches_pending_validation(mock_extract, db, settings, transcriber_ok, tmp_path):
    llm = FakeLLM([json.dumps(VALID_METADATA)])
    pipeline = build_pipeline(db, settings, transcriber_ok, llm)
    asset_id = make_asset(db, tmp_path)

    final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.PENDING_VALIDATION.value
    asset = db.get_asset(asset_id)
    assert asset["transcript"] == "hola desde el noticiero"
    assert asset["title"] == VALID_METADATA["title"]
    assert asset["file_hash"]

    # transform_logs: una entrada por transicion real
    transitions = [(l["status_from"], l["status_to"]) for l in db.get_logs(asset_id)]
    assert ("DETECTED", "TRANSCRIBING") in transitions
    assert ("TRANSCRIBING", "TRANSCRIBED") in transitions
    assert ("TRANSCRIBED", "STRUCTURING") in transitions
    assert ("STRUCTURING", "PENDING_VALIDATION") in transitions

    # confidence 0.9 >= umbral 0.8: el agente enruta la salida a approved/
    out_file = settings.approved_dir / f"{asset_id}.json"
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["transcript"] == "hola desde el noticiero"
    assert payload["metadata"]["tags"] == VALID_METADATA["tags"]
    assert not (settings.output_dir / f"{asset_id}.json").exists()
    assert "APPROVED" in asset["validation_notes"]


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_duplicate_by_hash_stops_flow(mock_extract, db, settings, transcriber_ok, tmp_path):
    llm = FakeLLM([json.dumps(VALID_METADATA)])
    pipeline = build_pipeline(db, settings, transcriber_ok, llm)

    first = make_asset(db, tmp_path, "a.mp4", b"same-bytes")
    pipeline.process_asset(first)

    second = make_asset(db, tmp_path, "b.mp4", b"same-bytes")
    final = pipeline.process_asset(second)

    assert final == AssetStatus.DUPLICATE.value
    assert db.get_asset(second)["status"] == "DUPLICATE"
    transitions = [(l["status_from"], l["status_to"]) for l in db.get_logs(second)]
    assert ("DETECTED", "DUPLICATE") in transitions
    # el flujo se detuvo: no hay archivo de salida para el duplicado
    assert not (settings.output_dir / f"{second}.json").exists()


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_transcription_failure_exhausts_retries(mock_extract, db, settings, tmp_path):
    transcriber = MagicMock()
    transcriber.transcribe.side_effect = TranscriptionError("audio corrupto")
    pipeline = build_pipeline(db, settings, transcriber, FakeLLM([]))
    asset_id = make_asset(db, tmp_path)

    final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.FAILED.value
    asset = db.get_asset(asset_id)
    assert asset["retry_count"] == settings.max_retries
    assert asset["error_code"].startswith("TRANSCRIPTION_ERROR")
    transitions = [(l["status_from"], l["status_to"]) for l in db.get_logs(asset_id)]
    assert ("TRANSCRIBING", "FAILED") in transitions


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_invalid_llm_schema_goes_to_needs_review(mock_extract, db, settings, transcriber_ok, tmp_path):
    bad = json.dumps({**VALID_METADATA, "tags": []})
    llm = FakeLLM([bad, bad])  # respuesta y correccion, ambas invalidas
    pipeline = build_pipeline(db, settings, transcriber_ok, llm)
    asset_id = make_asset(db, tmp_path)

    final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.NEEDS_REVIEW.value
    asset = db.get_asset(asset_id)
    assert asset["error_code"].startswith("LLM_SCHEMA_VALIDATION_FAILED")
    transitions = [(l["status_from"], l["status_to"]) for l in db.get_logs(asset_id)]
    assert ("STRUCTURING", "NEEDS_REVIEW") in transitions


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_llm_transport_error_retries_then_fails(mock_extract, db, settings, transcriber_ok, tmp_path):
    llm = FakeLLM([ConnectionError("api caida"), ConnectionError("api caida")])
    pipeline = build_pipeline(db, settings, transcriber_ok, llm)
    asset_id = make_asset(db, tmp_path)

    final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.FAILED.value
    asset = db.get_asset(asset_id)
    assert asset["error_code"].startswith("LLM_TRANSPORT_ERROR")


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_llm_transport_error_then_success(mock_extract, db, settings, transcriber_ok, tmp_path):
    llm = FakeLLM([ConnectionError("blip"), json.dumps(VALID_METADATA)])
    pipeline = build_pipeline(db, settings, transcriber_ok, llm)
    asset_id = make_asset(db, tmp_path)

    final = pipeline.process_asset(asset_id)
    assert final == AssetStatus.PENDING_VALIDATION.value


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_low_confidence_routes_to_output_dir(mock_extract, db, settings, transcriber_ok, tmp_path):
    low = dict(VALID_METADATA, confidence_score=0.5)  # 0.5 < umbral 0.8
    pipeline = build_pipeline(db, settings, transcriber_ok, FakeLLM([json.dumps(low)]))
    asset_id = make_asset(db, tmp_path)

    final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.PENDING_VALIDATION.value
    assert (settings.output_dir / f"{asset_id}.json").exists()
    assert not (settings.approved_dir / f"{asset_id}.json").exists()
    assert "revision estandar" in db.get_asset(asset_id)["validation_notes"]


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_confidence_threshold_is_configurable(mock_extract, db, settings, transcriber_ok, tmp_path):
    settings.confidence_threshold = 0.95  # el 0.9 del payload ya no alcanza
    pipeline = build_pipeline(db, settings, transcriber_ok, FakeLLM([json.dumps(VALID_METADATA)]))
    asset_id = make_asset(db, tmp_path)

    pipeline.process_asset(asset_id)

    assert (settings.output_dir / f"{asset_id}.json").exists()
    assert not (settings.approved_dir / f"{asset_id}.json").exists()


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_dynamic_threshold_from_db_overrides_env_default(mock_extract, db, settings, transcriber_ok, tmp_path):
    # el default (settings) aprobaría con 0.8, pero la config dinámica manda
    db.set_config_value("confidence_threshold", 0.95)
    pipeline = build_pipeline(db, settings, transcriber_ok, FakeLLM([json.dumps(VALID_METADATA)]))
    asset_id = make_asset(db, tmp_path)

    pipeline.process_asset(asset_id)

    assert (settings.output_dir / f"{asset_id}.json").exists()
    assert not (settings.approved_dir / f"{asset_id}.json").exists()
    assert "umbral 0.95" in db.get_asset(asset_id)["validation_notes"]


def test_missing_source_file_fails_cleanly(db, settings, transcriber_ok, tmp_path):
    pipeline = build_pipeline(db, settings, transcriber_ok, FakeLLM([]))
    asset_id = db.create_asset(str(tmp_path / "ghost.mp4"))

    final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.FAILED.value
    assert db.get_asset(asset_id)["error_code"] == "FILE_ACCESS_ERROR"


@patch("my_princess.graph.extract_audio", return_value="audio.wav")
def test_unhandled_exception_never_propagates(mock_extract, db, settings, tmp_path):
    transcriber = MagicMock()
    transcriber.transcribe.return_value = TranscriptionResult(text="ok", duration_minutes=1)
    pipeline = build_pipeline(db, settings, transcriber, FakeLLM([]))
    asset_id = make_asset(db, tmp_path)

    # rompemos la base de datos a mitad del flujo para forzar una excepcion
    with patch.object(pipeline.db, "find_duplicate", side_effect=RuntimeError("db rota")):
        final = pipeline.process_asset(asset_id)

    assert final == AssetStatus.FAILED.value
    assert db.get_asset(asset_id)["error_code"].startswith("UNHANDLED_ERROR")
