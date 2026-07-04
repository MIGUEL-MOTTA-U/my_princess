"""Test de integración end-to-end.

Coloca un .mp4 sintético real (generado con ffmpeg) en el watchfolder y
ejecuta el loop completo (`main.run`): detección → registro → dedup →
extracción de audio real con ffmpeg → transcripción (whisper mockeado) →
estructuración (LLM falso) → archivo de salida → PENDING_VALIDATION.
"""
import json
import subprocess
from unittest.mock import patch

import pytest

from my_princess.audio import resolve_ffmpeg
from my_princess.config import Settings
from my_princess.db import Database
from my_princess.main import run
from my_princess.models import AssetStatus
from my_princess.transcriber import TranscriptionResult

METADATA = {
    "title": "Tono de prueba del máster de emisión",
    "summary_short": "Señal de tono para verificación técnica.",
    "summary_long": "El clip contiene un tono de 440 Hz usado para verificar la cadena de emisión.",
    "tags": ["tono", "prueba", "técnica"],
    "staff": [],
    "confidence_score": 0.7,
}


class FakeLLM:
    def complete(self, system, user):
        return json.dumps(METADATA)


@pytest.fixture
def synthetic_mp4(tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    path = watch / "ingest_tone.mp4"
    subprocess.run(
        [
            resolve_ffmpeg(), "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-shortest", str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path


def test_end_to_end_pipeline(tmp_path, synthetic_mp4):
    settings = Settings(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "out",
        approved_dir=tmp_path / "approved",
        db_path=tmp_path / "data" / "demo.db",
        ai_notes_path=tmp_path / "ai_notes.md",
        poll_interval_seconds=0.01,
        max_retries=2,
    )

    fake_result = TranscriptionResult(
        text="Tono de prueba de emisión.", duration_minutes=0.017, language="es"
    )
    # whisper mockeado (sin modelos reales); ffmpeg y todo lo demás es real
    with patch(
        "my_princess.transcriber.Transcriber.transcribe", return_value=fake_result
    ):
        # 3 ciclos: observar tamaño, registrar+procesar, ciclo vacío
        run(settings, cycles=3, llm=FakeLLM())

    db = Database(settings.db_path)
    try:
        asset = db.find_asset_by_source_path(str(synthetic_mp4.resolve()))
        assert asset is not None, "el asset debió registrarse desde el watchfolder"

        # criterio 2: llegó automáticamente a PENDING_VALIDATION
        assert asset["status"] == AssetStatus.PENDING_VALIDATION.value
        assert asset["transcript"] == "Tono de prueba de emisión."
        assert asset["file_hash"]
        assert asset["title"] == METADATA["title"]

        # criterio 3: archivo de salida con transcripción + metadata válida
        out_file = settings.output_dir / f"{asset['id_asset']}.json"
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["transcript"] == asset["transcript"]
        assert payload["metadata"]["confidence_score"] == 0.7

        # criterio 4: una entrada de log por cada transición real
        transitions = [
            (l["status_from"], l["status_to"]) for l in db.get_logs(asset["id_asset"])
        ]
        assert transitions == [
            (None, "DETECTED"),
            ("DETECTED", "TRANSCRIBING"),
            ("TRANSCRIBING", "TRANSCRIBED"),
            ("TRANSCRIBED", "STRUCTURING"),
            ("STRUCTURING", "PENDING_VALIDATION"),
        ]

        # criterio 5: ai_notes.md refleja el mismo historial
        notes = settings.ai_notes_path.read_text(encoding="utf-8")
        assert asset["id_asset"] in notes
        assert "DETECTED" in notes and "PENDING_VALIDATION" in notes
    finally:
        db.close()
