"""Extraccion de audio con ffmpeg.

Resuelve el binario de ffmpeg desde el PATH y, si no existe (caso tipico en
Windows sin instalacion manual), usa el binario empaquetado por
`imageio-ffmpeg`. Asi la demo corre sin pasos de instalacion extra.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AudioExtractionError(Exception):
    pass


def resolve_ffmpeg() -> str:
    if binary := shutil.which("ffmpeg"):
        return binary
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depende del entorno
        raise AudioExtractionError(
            "ffmpeg no disponible: instala ffmpeg o el paquete imageio-ffmpeg"
        ) from exc


def extract_audio(video_path: Path | str, output_dir: Path | str) -> Path:
    """Extrae la pista de audio a WAV mono 16 kHz (formato optimo para
    whisper). Devuelve la ruta del WAV generado."""
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = output_dir / (video_path.stem + ".wav")

    command = [
        resolve_ffmpeg(),
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(wav_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not wav_path.exists():
        raise AudioExtractionError(
            f"ffmpeg fallo (codigo {result.returncode}): {result.stderr[-500:]}"
        )
    return wav_path
