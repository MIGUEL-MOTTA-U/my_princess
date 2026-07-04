"""Tests de la capa de persistencia (assets + transform_logs)."""
import pytest

from my_princess.models import AssetStatus


def test_create_asset_sets_detected_status(db):
    asset_id = db.create_asset("watchfolder/video.mp4")
    asset = db.get_asset(asset_id)
    assert asset["status"] == AssetStatus.DETECTED.value
    assert asset["source_path"] == "watchfolder/video.mp4"
    assert asset["retry_count"] == 0
    assert asset["intake_date"]


def test_get_asset_missing_returns_none(db):
    assert db.get_asset("no-such-id") is None


def test_update_asset_serializes_json_and_enum(db):
    asset_id = db.create_asset("a.mp4")
    db.update_asset(
        asset_id,
        status=AssetStatus.TRANSCRIBED,
        tags=["news", "politics", "colombia"],
        staff=["Ana Pérez"],
        transcript="hola mundo",
        confidence_score=0.9,
    )
    asset = db.get_asset(asset_id)
    assert asset["status"] == AssetStatus.TRANSCRIBED.value
    assert asset["tags"] == ["news", "politics", "colombia"]
    assert asset["staff"] == ["Ana Pérez"]
    assert asset["confidence_score"] == 0.9


def test_update_asset_rejects_unknown_columns(db):
    asset_id = db.create_asset("a.mp4")
    with pytest.raises(ValueError, match="Campos desconocidos"):
        db.update_asset(asset_id, transcritp="typo")  # typo intencional


def test_update_asset_with_no_fields_is_noop(db):
    asset_id = db.create_asset("a.mp4")
    before = db.get_asset(asset_id)
    db.update_asset(asset_id)
    assert db.get_asset(asset_id) == before


def test_find_asset_by_source_path(db):
    asset_id = db.create_asset("b.mp4")
    found = db.find_asset_by_source_path("b.mp4")
    assert found["id_asset"] == asset_id
    assert db.find_asset_by_source_path("missing.mp4") is None


def test_find_duplicate_by_hash(db):
    first = db.create_asset("original.mp4")
    db.update_asset(first, file_hash="abc123")
    second = db.create_asset("copy.mp4")
    db.update_asset(second, file_hash="abc123")

    dup = db.find_duplicate(second, "copy.mp4", "abc123")
    assert dup["id_asset"] == first


def test_find_duplicate_by_source_path(db):
    first = db.create_asset("same.mp4")
    db.update_asset(first, file_hash="h1")
    second = db.create_asset("same.mp4")
    dup = db.find_duplicate(second, "same.mp4", "h2")
    assert dup["id_asset"] == first


def test_no_duplicate_returns_none(db):
    asset_id = db.create_asset("solo.mp4")
    assert db.find_duplicate(asset_id, "solo.mp4", "hash-x") is None


def test_config_value_roundtrip_and_default(db):
    assert db.get_config_value("confidence_threshold", 0.8) == 0.8
    db.set_config_value("confidence_threshold", 0.92)
    assert db.get_config_value("confidence_threshold", 0.8) == 0.92
    db.set_config_value("confidence_threshold", 0.5)  # upsert sobreescribe
    assert db.get_config_value("confidence_threshold") == 0.5


def test_list_assets_pagination_and_status_filter(db):
    ids = [db.create_asset(f"v{i}.mp4") for i in range(5)]
    db.update_asset(ids[0], status="FAILED")

    page1 = db.list_assets(skip=0, limit=2)
    page2 = db.list_assets(skip=2, limit=2)
    assert len(page1) == 2 and len(page2) == 2
    assert {a["id_asset"] for a in page1}.isdisjoint({a["id_asset"] for a in page2})
    assert db.count_assets() == 5
    assert db.count_assets(status="FAILED") == 1
    assert db.list_assets(status="FAILED")[0]["id_asset"] == ids[0]


def test_list_logs_global_and_by_asset(db):
    a1 = db.create_asset("a.mp4")
    a2 = db.create_asset("b.mp4")
    db.log_transition(a1, "detection", None, AssetStatus.DETECTED)
    db.log_transition(a2, "detection", None, AssetStatus.DETECTED)
    db.log_transition(a1, "transcription", AssetStatus.DETECTED, AssetStatus.TRANSCRIBING)

    assert db.count_logs() == 3
    assert db.count_logs(asset_id=a1) == 2
    assert len(db.list_logs(asset_id=a1, limit=1)) == 1
    assert all(l["asset_id"] == a1 for l in db.list_logs(asset_id=a1))


def test_log_transition_records_all_fields(db):
    asset_id = db.create_asset("c.mp4")
    db.log_transition(
        asset_id,
        stage="transcription",
        status_from=AssetStatus.DETECTED,
        status_to=AssetStatus.TRANSCRIBING,
        duration_ms=120,
    )
    db.log_transition(
        asset_id,
        stage="transcription",
        status_from=AssetStatus.TRANSCRIBING,
        status_to=AssetStatus.FAILED,
        error_detail="ffmpeg exploded",
    )
    logs = db.get_logs(asset_id)
    assert len(logs) == 2
    assert logs[0]["status_from"] == "DETECTED"
    assert logs[0]["status_to"] == "TRANSCRIBING"
    assert logs[0]["duration_ms"] == 120
    assert logs[1]["error_detail"] == "ffmpeg exploded"
    assert logs[0]["intake_date"] == db.get_asset(asset_id)["intake_date"]
