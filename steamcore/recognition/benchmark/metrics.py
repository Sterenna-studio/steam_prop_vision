"""Métriques détaillées et agrégation compacte benchmark/runtime."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import math

import numpy as np


@dataclass
class VisionMetric:
    sample_id: str
    sequence_id: str
    frame_index: int
    timestamp_s: float
    backend: str
    variant: str
    homography_backend: str
    homography_requested: str
    homography_fallback_used: bool
    object_expected: str | None
    object_detected: str | None
    condition: str
    l1_hit: bool
    l1_miss: bool
    l2_success: bool
    l2_fail: bool
    l2_latency_ms: float
    l3_success: bool
    l3_fail: bool
    l3_latency_ms: float
    matches: int = 0
    inliers: int = 0
    inlier_ratio: float = 0.0
    reprojection_error: float | None = None
    quadrilateral_area: float | None = None
    geometry_valid: bool = False
    top1: str | None = None
    top2: str | None = None
    top1_score: float | None = None
    top2_score: float | None = None
    top1_top2_margin: float | None = None
    final_candidate: str | None = None
    l3_best_candidate: str | None = None
    l3_corrected_top1: bool = False
    score: float = 0.0
    threshold_used: float | None = None
    true_positive: bool = False
    true_negative: bool = False
    false_positive: bool = False
    false_negative: bool = False
    total_latency_ms: float = 0.0
    cpu_percent: float | None = None
    ram_mb: float | None = None
    fps: float | None = None
    time_to_first_detection: float | None = None
    time_to_trigger: float | None = None
    miss_streak: int = 0
    longest_miss_streak: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class VisionMetricsAccumulator:
    """Accumule les frames sans écrire un log par frame en production."""

    def __init__(self) -> None:
        self.rows: list[VisionMetric] = []

    def add(self, metric: VisionMetric) -> None:
        self.rows.append(metric)

    def summary(self) -> dict:
        return summarize_metrics(self.rows)

    def grouped_summary(self) -> list[dict]:
        groups = defaultdict(list)
        for row in self.rows:
            groups[(row.variant, row.backend, row.homography_requested)].append(row)
        return [
            {
                "variant": key[0],
                "backend": key[1],
                "homography_requested": key[2],
                **summarize_metrics(rows),
            }
            for key, rows in sorted(groups.items())
        ]


def summarize_metrics(rows: list[VisionMetric]) -> dict:
    total = len(rows)
    positives = sum(row.object_expected is not None for row in rows)
    negatives = total - positives
    true_positives = sum(row.true_positive for row in rows)
    true_negatives = sum(row.true_negative for row in rows)
    false_positives = sum(row.false_positive for row in rows)
    false_negatives = sum(row.false_negative for row in rows)
    detections = sum(row.object_detected is not None for row in rows)

    by_object = {}
    object_ids = sorted(
        {row.object_expected for row in rows if row.object_expected is not None}
    )
    for object_id in object_ids:
        object_rows = [row for row in rows if row.object_expected == object_id]
        correct = sum(row.object_detected == object_id for row in object_rows)
        by_object[object_id] = {
            "samples": len(object_rows),
            "recall": _ratio(correct, len(object_rows)),
        }

    by_condition = {}
    for condition in sorted({row.condition for row in rows}):
        condition_rows = [row for row in rows if row.condition == condition]
        condition_positives = sum(
            row.object_expected is not None for row in condition_rows
        )
        condition_negatives = len(condition_rows) - condition_positives
        condition_tp = sum(row.true_positive for row in condition_rows)
        condition_detections = sum(
            row.object_detected is not None for row in condition_rows
        )
        by_condition[condition] = {
            "samples": len(condition_rows),
            "positive_samples": condition_positives,
            "negative_samples": condition_negatives,
            "recall": _ratio(condition_tp, condition_positives),
            "precision": _ratio(condition_tp, condition_detections),
            "false_positive_rate": _ratio(
                sum(
                    row.object_expected is None and row.object_detected is not None
                    for row in condition_rows
                ),
                condition_negatives,
            ),
            "l1_hit_rate": _ratio(
                sum(row.l1_hit for row in condition_rows), len(condition_rows)
            ),
        }

    confusion = defaultdict(lambda: defaultdict(int))
    for row in rows:
        expected = row.object_expected or "<negative>"
        detected = row.object_detected or "<none>"
        confusion[expected][detected] += 1

    detection_times, longest_miss_streak = _sequence_metrics(rows)
    latencies = [row.total_latency_ms for row in rows]
    fps_values = [row.fps for row in rows if row.fps is not None]
    cpu_values = [row.cpu_percent for row in rows if row.cpu_percent is not None]
    ram_values = [row.ram_mb for row in rows if row.ram_mb is not None]
    return {
        "samples": total,
        "positive_samples": positives,
        "negative_samples": negatives,
        "recall": _ratio(true_positives, positives),
        "precision": _ratio(true_positives, detections),
        "false_positive_rate": _ratio(
            sum(
                row.object_expected is None and row.object_detected is not None
                for row in rows
            ),
            negatives,
        ),
        "false_negative_rate": _ratio(false_negatives, positives),
        "true_positives": true_positives,
        "true_negatives": true_negatives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "l1_hit_rate": _ratio(sum(row.l1_hit for row in rows), total),
        "l2_success_rate": _ratio(sum(row.l2_success for row in rows), total),
        "l3_success_rate": _ratio(sum(row.l3_success for row in rows), total),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "time_to_first_detection_p50": _percentile(detection_times, 50),
        "time_to_first_detection_p95": _percentile(detection_times, 95),
        "longest_miss_streak": longest_miss_streak,
        "fps_mean": float(np.mean(fps_values)) if fps_values else None,
        "cpu_percent_mean": float(np.mean(cpu_values)) if cpu_values else None,
        "ram_mb_peak": max(ram_values) if ram_values else None,
        "recall_by_object": by_object,
        "metrics_by_condition": by_condition,
        "confusion": {key: dict(value) for key, value in confusion.items()},
    }


def classify(expected: str | None, detected: str | None) -> dict[str, bool]:
    correct_positive = expected is not None and detected == expected
    true_negative = expected is None and detected is None
    false_positive = detected is not None and detected != expected
    false_negative = expected is not None and detected != expected
    return {
        "true_positive": correct_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def _sequence_metrics(rows: list[VisionMetric]) -> tuple[list[float], int]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[
            (
                row.variant,
                row.homography_requested,
                row.object_expected,
                row.condition,
                row.sequence_id,
            )
        ].append(row)
    detection_times = []
    longest = 0
    for sequence_rows in grouped.values():
        sequence_rows.sort(key=lambda row: row.frame_index)
        first = next((row for row in sequence_rows if row.true_positive), None)
        if first is not None:
            detection_times.append(first.timestamp_s)
        streak = 0
        for row in sequence_rows:
            if row.object_expected is not None and not row.true_positive:
                streak += 1
                longest = max(longest, streak)
            else:
                streak = 0
    return detection_times, longest


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    value = float(np.percentile(values, percentile))
    return None if math.isnan(value) else value
