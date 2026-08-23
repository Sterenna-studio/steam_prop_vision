"""Validation temporelle pure et partagée entre runtime et benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TemporalStatus(str, Enum):
    NO_CANDIDATE = "no_candidate"
    MISS_TOLERATED = "miss_tolerated"
    RESET_AFTER_MISS = "reset_after_miss"
    NEW_CANDIDATE = "new_candidate"
    ACCUMULATING = "accumulating"
    HOLD_STARTED = "hold_started"
    HOLDING = "holding"
    TRIGGERED = "triggered"


@dataclass(frozen=True)
class TemporalDecision:
    status: TemporalStatus
    card_id: str | None = None
    held_ms: float = 0.0
    miss_count: int = 0
    consecutive_count: int = 0
    started_hold: bool = False

    @property
    def hold_started(self) -> bool:
        return self.started_hold

    @property
    def triggered(self) -> bool:
        return self.status == TemporalStatus.TRIGGERED


class TemporalCardValidator:
    """État du hold actuel de STYX, sans caméra ni effets externes."""

    def __init__(
        self,
        hold_ms: int = 1000,
        consecutive_frames: int = 1,
        miss_grace_frames: int = 5,
    ):
        if hold_ms < 0 or consecutive_frames < 1 or miss_grace_frames < 0:
            raise ValueError("Configuration de validation temporelle invalide")
        self.hold_ms = hold_ms
        self.consecutive_frames = consecutive_frames
        self.miss_grace_frames = miss_grace_frames
        self.reset()

    def reset(self) -> None:
        self.hold_card_id: str | None = None
        self.hold_start_s: float | None = None
        self.consecutive_card_id: str | None = None
        self.consecutive_count = 0
        self.miss_count = 0

    def register_miss(self) -> TemporalDecision:
        if self.consecutive_card_id is None:
            return TemporalDecision(TemporalStatus.NO_CANDIDATE)
        self.miss_count += 1
        if self.miss_count > self.miss_grace_frames:
            missed = self.miss_count
            self.reset()
            return TemporalDecision(TemporalStatus.RESET_AFTER_MISS, miss_count=missed)
        return TemporalDecision(
            TemporalStatus.MISS_TOLERATED,
            card_id=self.consecutive_card_id,
            miss_count=self.miss_count,
            consecutive_count=self.consecutive_count,
        )

    def register_detection(self, card_id: str, timestamp_s: float) -> TemporalDecision:
        if not card_id:
            raise ValueError("card_id ne peut pas être vide")
        if card_id != self.consecutive_card_id:
            self.consecutive_card_id = card_id
            self.consecutive_count = 1
            self.hold_card_id = None
            self.hold_start_s = None
            self.miss_count = 0
            return self._decision(TemporalStatus.NEW_CANDIDATE, card_id)

        self.miss_count = 0
        self.consecutive_count += 1
        if self.consecutive_count < self.consecutive_frames:
            return self._decision(TemporalStatus.ACCUMULATING, card_id)
        if self.hold_card_id is None:
            self.hold_card_id = card_id
            self.hold_start_s = timestamp_s
            status = (
                TemporalStatus.TRIGGERED
                if self.hold_ms == 0
                else TemporalStatus.HOLD_STARTED
            )
            return self._decision(status, card_id, started_hold=True)

        held_ms = max(0.0, (timestamp_s - self.hold_start_s) * 1000.0)
        status = (
            TemporalStatus.TRIGGERED
            if held_ms >= self.hold_ms
            else TemporalStatus.HOLDING
        )
        return self._decision(status, card_id, held_ms)

    def _decision(
        self,
        status: TemporalStatus,
        card_id: str,
        held_ms: float = 0.0,
        *,
        started_hold: bool = False,
    ) -> TemporalDecision:
        return TemporalDecision(
            status=status,
            card_id=card_id,
            held_ms=held_ms,
            miss_count=self.miss_count,
            consecutive_count=self.consecutive_count,
            started_hold=started_hold,
        )
