"""Tests del watcher: estabilidad de tamaño, filtro .mp4, idempotencia y hash."""
from my_princess.models import AssetStatus
from my_princess.notes import AINotes
from my_princess.watcher import Watcher, compute_file_hash


def make_watcher(tmp_path, db):
    watch = tmp_path / "watch"
    watch.mkdir()
    notes = AINotes(tmp_path / "ai_notes.md")
    return watch, Watcher(watch, db, notes)


def test_new_file_requires_two_stable_scans(tmp_path, db):
    watch, watcher = make_watcher(tmp_path, db)
    (watch / "video.mp4").write_bytes(b"x" * 100)

    assert watcher.scan() == []  # primer escaneo: solo observa el tamaño
    ids = watcher.scan()  # segundo: tamaño estable -> registra
    assert len(ids) == 1
    asset = db.get_asset(ids[0])
    assert asset["status"] == AssetStatus.DETECTED.value
    assert asset["source_path"].endswith("video.mp4")
    assert db.get_logs(ids[0])[0]["status_to"] == "DETECTED"


def test_growing_file_is_not_registered(tmp_path, db):
    watch, watcher = make_watcher(tmp_path, db)
    target = watch / "growing.mp4"
    target.write_bytes(b"a" * 10)
    watcher.scan()
    target.write_bytes(b"a" * 20)  # sigue creciendo
    assert watcher.scan() == []
    assert watcher.scan() != []  # ya estable


def test_non_mp4_files_ignored(tmp_path, db):
    watch, watcher = make_watcher(tmp_path, db)
    (watch / "notes.txt").write_text("hello")
    (watch / "clip.mov").write_bytes(b"m" * 50)
    watcher.scan()
    assert watcher.scan() == []


def test_already_registered_path_not_duplicated(tmp_path, db):
    watch, watcher = make_watcher(tmp_path, db)
    (watch / "video.mp4").write_bytes(b"x" * 100)
    watcher.scan()
    ids = watcher.scan()
    assert len(ids) == 1
    # ciclos posteriores no crean nuevos assets para el mismo path
    assert watcher.scan() == []
    assert watcher.scan() == []


def test_missing_watch_dir_returns_empty(tmp_path, db):
    notes = AINotes(tmp_path / "ai_notes.md")
    watcher = Watcher(tmp_path / "does-not-exist", db, notes)
    assert watcher.scan() == []


def test_deleted_pending_file_is_forgotten(tmp_path, db):
    watch, watcher = make_watcher(tmp_path, db)
    target = watch / "temp.mp4"
    target.write_bytes(b"z" * 30)
    watcher.scan()
    target.unlink()
    assert watcher.scan() == []
    assert watcher._pending_sizes == {}


def test_compute_file_hash_is_deterministic(tmp_path):
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"same content")
    f2.write_bytes(b"same content")
    assert compute_file_hash(f1) == compute_file_hash(f2)
    f2.write_bytes(b"different")
    assert compute_file_hash(f1) != compute_file_hash(f2)
