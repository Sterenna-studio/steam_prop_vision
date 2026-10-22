"""
apps/rpi/motion_gate.py
Porte de mouvement : évite le pipeline L1/L2/L3 quand la scène est figée.

La salle est vide l'essentiel du temps : relancer détection de contours, ORB et
matching sur une image qui n'a pas changé est du calcul perdu. La porte compare
chaque frame à la précédente sur une miniature (quelques centaines de pixels,
coût négligeable) et ne laisse passer que :
- les frames où la scène bouge (carte posée/retirée, main) et les `linger_s`
  secondes qui suivent (le temps que la scène se stabilise) ;
- toutes les frames tant qu'un candidat est en cours de validation (`force`) ;
- une frame de contrôle toutes les `idle_interval_s` même sans mouvement, pour
  ne jamais rater une carte laissée en place (ex : après un retour en IDLE).

Pure (numpy/cv2, aucune caméra) : testable hors Pi. Désactivée par défaut.
"""

from __future__ import annotations

import cv2
import numpy as np


class MotionGate:
    def __init__(
        self,
        pixel_delta: int = 12,
        changed_ratio: float = 0.01,
        linger_s: float = 2.0,
        idle_interval_s: float = 1.0,
        size: tuple[int, int] = (64, 36),
    ):
        self.pixel_delta = int(pixel_delta)
        self.changed_ratio = float(changed_ratio)
        self.linger_s = float(linger_s)
        self.idle_interval_s = float(idle_interval_s)
        self.size = size
        self._prev: np.ndarray | None = None
        self._last_motion = float("-inf")
        self._last_pass = float("-inf")
        self.passed = 0
        self.skipped = 0

    @classmethod
    def from_config(cls, cfg: dict) -> MotionGate | None:
        """None si la fonctionnalité est désactivée (défaut)."""
        if not cfg.get("enable_motion_gate", False):
            return None
        return cls(
            pixel_delta=cfg.get("motion_gate_pixel_delta", 12),
            changed_ratio=cfg.get("motion_gate_changed_ratio", 0.01),
            linger_s=cfg.get("motion_gate_linger_s", 2.0),
            idle_interval_s=cfg.get("motion_gate_idle_interval_s", 1.0),
        )

    def _thumb(self, frame: np.ndarray) -> np.ndarray:
        small = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(small, (3, 3), 0)

    def motion_ratio(self, frame: np.ndarray) -> float:
        """Fraction de la miniature qui a changé depuis la frame précédente
        (0.0 pour la toute première frame). Met à jour la référence."""
        thumb = self._thumb(frame)
        prev, self._prev = self._prev, thumb
        if prev is None:
            return 0.0
        return float(np.mean(cv2.absdiff(thumb, prev) > self.pixel_delta))

    def should_process(
        self, frame: np.ndarray, now: float, force: bool = False
    ) -> bool:
        first = self._prev is None
        if self.motion_ratio(frame) >= self.changed_ratio:
            self._last_motion = now
        go = (
            first
            or force
            or now - self._last_motion <= self.linger_s
            or now - self._last_pass >= self.idle_interval_s
        )
        if go:
            self._last_pass = now
            self.passed += 1
        else:
            self.skipped += 1
        return go

    @property
    def skip_ratio(self) -> float:
        total = self.passed + self.skipped
        return self.skipped / total if total else 0.0
