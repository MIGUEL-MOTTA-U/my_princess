"""Tests de la capa de persistencia (assets + transform_logs)."""
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
