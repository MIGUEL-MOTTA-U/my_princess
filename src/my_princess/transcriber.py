"""Transcripcion con faster-whisper.

El modelo se importa y carga de forma perezosa para que los tests (que
mockean `transcribe`) no necesiten el paquete ni descargar pesos.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TranscriptionError(Exception):
    pass


@dataclass
class TranscriptionResult:
    text: str
    duration_minutes: float
    language: str | None = None


class Transcriber:
    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        self._model = None

    def _load_model(self):  # pragma: no cover - descarga/carga real del modelo
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio_path: Path | str) -> TranscriptionResult:
        try:
            model = self._load_model()
            segments, info = model.transcribe(str(audio_path))
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return TranscriptionResult(
                text=text,
                duration_minutes=round((info.duration or 0.0) / 60.0, 3),
                language=info.language,
            )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"faster-whisper fallo: {exc}") from exc
