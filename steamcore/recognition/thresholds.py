"""Résolution rétrocompatible des seuils globaux et par objet."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecognitionThresholds:
    default_threshold: float = 0.20
    use_per_object_thresholds: bool = False
    object_thresholds: dict[str, float] = field(default_factory=dict)

    def resolve(self, object_id: str | None = None) -> float:
        if self.use_per_object_thresholds and object_id is not None:
            return self.object_thresholds.get(object_id, self.default_threshold)
        return self.default_threshold

    def set_object_threshold(self, object_id: str, threshold: float) -> None:
        self.object_thresholds[object_id] = _validate_threshold(threshold)

    def reset_object_threshold(self, object_id: str) -> None:
        self.object_thresholds.pop(object_id, None)

    @classmethod
    def from_config(
        cls, cfg: dict, legacy_default: float = 0.20
    ) -> RecognitionThresholds:
        recognition = cfg.get("recognition", {}) or {}
        default = recognition.get(
            "default_threshold", cfg.get("card_score_threshold", legacy_default)
        )
        object_thresholds = {}
        for object_id, object_cfg in (cfg.get("objects", {}) or {}).items():
            if isinstance(object_cfg, dict) and "threshold" in object_cfg:
                object_thresholds[object_id] = _validate_threshold(
                    object_cfg["threshold"]
                )
        return cls(
            default_threshold=_validate_threshold(default),
            use_per_object_thresholds=bool(
                recognition.get("use_per_object_thresholds", False)
            ),
            object_thresholds=object_thresholds,
        )


def _validate_threshold(value: float) -> float:
    threshold = float(value)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("Un seuil de reconnaissance doit être compris entre 0 et 1")
    return threshold
