"""Métriques spécifiques au benchmark L1 v2 et simulation du hold STYX."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import math

import numpy as np

from .metrics import classify
from ..temporal import TemporalCardValidator


@dataclass
class L1FrameMetric:
    sample_id: str
    sequence_id: str
    frame_index: int
    timestamp_s: float
    strategy: str
    recognition_variant: str
    homography_requested: str
    homography_backend: str
    object_expected: str | None
    object_detected: str | None
    condition: str
    contour_found: bool
    roi_source: str
    fallback_used: bool
    l1_quality: float
    l1_regularity: float
    l1_area_ratio: float
    l1_area_score: float
    l1_edge_support: float
    l1_contrast: float
    l1_temporal_stability: float
    tracking_quality: float | None
    roi_x: int | None
    roi_y: int | None
    roi_width: int | None
    roi_height: int | None
    l1_latency_ms: float
    l2_latency_ms: float
    l3_latency_ms: float
    total_latency_ms: float
    l2_success: bool
    l3_success: bool
    matches: int = 0
    inliers: int = 0
    inlier_ratio: float = 0.0
    reprojection_error: float | None = None
    top1: str | None = None
    top2: str | None = None
    top1_top2_margin: float | None = None
    score: float = 0.0
    threshold_used: float | None = None
    true_positive: bool = False
    true_negative: bool = False
    false_positive: bool = False
    false_negative: bool = False
    miss_streak: int = 0
    longest_miss_streak: int = 0
    time_to_first_detection: float | None = None
    trigger_id: str | None = None
    time_to_trigger: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class HoldSimulator:
    """Reproduit la validation temporelle de ``apps/rpi/main.py``.

    Une première reconnaissance établit l'identité candidate. Le hold ne
    démarre que sur une reconnaissance suivante, comme dans le runtime actuel.
    """

    def __init__(
        self,
        hold_ms: int = 1000,
        consecutive_frames: int = 1,
        miss_grace_frames: int = 5,
    ):
        self.validator = TemporalCardValidator(
            hold_ms, consecutive_frames, miss_grace_frames
        )
        self.triggered = False

    def reset(self) -> None:
        self.validator.reset()
        self.triggered = False

    def update(self, detected: str | None, timestamp_s: float) -> str | None:
        if self.triggered:
            return None
        if detected is None:
            self.validator.register_miss()
            return None
        decision = self.validator.register_detection(detected, timestamp_s)
        if decision.triggered:
            self.triggered = True
            return detected
        return None


class L1MetricsAccumulator:
    def __init__(self) -> None:
        self.rows: list[L1FrameMetric] = []

    def add(self, metric: L1FrameMetric) -> None:
        self.rows.append(metric)

    def grouped_summary(self) -> list[dict]:
        groups = defaultdict(list)
        for row in self.rows:
            groups[
                (row.strategy, row.recognition_variant, row.homography_requested)
            ].append(row)
        return [
            {
                "strategy": key[0],
                "recognition_variant": key[1],
                "homography_requested": key[2],
                **summarize_l1_metrics(rows),
            }
            for key, rows in sorted(groups.items())
        ]


def summarize_l1_metrics(rows: list[L1FrameMetric]) -> dict:
    total = len(rows)
    positives = sum(row.object_expected is not None for row in rows)
    negatives = total - positives
    tp = sum(row.true_positive for row in rows)
    fp = sum(row.false_positive for row in rows)
    fn = sum(row.false_negative for row in rows)
    detections = sum(row.object_detected is not None for row in rows)
    fallback_rows = [row for row in rows if row.fallback_used]
    positive_sequences = _sequences(rows, positive=True)
    negative_sequences = _sequences(rows, positive=False)
    presentation_hits = sum(
        any(row.true_positive for row in sequence) for sequence in positive_sequences
    )
    correct_triggers = sum(
        any(row.trigger_id == row.object_expected for row in sequence)
        for sequence in positive_sequences
    )
    wrong_triggers = sum(
        any(
            row.trigger_id is not None and row.trigger_id != row.object_expected
            for row in sequence
        )
        for sequence in positive_sequences
    )
    negative_triggers = sum(
        any(row.trigger_id is not None for row in sequence)
        for sequence in negative_sequences
    )
    detection_times = [
        next(row.timestamp_s for row in sequence if row.true_positive)
        for sequence in positive_sequences
        if any(row.true_positive for row in sequence)
    ]
    trigger_times = [
        row.time_to_trigger
        for row in rows
        if row.time_to_trigger is not None and row.trigger_id == row.object_expected
    ]
    source_counts = defaultdict(int)
    source_correct = defaultdict(int)
    for row in rows:
        source_counts[row.roi_source] += 1
        source_correct[row.roi_source] += int(row.true_positive)
    by_condition = {}
    for condition in sorted({row.condition for row in rows}):
        selected = [row for row in rows if row.condition == condition]
        selected_pos = sum(row.object_expected is not None for row in selected)
        by_condition[condition] = {
            "samples": len(selected),
            "recall": _ratio(sum(row.true_positive for row in selected), selected_pos),
            "contour_hit_rate": _ratio(
                sum(row.contour_found for row in selected), len(selected)
            ),
            "fallback_rate": _ratio(
                sum(row.fallback_used for row in selected), len(selected)
            ),
        }
    by_object = {}
    for object_id in sorted(
        {row.object_expected for row in rows if row.object_expected is not None}
    ):
        selected = [row for row in rows if row.object_expected == object_id]
        sequences = _group_sequences(selected)
        by_object[object_id] = {
            "samples": len(selected),
            "recall": _ratio(sum(row.true_positive for row in selected), len(selected)),
            "presentations": len(sequences),
            "presentation_detection_rate": _ratio(
                sum(
                    any(row.true_positive for row in sequence) for sequence in sequences
                ),
                len(sequences),
            ),
            "trigger_success_rate": _ratio(
                sum(
                    any(row.trigger_id == object_id for row in sequence)
                    for sequence in sequences
                ),
                len(sequences),
            ),
        }
    confusion = defaultdict(lambda: defaultdict(int))
    for row in rows:
        confusion[row.object_expected or "<negative>"][
            row.object_detected or "<none>"
        ] += 1
    return {
        "samples": total,
        "positive_samples": positives,
        "negative_samples": negatives,
        "recall": _ratio(tp, positives),
        "precision": _ratio(tp, detections),
        "false_positive_rate": _ratio(
            sum(
                row.object_expected is None and row.object_detected is not None
                for row in rows
            ),
            negatives,
        ),
        "false_negative_rate": _ratio(fn, positives),
        "false_positives": fp,
        "false_negatives": fn,
        "contour_hit_rate": _ratio(sum(row.contour_found for row in rows), total),
        "fallback_rate": _ratio(len(fallback_rows), total),
        "fallback_precision": _ratio(
            sum(row.true_positive for row in fallback_rows),
            sum(row.object_detected is not None for row in fallback_rows),
        ),
        "presentation_count": len(positive_sequences),
        "presentation_detection_rate": _ratio(
            presentation_hits, len(positive_sequences)
        ),
        "trigger_success_rate": _ratio(correct_triggers, len(positive_sequences)),
        "wrong_trigger_rate": _ratio(wrong_triggers, len(positive_sequences)),
        "negative_trigger_rate": _ratio(negative_triggers, len(negative_sequences)),
        "time_to_first_detection_p50": _percentile(detection_times, 50),
        "time_to_first_detection_p95": _percentile(detection_times, 95),
        "time_to_trigger_p50": _percentile(trigger_times, 50),
        "time_to_trigger_p95": _percentile(trigger_times, 95),
        "longest_miss_streak": max(
            (row.longest_miss_streak for row in rows), default=0
        ),
        "latency_ms_p50": _percentile([row.total_latency_ms for row in rows], 50),
        "latency_ms_p95": _percentile([row.total_latency_ms for row in rows], 95),
        "mean_l1_quality": (
            float(np.mean([row.l1_quality for row in rows])) if rows else None
        ),
        "roi_sources": {
            source: {
                "samples": count,
                "correct": source_correct[source],
                "recall_contribution": _ratio(source_correct[source], positives),
            }
            for source, count in sorted(source_counts.items())
        },
        "recall_by_object": by_object,
        "metrics_by_condition": by_condition,
        "confusion": {key: dict(value) for key, value in confusion.items()},
    }


def set_classification(metric: L1FrameMetric) -> None:
    for name, value in classify(metric.object_expected, metric.object_detected).items():
        setattr(metric, name, value)


def _sequences(
    rows: list[L1FrameMetric], *, positive: bool
) -> list[list[L1FrameMetric]]:
    selected = [row for row in rows if (row.object_expected is not None) is positive]
    return _group_sequences(selected)


def _group_sequences(rows: list[L1FrameMetric]) -> list[list[L1FrameMetric]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.object_expected, row.condition, row.sequence_id)].append(row)
    result = []
    for sequence in grouped.values():
        sequence.sort(key=lambda row: row.frame_index)
        result.append(sequence)
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    value = float(np.percentile(values, percentile))
    return None if math.isnan(value) else value
