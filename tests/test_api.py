"""Tests de la capa REST (FastAPI): TestClient + mongomock, sin servicios reales."""
import io
import json

import mongomock
import pytest
from fastapi.testclient import TestClient

from my_princess.api.app import create_app
from my_princess.config import Settings
from my_princess.db import Database
from my_princess.models import AssetStatus


@pytest.fixture
def api(tmp_path):
    settings = Settings(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "out",
        approved_dir=tmp_path / "approved",
        work_dir=tmp_path / "data",
        ai_notes_path=tmp_path / "ai_notes.md",
        confidence_threshold=0.8,
    )
    db = Database(client=mongomock.MongoClient())
    client = TestClient(create_app(settings=settings, db=db))
    return client, db, settings


def seed_asset(db, status=AssetStatus.PENDING_VALIDATION, path="video.mp4"):
    asset_id = db.create_asset(path)
    db.update_asset(asset_id, status=status, title="Titular", confidence_score=0.9)
    db.log_transition(asset_id, "detection", None, AssetStatus.DETECTED)
    db.log_transition(asset_id, "output", AssetStatus.STRUCTURING, status)
    return asset_id


# -- health ----------------------------------------------------------------

def test_health_ok(api):
    client, _, _ = api
    body = client.get("/api/v1/health").json()
    assert body == {"status": "ok", "database": "up"}


# -- assets ------------------------------------------------------------------

def test_list_assets_empty(api):
    client, _, _ = api
    body = client.get("/api/v1/assets").json()
    assert body == {"items": [], "page": 1, "size": 20, "total_items": 0, "total_pages": 0}


def test_list_assets_pagination_and_filter(api):
    client, db, _ = api
    for i in range(3):
        seed_asset(db, path=f"v{i}.mp4")
    failed = seed_asset(db, status=AssetStatus.FAILED, path="bad.mp4")

    body = client.get("/api/v1/assets", params={"page": 1, "size": 2}).json()
    assert len(body["items"]) == 2
    assert body["total_items"] == 4
    assert body["total_pages"] == 2

    filtered = client.get("/api/v1/assets", params={"status": "FAILED"}).json()
    assert [a["id_asset"] for a in filtered["items"]] == [failed]


def test_list_assets_rejects_invalid_status_and_pagination(api):
    client, _, _ = api
    assert client.get("/api/v1/assets", params={"status": "NOPE"}).status_code == 422
    assert client.get("/api/v1/assets", params={"page": 0}).status_code == 422
    assert client.get("/api/v1/assets", params={"size": 1000}).status_code == 422


def test_get_asset_detail_and_404(api):
    client, db, _ = api
    asset_id = seed_asset(db)
    db.update_asset(asset_id, transcript="texto", tags=["a", "b", "c"])

    body = client.get(f"/api/v1/assets/{asset_id}").json()
    assert body["transcript"] == "texto"
    assert body["tags"] == ["a", "b", "c"]
    assert client.get("/api/v1/assets/no-existe").status_code == 404


# -- trazabilidad ------------------------------------------------------------

def test_asset_logs_paginated_and_404(api):
    client, db, _ = api
    asset_id = seed_asset(db)
    body = client.get(f"/api/v1/assets/{asset_id}/logs").json()
    assert body["total_items"] == 2
    assert all(l["asset_id"] == asset_id for l in body["items"])
    assert client.get("/api/v1/assets/ghost/logs").status_code == 404


def test_global_logs_feed(api):
    client, db, _ = api
    seed_asset(db, path="a.mp4")
    seed_asset(db, path="b.mp4")
    body = client.get("/api/v1/logs", params={"size": 3}).json()
    assert body["total_items"] == 4
    assert len(body["items"]) == 3


# -- carga de videos ---------------------------------------------------------

def test_upload_video_lands_in_watchfolder(api):
    client, _, settings = api
    response = client.post(
        "/api/v1/videos",
        files={"file": ("clip.mp4", io.BytesIO(b"fake-bytes"), "video/mp4")},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "clip.mp4"
    assert (settings.watch_dir / "clip.mp4").read_bytes() == b"fake-bytes"


def test_upload_rejects_non_mp4(api):
    client, _, _ = api
    response = client.post(
        "/api/v1/videos",
        files={"file": ("document.pdf", io.BytesIO(b"x"), "application/pdf")},
    )
    assert response.status_code == 400


def test_upload_duplicate_name_conflicts(api):
    client, _, _ = api
    upload = {"file": ("same.mp4", io.BytesIO(b"x"), "video/mp4")}
    assert client.post("/api/v1/videos", files=upload).status_code == 201
    upload = {"file": ("same.mp4", io.BytesIO(b"y"), "video/mp4")}
    assert client.post("/api/v1/videos", files=upload).status_code == 409


def test_upload_sanitizes_path_traversal(api):
    client, _, settings = api
    response = client.post(
        "/api/v1/videos",
        files={"file": ("..\\..\\evil.mp4", io.BytesIO(b"x"), "video/mp4")},
    )
    assert response.status_code == 201
    assert (settings.watch_dir / "evil.mp4").exists()


# -- salidas -----------------------------------------------------------------

def write_output(settings, folder, asset_id, payload=None):
    path = getattr(settings, f"{'approved' if folder == 'approved' else 'output'}_dir")
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{asset_id}.json").write_text(
        json.dumps(payload or {"id_asset": asset_id}), encoding="utf-8"
    )


def test_list_outputs_by_folder(api):
    client, _, settings = api
    write_output(settings, "approved", "aaa")
    write_output(settings, "output", "bbb")

    approved = client.get("/api/v1/outputs/approved").json()
    assert [f["asset_id"] for f in approved["items"]] == ["aaa"]
    assert approved["items"][0]["folder"] == "approved"

    standard = client.get("/api/v1/outputs/output").json()
    assert [f["asset_id"] for f in standard["items"]] == ["bbb"]

    assert client.get("/api/v1/outputs/otra").status_code == 422  # enum invalido


def test_get_output_content_and_404(api):
    client, _, settings = api
    write_output(settings, "approved", "ccc", {"id_asset": "ccc", "transcript": "hola"})
    body = client.get("/api/v1/outputs/approved/ccc").json()
    assert body["transcript"] == "hola"
    assert client.get("/api/v1/outputs/approved/nope").status_code == 404


# -- configuracion dinamica ----------------------------------------------------

def test_config_defaults_to_env_value(api):
    client, _, _ = api
    body = client.get("/api/v1/config").json()
    assert body == {"confidence_threshold": 0.8, "source": "env_default"}


def test_config_update_is_dynamic_and_validated(api):
    client, db, _ = api
    response = client.put("/api/v1/config", json={"confidence_threshold": 0.95})
    assert response.status_code == 200
    assert response.json() == {"confidence_threshold": 0.95, "source": "dynamic"}
    # persiste donde el pipeline lo lee
    assert db.get_config_value("confidence_threshold") == 0.95
    # fuera de rango -> validacion pydantic
    assert client.put("/api/v1/config", json={"confidence_threshold": 1.5}).status_code == 422
