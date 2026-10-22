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
    """kind : "ok" = carte validée ; "L1"/"L2"/"L3" = rejet à cet étage du
    pipeline (L1 aucun contour, L2 contour sans carte, L3 score sous le seuil).
    Chaque kind a son propre débit et sa propre rotation : une rafale de rejets
    ne chasse jamais les snapshots de cartes validées."""

    def __init__(
        self,
        directory: str = DEFAULT_DIR,
        max_files: int = 50,
        min_interval_s: float = 5.0,
        jpeg_quality: int = 80,
        queue_size: int = 1,
        reject_max_files: int = 30,
        reject_interval_s: float = 10.0,
        l1_interval_s: float = 0.0,
    ):
        super().__init__(daemon=True, name="snapshots")
        self.directory = Path(directory)
        self.max_files = max(1, int(max_files))
        self.reject_max_files = max(1, int(reject_max_files))
        self.min_interval_s = float(min_interval_s)
        self.jpeg_quality = int(jpeg_quality)
        # None = kind désactivé. L1 est le cas "scène vide" le plus fréquent :
        # échantillonnage lent, éteint par défaut.
        self._intervals = {
            "ok": self.min_interval_s,
            "L2": float(reject_interval_s),
            "L3": float(reject_interval_s),
            "L1": float(l1_interval_s) if l1_interval_s > 0 else None,
        }
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, queue_size))
        self._stop_event = threading.Event()
        self._last_submit: dict[str, float] = {}
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
            reject_max_files=cfg.get("snapshot_reject_max_files", 30),
            reject_interval_s=cfg.get("snapshot_reject_interval_s", 10.0),
            l1_interval_s=cfg.get("snapshot_l1_interval_s", 0.0),
        )

    def submit(
        self,
        frame,
        card_id: str,
        score: float,
        now: float | None = None,
        kind: str = "ok",
    ) -> bool:
        """Non bloquant. True si la frame a été mise en file."""
        interval = self._intervals.get(kind)
        if interval is None:
            return False
        now = time.time() if now is None else now
        if now - self._last_submit.get(kind, float("-inf")) < interval:
            return False
        try:
            self._queue.put_nowait((frame.copy(), card_id, score, now, kind))
        except queue.Full:
            self.dropped += 1
            return False
        self._last_submit[kind] = now
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

    def _write(
        self, frame, card_id: str, score: float, ts: float, kind: str = "ok"
    ) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts))
        millis = int((ts % 1) * 1000)
        name = f"{stamp}_{millis:03d}_{kind}_{_SAFE.sub('_', card_id)}_{score:.2f}.jpg"
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
        self._rotate(kind)
        log.info(f"[snapshot] {final}")
        return final

    def _rotate(self, kind: str = "ok") -> None:
        limit = self.max_files if kind == "ok" else self.reject_max_files
        files = sorted(self.directory.glob(f"*_{kind}_*.jpg"))
        for old in files[: max(0, len(files) - limit)]:
            try:
                old.unlink()
            except OSError:
                pass
