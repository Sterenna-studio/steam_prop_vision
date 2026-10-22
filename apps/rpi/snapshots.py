"""
apps/rpi/snapshots.py
Snapshots JPEG des détections validées, pour diagnostic a posteriori.

Contraintes de conception (STYX tourne ~10 ans sur carte SD, avec un watchdog
anti-freeze) :
- écriture dans un thread dédié : la boucle caméra ne paie jamais l'encodage
  JPEG ni l'I/O, donc le watchdog n'est pas déclenché par un snapshot ;
- file bornée (1 par défaut) : si l'écriture traîne, le snapshot en trop est
  abandonné plutôt que de bloquer ou d'accumuler de la mémoire ;
- débit limité (min_interval_s) et rotation (max_files) : écritures et
  espace disque bornés, quoi qu'il arrive en amont ;
- dossier par défaut en RAM (/dev/shm) : aucune usure de la carte SD, au prix
  d'une perte au reboot. Pointer snapshot_dir vers une clé USB pour conserver.

Aucune dépendance picamera2 : importable et testable hors Pi.
"""

from __future__ import annotations
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path

import cv2

log = logging.getLogger("steam")

DEFAULT_DIR = "/dev/shm/steam_snapshots"
_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


class SnapshotWriter(threading.Thread):
    def __init__(
        self,
        directory: str = DEFAULT_DIR,
        max_files: int = 50,
        min_interval_s: float = 5.0,
        jpeg_quality: int = 80,
        queue_size: int = 1,
    ):
        super().__init__(daemon=True, name="snapshots")
        self.directory = Path(directory)
        self.max_files = max(1, int(max_files))
        self.min_interval_s = float(min_interval_s)
        self.jpeg_quality = int(jpeg_quality)
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, queue_size))
        self._stop_event = threading.Event()
        self._last_submit = float("-inf")
        self.written = 0
        self.dropped = 0

    @classmethod
    def from_config(cls, cfg: dict) -> SnapshotWriter | None:
        """None si la fonctionnalité est désactivée (défaut)."""
        if not cfg.get("enable_snapshots", False):
            return None
        return cls(
            directory=cfg.get("snapshot_dir", DEFAULT_DIR),
            max_files=cfg.get("snapshot_max_files", 50),
            min_interval_s=cfg.get("snapshot_min_interval_s", 5.0),
            jpeg_quality=cfg.get("snapshot_jpeg_quality", 80),
        )

    def submit(
        self, frame, card_id: str, score: float, now: float | None = None
    ) -> bool:
        """Non bloquant. True si la frame a été mise en file."""
        now = time.time() if now is None else now
        if now - self._last_submit < self.min_interval_s:
            return False
        try:
            self._queue.put_nowait((frame.copy(), card_id, score, now))
        except queue.Full:
            self.dropped += 1
            return False
        self._last_submit = now
        return True

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._write(*item)
            except Exception:
                log.exception("[snapshot] échec d'écriture")

    def stop(self) -> None:
        self._stop_event.set()

    def _write(self, frame, card_id: str, score: float, ts: float) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        millis = int((ts % 1) * 1000)
        name = f"{stamp}_{millis:03d}_{_SAFE.sub('_', card_id)}_{score:.2f}.jpg"
        final = self.directory / name
        tmp = final.with_suffix(".tmp")
        ok, buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        )
        if not ok:
            raise RuntimeError("encodage JPEG impossible")
        tmp.write_bytes(buf.tobytes())
        os.replace(tmp, final)
        self.written += 1
        self._rotate()
        log.info(f"[snapshot] {final}")
        return final

    def _rotate(self) -> None:
        files = sorted(self.directory.glob("*.jpg"))
        for old in files[: max(0, len(files) - self.max_files)]:
            try:
                old.unlink()
            except OSError:
                pass
