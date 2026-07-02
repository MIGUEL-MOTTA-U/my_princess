"""Deteccion de videos nuevos en el watchfolder.

Estrategia: polling con intervalo configurable (sin watchdog/inotify — para
una demo el polling es portable, testeable y suficiente; ver DECISIONS.md).
Un archivo se considera "estable" cuando su tamano no cambia entre dos
escaneos consecutivos, para no procesar archivos que aun se estan copiando.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .db import Database
from .models import AssetStatus
from .notes import AINotes


def compute_file_hash(path: Path | str, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class Watcher:
    """Escanea el watchfolder y registra assets nuevos en estado DETECTED."""

    def __init__(self, watch_dir: Path | str, db: Database, notes: AINotes):
        self.watch_dir = Path(watch_dir)
        self.db = db
        self.notes = notes
        # tamano observado en el escaneo anterior, por ruta
        self._pending_sizes: dict[str, int] = {}

    def scan(self) -> list[str]:
        """Un ciclo de escaneo. Devuelve los id_asset de los archivos nuevos
        registrados (ya estables). Los archivos aun creciendo quedan pendientes
        para el siguiente ciclo."""
        new_asset_ids: list[str] = []
        if not self.watch_dir.exists():
            return new_asset_ids

        seen_paths: set[str] = set()
        for path in sorted(self.watch_dir.glob("*.mp4")):
            if not path.is_file():
                continue
            key = str(path.resolve())
            seen_paths.add(key)

            # ya registrado en la base: no volver a crear un asset por el
            # mismo archivo en cada ciclo de polling
            if self.db.find_asset_by_source_path(key):
                continue

            size = path.stat().st_size
            previous = self._pending_sizes.get(key)
            if previous is None or previous != size:
                # primera vez que lo vemos, o sigue siendo escrito
                self._pending_sizes[key] = size
                continue

            del self._pending_sizes[key]
            asset_id = self.db.create_asset(key)
            self.db.log_transition(
                asset_id, stage="detection", status_from=None,
                status_to=AssetStatus.DETECTED,
            )
            self.notes.log(
                asset_id, "detection",
                f"Archivo nuevo detectado y estable: `{path.name}` ({size} bytes)",
                transition="∅ → DETECTED",
            )
            new_asset_ids.append(asset_id)

        # olvidar pendientes que desaparecieron del folder
        self._pending_sizes = {
            k: v for k, v in self._pending_sizes.items() if k in seen_paths
        }
        return new_asset_ids
