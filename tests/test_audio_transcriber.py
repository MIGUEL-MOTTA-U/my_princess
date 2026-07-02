"""Tests de extracción de audio (ffmpeg real, sintético) y del wrapper de
faster-whisper (mockeado — sin cargar modelos reales)."""
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from my_princess.audio import AudioExtractionError, extract_audio, resolve_ffmpeg
from my_princess.transcriber import Transcriber, TranscriptionError


@pytest.fixture(scope="module")
def synthetic_mp4(tmp_path_factory):
    """Genera un mp4 corto (1s de tono) con el ffmpeg empaquetado."""
    path = tmp_path_factory.mktemp("media") / "tone.mp4"
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


def test_extract_audio_produces_wav(tmp_path, synthetic_mp4):
    wav = extract_audio(synthetic_mp4, tmp_path / "audio")
    assert wav.exists()
    assert wav.suffix == ".wav"
    assert wav.stat().st_size > 1000


def test_extract_audio_fails_on_invalid_input(tmp_path):
    bogus = tmp_path / "not_a_video.mp4"
    bogus.write_bytes(b"this is not an mp4")
    with pytest.raises(AudioExtractionError):
        extract_audio(bogus, tmp_path / "audio")


def test_transcriber_joins_segments_and_reports_duration():
    transcriber = Transcriber(model_name="base")
    segments = [SimpleNamespace(text=" Hola "), SimpleNamespace(text="mundo. ")]
    info = SimpleNamespace(duration=90.0, language="es")
    model = MagicMock()
    model.transcribe.return_value = (iter(segments), info)

    with patch.object(transcriber, "_load_model", return_value=model):
        result = transcriber.transcribe("audio.wav")

    assert result.text == "Hola mundo."
    assert result.duration_minutes == 1.5
    assert result.language == "es"


def test_transcriber_wraps_errors():
    transcriber = Transcriber()
    with patch.object(transcriber, "_load_model", side_effect=RuntimeError("boom")):
        with pytest.raises(TranscriptionError, match="boom"):
            transcriber.transcribe("audio.wav")


def test_transcriber_handles_none_duration():
    transcriber = Transcriber()
    info = SimpleNamespace(duration=None, language=None)
    model = MagicMock()
    model.transcribe.return_value = (iter([]), info)
    with patch.object(transcriber, "_load_model", return_value=model):
        result = transcriber.transcribe("audio.wav")
    assert result.text == ""
    assert result.duration_minutes == 0.0
