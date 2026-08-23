from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from steamcore.recognition.benchmark.l1 import (
    L1Controller,
    NormalizedROI,
    OpticalFlowROITracker,
    calibrate_normalized_roi,
    candidate_bbox_in_frame,
    evaluate_l1_quality,
)
from steamcore.recognition.benchmark.l1_metrics import (
    HoldSimulator,
    L1FrameMetric,
    L1MetricsAccumulator,
    set_classification,
)
from steamcore.recognition.benchmark.l1_report import (
    L1ReportContext,
    build_l1_report,
    render_l1_markdown,
    write_l1_reports,
)
from steamcore.recognition.benchmark.l1_runner import (
    L1BenchmarkOptions,
    L1BenchmarkRunner,
)
from steamcore.recognition.benchmark.variants import get_variants
from steamcore.recognition.card_detector import CardCandidate
from steamcore.recognition.card_recognizer import RecognitionCandidate
from steamcore.recognition.fast_detector import QuadROI
from steamcore.recognition.thresholds import RecognitionThresholds


def _quad(x=20, y=20, size=60, confidence=0.9):
    corners = np.float32([[x, y], [x + size, y], [x + size, y + size], [x, y + size]])
    return QuadROI(x, y, size, size, corners, confidence)


def _metric(
    *,
    detected="plate_x",
    expected="plate_x",
    frame_index=0,
    timestamp_s=0.0,
    trigger_id=None,
):
    metric = L1FrameMetric(
        sample_id="sample.png",
        sequence_id="sequence_1",
        frame_index=frame_index,
        timestamp_s=timestamp_s,
        strategy="contour",
        recognition_variant="A",
        homography_requested="ransac",
        homography_backend="ransac",
        object_expected=expected,
        object_detected=detected,
        condition="frontal",
        contour_found=True,
        roi_source="contour",
        fallback_used=False,
        l1_quality=0.8,
        l1_regularity=0.9,
        l1_area_ratio=0.1,
        l1_area_score=1.0,
        l1_edge_support=0.8,
        l1_contrast=0.7,
        l1_temporal_stability=0.5,
        tracking_quality=None,
        roi_x=0,
        roi_y=0,
        roi_width=100,
        roi_height=100,
        l1_latency_ms=1.0,
        l2_latency_ms=2.0,
        l3_latency_ms=3.0,
        total_latency_ms=6.0,
        l2_success=True,
        l3_success=detected is not None,
        trigger_id=trigger_id,
        time_to_trigger=timestamp_s if trigger_id else None,
    )
    set_classification(metric)
    return metric


def test_normalized_roi_parse_and_bbox():
    roi = NormalizedROI.parse("0.1,0.2,0.5,0.6")
    assert roi.to_bbox((100, 200, 3)) == (20, 20, 100, 60)
    with pytest.raises(ValueError):
        NormalizedROI.parse("0.9,0.2,0.5,0.6")
    with pytest.raises(ValueError):
        NormalizedROI.parse("0.1,0.2,0.5")


def test_roi_calibration_uses_observed_quads():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    result = calibrate_normalized_roi(
        [
            (frame, _quad(20, 20, 40)),
            (frame, _quad(30, 20, 40)),
            (frame, _quad(20, 30, 40)),
        ],
        margin=0,
    )
    assert result.samples_seen == 3
    assert result.detections_used == 3
    assert 0.1 <= result.roi.x <= 0.15
    assert result.roi.w > 0.2


def test_l1_controller_fallback_policies():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    roi = NormalizedROI(0.25, 0.25, 0.5, 0.5)
    assert L1Controller("contour", roi).select(frame, None).bbox is None
    full = L1Controller("full_fallback", roi).select(frame, None)
    assert full.source == "full_frame"
    assert full.bbox == (0, 0, 200, 100)
    calibrated = L1Controller("calibrated_fallback", roi).select(frame, None)
    assert calibrated.source == "calibrated_roi"
    assert calibrated.bbox == (50, 25, 100, 50)
    quality = L1Controller("quality_fallback", roi, quality_threshold=1.0).select(
        frame, _quad()
    )
    assert quality.contour_found is True
    assert quality.source == "calibrated_roi"


def test_l1_quality_and_candidate_bbox_are_normalized():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(frame, (20, 20), (80, 80), (255, 255, 255), 2)
    quality = evaluate_l1_quality(frame, _quad())
    assert 0 <= quality.score <= 1
    assert quality.area_ratio > 0
    bbox = candidate_bbox_in_frame(
        np.float32([[0, 0], [20, 0], [20, 20], [0, 20]]),
        (40, 30, 50, 50),
        frame.shape,
        margin=0,
    )
    assert bbox[:2] == (40, 30)


def test_optical_flow_tracker_follows_translation():
    rng = np.random.default_rng(4)
    frame = np.zeros((180, 220, 3), dtype=np.uint8)
    texture = rng.integers(0, 256, (80, 80, 3), dtype=np.uint8)
    frame[40:120, 60:140] = texture
    shifted = cv2.warpAffine(frame, np.float32([[1, 0, 7], [0, 1, 5]]), (220, 180))
    tracker = OpticalFlowROITracker(min_quality=0.1)
    assert tracker.acquire(frame, (60, 40, 80, 80))
    tracked = tracker.track(shifted)
    assert tracked is not None
    bbox, quality = tracked
    assert abs(bbox[0] - 67) <= 2
    assert abs(bbox[1] - 45) <= 2
    assert quality > 0.1


def test_hold_simulator_matches_runtime_semantics_and_grace():
    hold = HoldSimulator(hold_ms=1000, consecutive_frames=1, miss_grace_frames=1)
    assert hold.update("plate_x", 0.0) is None
    assert hold.update("plate_x", 0.5) is None
    assert hold.update(None, 1.0) is None
    assert hold.update("plate_x", 1.5) == "plate_x"

    reset = HoldSimulator(hold_ms=500, consecutive_frames=1, miss_grace_frames=0)
    reset.update("plate_x", 0.0)
    reset.update("plate_x", 0.5)
    reset.update(None, 0.75)
    assert reset.update("plate_x", 1.0) is None


def test_l1_metrics_and_report_generation(tmp_path):
    metrics = L1MetricsAccumulator()
    metrics.add(_metric(frame_index=0, timestamp_s=0.0))
    metrics.add(_metric(frame_index=1, timestamp_s=1.0, trigger_id="plate_x"))
    metrics.add(_metric(expected=None, detected=None, frame_index=0))
    summary = metrics.grouped_summary()[0]
    assert summary["presentation_detection_rate"] == 1.0
    assert summary["trigger_success_rate"] == 1.0
    assert summary["negative_trigger_rate"] == 0.0
    report = build_l1_report(
        metrics,
        L1ReportContext(
            corpus="corpus",
            templates="PLATEST",
            recognition_variant="A",
            homography="ransac",
            strategies=["contour"],
            calibrated_roi=None,
            calibration_samples_seen=None,
            calibration_detections_used=None,
            quality_threshold=0.55,
            tracking_threshold=0.35,
            hold_ms=1000,
            consecutive_frames=1,
            miss_grace_frames=5,
            top_k=2,
            top2_margin=0.1,
        ),
    )
    assert "Triggers corrects" in render_l1_markdown(report)
    paths = write_l1_reports(report, tmp_path, "l1")
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["samples"]
    assert paths["csv"].exists()


def test_l1_runner_replays_sequences_through_hold(monkeypatch, tmp_path):
    corpus = tmp_path / "corpus"
    positive = corpus / "plate_x" / "occlusion"
    negative = corpus / "negatives" / "aucune_plaque"
    positive.mkdir(parents=True)
    negative.mkdir(parents=True)
    for directory, value, expected, sequence_id in (
        (positive, 255, "plate_x", "positive_sequence"),
        (negative, 0, "none", "negative_sequence"),
    ):
        for index in range(4):
            image_path = directory / f"frame_{index:04d}.png"
            cv2.imwrite(str(image_path), np.full((40, 60, 3), value, dtype=np.uint8))
            image_path.with_suffix(".yaml").write_text(
                f"expected: {expected}\nsequence_id: {sequence_id}\nfps: 2\n",
                encoding="utf-8",
            )

    class FakeFastDetector:
        def __init__(self, **_kwargs):
            pass

        def detect(self, _frame):
            return None

    class FakeCardDetector:
        def __init__(self, **_kwargs):
            pass

        def detect_candidates(self, roi, top_k=1):
            if float(np.mean(roi)) < 1:
                return []
            return [
                CardCandidate(
                    card_id="plate_x",
                    match_count=20,
                    inlier_count=18,
                    inlier_ratio=0.9,
                    homography_quality=0.8,
                    reprojection_error=0.2,
                    corners=np.float32([[0, 0], [59, 0], [59, 39], [0, 39]]),
                    warped=roi,
                    score=0.75,
                    quadrilateral_area=2301.0,
                    geometry_valid=True,
                    homography_backend="ransac",
                    homography_fallback_used=False,
                    homography_latency_ms=1.0,
                )
            ][:top_k]

    class FakeRecognizer:
        def __init__(self, **_kwargs):
            pass

        def recognize_candidates(self, _warped, hint_ids=None):
            return [
                RecognitionCandidate(
                    card_id=hint_ids[0],
                    score=0.8,
                    matches=15,
                    matched_img="template.png",
                    threshold_used=0.2,
                    accepted=True,
                )
            ]

    monkeypatch.setattr(
        "steamcore.recognition.benchmark.l1_runner.FastDetector", FakeFastDetector
    )
    monkeypatch.setattr(
        "steamcore.recognition.benchmark.l1_runner.CardDetector", FakeCardDetector
    )
    monkeypatch.setattr(
        "steamcore.recognition.benchmark.l1_runner.CardRecognizer", FakeRecognizer
    )
    runner = L1BenchmarkRunner(
        get_variants("A")[0],
        "ransac",
        L1BenchmarkOptions(
            corpus=str(corpus),
            templates=str(tmp_path / "PLATEST"),
            strategies=("contour", "full_fallback"),
            hold_ms=1000,
            consecutive_frames=1,
            miss_grace_frames=0,
        ),
        RecognitionThresholds(default_threshold=0.2),
    )

    summaries = {row["strategy"]: row for row in runner.run().grouped_summary()}

    assert summaries["contour"]["trigger_success_rate"] == 0.0
    assert summaries["full_fallback"]["presentation_detection_rate"] == 1.0
    assert summaries["full_fallback"]["trigger_success_rate"] == 1.0
    assert summaries["full_fallback"]["negative_trigger_rate"] == 0.0
    trigger_rows = [
        row
        for row in runner.metrics.rows
        if row.strategy == "full_fallback" and row.trigger_id == "plate_x"
    ]
    assert len(trigger_rows) == 1
    assert trigger_rows[0].frame_index == 3
    assert trigger_rows[0].time_to_trigger == 1.5
