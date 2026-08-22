"""Contrat cible commun aux backends de perception, sans migration runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Protocol

import numpy as np


@dataclass
class PerceptionResult:
    id: str
    confidence: float
    backend: str
    timestamp: float = field(default_factory=time.time)
    corners: np.ndarray | None = None
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence doit être comprise entre 0 et 1")


class PerceptionBackend(Protocol):
    name: str

    def detect(self, frame: np.ndarray) -> list[PerceptionResult]: ...
