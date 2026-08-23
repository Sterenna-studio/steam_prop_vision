"""Runner reproductible pour comparer les stratégies de sélection L1."""

from __future__ import annotations

from dataclasses import dataclass
import time

from ..card_detector import CardCandidate, CardDetector
from ..card_recognizer import CardRecognizer, RecognitionCandidate
from ..fast_detector import FastDetector
from ..thresholds import RecognitionThresholds
from .corpus import CorpusFrame, discover_corpus, iter_frames
from .l1 import (
    L1Controller,
    L1_STRATEGIES,
    NormalizedROI,
    ROICalibrationResult,
    calibrate_normalized_roi,
    candidate_bbox_in_frame,
)
from .l1_metrics import (
    HoldSimulator,
    L1FrameMetric,
    L1MetricsAccumulator,
    set_classification,
)
from .runner import _resolved_name, _rotate_frame
from .variants import BenchmarkVariant


@dataclass
class L1BenchmarkOptions:
    corpus: str
    templates: str = "PLATEST"
    strategies: tuple[str, ...] = L1_STRATEGIES
    top_k: int = 2
    top2_margin: float = 0.10
    limit: int | None = None
    object_id: str | None = None
    verbose: bool = False
    l3_min_matches: int = 12
    fast_min_area: int = 4000
    camera_rotation: int = 0
    calibrated_roi: NormalizedROI | None = None
    auto_calibrate_roi: bool = True
    calibration_condition: str = "frontal"
    calibration_margin: float = 0.04
    quality_threshold: float = 0.55
    tracking_threshold: float = 0.35
    hold_ms: int = 1000
    consecutive_frames: int = 1
    miss_grace_frames: int = 5


class L1BenchmarkRunner:
    def __init__(
        self,
        recognition_variant: BenchmarkVariant,
        homography: str,
        options: L1BenchmarkOptions,
        thresholds: RecognitionThresholds,
    ):
        if recognition_variant.l3_backend != "orb":
            raise ValueError("Le benchmark L1 v2 exige un L3 ORB (variantes A, B ou C)")
        unknown = set(options.strategies) - set(L1_STRATEGIES)
        if unknown:
            raise ValueError(f"Stratégies L1 inconnues: {', '.join(sorted(unknown))}")
        self.variant = recognition_variant
        self.homography = homography
        self.options = options
        self.thresholds = thresholds
        self.entries = discover_corpus(options.corpus, options.object_id)
        self.metrics = L1MetricsAccumulator()
        self.calibration: ROICalibrationResult | None = None

    def run(self) -> L1MetricsAccumulator:
        calibrated_roi = self.options.calibrated_roi
        needs_calibration = any(
            strategy
            in {"calibrated_fallback", "quality_fallback", "acquisition_tracking"}
            for strategy in self.options.strategies
        )
        if (
            calibrated_roi is None
            and self.options.auto_calibrate_roi
            and needs_calibration
        ):
            self.calibration = self._calibrate_roi()
            calibrated_roi = self.calibration.roi
        if calibrated_roi is None and needs_calibration:
            raise ValueError(
                "Une ROI calibrée est requise pour les stratégies demandées"
            )
        for strategy in self.options.strategies:
            self._run_strategy(strategy, calibrated_roi)
        return self.metrics

    def _calibrate_roi(self) -> ROICalibrationResult:
        detector = FastDetector(min_area=self.options.fast_min_area)
        samples = []
        for entry in self.entries:
            if entry.metadata.expected is None:
                continue
            if entry.metadata.condition != self.options.calibration_condition:
                continue
            for frame in iter_frames(entry):
                image = _rotate_frame(frame.image, self.options.camera_rotation)
                samples.append((image, detector.detect(image)))
        return calibrate_normalized_roi(samples, margin=self.options.calibration_margin)

    def _run_strategy(
        self, strategy: str, calibrated_roi: NormalizedROI | None
    ) -> None:
        detector = CardDetector(
            platest_dir=self.options.templates,
            backend=self.variant.l2_backend,
            homography=self.homography,
        )
        recognizer = CardRecognizer(
            platest_dir=self.options.templates,
            min_matches=self.options.l3_min_matches,
            thresholds=self.thresholds,
        )
        fast_detector = FastDetector(min_area=self.options.fast_min_area)
        controllers: dict[tuple, L1Controller] = {}
        holds: dict[tuple, HoldSimulator] = {}
        positions: dict[tuple, int] = {}
        states: dict[tuple, dict] = {}
        processed = 0
        for entry in self.entries:
            for raw_frame in iter_frames(entry):
                if self.options.limit is not None and processed >= self.options.limit:
                    return
                sequence_id = entry.metadata.sequence_id or entry.relative_path
                key = (entry.metadata.expected, entry.metadata.condition, sequence_id)
                frame = self._place_in_sequence(raw_frame, key, positions)
                controller = controllers.setdefault(
                    key,
                    L1Controller(
                        strategy,
                        calibrated_roi,
                        quality_threshold=self.options.quality_threshold,
                        tracking_threshold=self.options.tracking_threshold,
                    ),
                )
                hold = holds.setdefault(
                    key,
                    HoldSimulator(
                        self.options.hold_ms,
                        self.options.consecutive_frames,
                        self.options.miss_grace_frames,
                    ),
                )
                metric = self._process_frame(
                    frame, strategy, controller, fast_detector, detector, recognizer
                )
                state = states.setdefault(
                    key,
                    {"miss_streak": 0, "longest": 0, "detected": False},
                )
                if metric.object_expected is not None and not metric.true_positive:
                    state["miss_streak"] += 1
                    state["longest"] = max(state["longest"], state["miss_streak"])
                else:
                    state["miss_streak"] = 0
                metric.miss_streak = state["miss_streak"]
                metric.longest_miss_streak = state["longest"]
                if metric.true_positive and not state["detected"]:
                    metric.time_to_first_detection = frame.timestamp_s
                    state["detected"] = True
                trigger = hold.update(metric.object_detected, frame.timestamp_s)
                if trigger is not None:
                    metric.trigger_id = trigger
                    metric.time_to_trigger = frame.timestamp_s
                self.metrics.add(metric)
                processed += 1
                if self.options.verbose:
                    print(
                        f"[{strategy}/{self.variant.code}/{self.homography}] "
                        f"{entry.relative_path}#{frame.frame_index}: "
                        f"{metric.roi_source} -> {metric.object_detected or '-'}"
                    )

    @staticmethod
    def _place_in_sequence(
        frame: CorpusFrame, key: tuple, positions: dict[tuple, int]
    ) -> CorpusFrame:
        index = positions.get(key, 0)
        positions[key] = index + 1
        fps = frame.entry.metadata.fps
        timestamp = index / fps if fps and fps > 0 else frame.timestamp_s
        return CorpusFrame(frame.entry, frame.image, index, timestamp)

    def _process_frame(
        self,
        frame: CorpusFrame,
        strategy: str,
        controller: L1Controller,
        fast_detector: FastDetector,
        detector: CardDetector,
        recognizer: CardRecognizer,
    ) -> L1FrameMetric:
        started = time.perf_counter()
        image = _rotate_frame(frame.image, self.options.camera_rotation)
        l1_started = time.perf_counter()
        quad = fast_detector.detect(image)
        selection = controller.select(image, quad)
        l1_latency = (time.perf_counter() - l1_started) * 1000.0
        roi = selection.crop(image)
        l2_started = time.perf_counter()
        candidates = (
            detector.detect_candidates(roi, top_k=self.options.top_k)
            if roi is not None
            else []
        )
        l2_latency = (time.perf_counter() - l2_started) * 1000.0
        selected = self._select_l3_candidates(candidates)
        l3_started = time.perf_counter()
        l3_results = [self._score_l3(recognizer, candidate) for candidate in selected]
        l3_latency = (time.perf_counter() - l3_started) * 1000.0
        accepted = [result for result in l3_results if result[1]]
        final = max(accepted, key=lambda result: result[0]) if accepted else None
        detected = final[2] if final else None
        measured = final or max(l3_results, key=lambda result: result[0], default=None)
        top1 = candidates[0] if candidates else None
        top2 = candidates[1] if len(candidates) > 1 else None
        if final is not None and selection.bbox is not None:
            matched_candidate = next(
                (candidate for candidate in selected if candidate.card_id == detected),
                None,
            )
            if matched_candidate is not None:
                controller.observe(
                    image,
                    candidate_bbox_in_frame(
                        matched_candidate.corners, selection.bbox, image.shape
                    ),
                )
        bbox = selection.bbox
        quality = selection.quality
        metric = L1FrameMetric(
            sample_id=frame.entry.relative_path,
            sequence_id=frame.entry.metadata.sequence_id or frame.entry.relative_path,
            frame_index=frame.frame_index,
            timestamp_s=frame.timestamp_s,
            strategy=strategy,
            recognition_variant=self.variant.code,
            homography_requested=self.homography,
            homography_backend=(
                top1.homography_backend if top1 else _resolved_name(self.homography)
            ),
            object_expected=frame.entry.metadata.expected,
            object_detected=detected,
            condition=frame.entry.metadata.condition,
            contour_found=selection.contour_found,
            roi_source=selection.source,
            fallback_used=selection.fallback_used,
            l1_quality=quality.score,
            l1_regularity=quality.regularity,
            l1_area_ratio=quality.area_ratio,
            l1_area_score=quality.area_score,
            l1_edge_support=quality.edge_support,
            l1_contrast=quality.contrast,
            l1_temporal_stability=quality.temporal_stability,
            tracking_quality=selection.tracking_quality,
            roi_x=bbox[0] if bbox else None,
            roi_y=bbox[1] if bbox else None,
            roi_width=bbox[2] if bbox else None,
            roi_height=bbox[3] if bbox else None,
            l1_latency_ms=l1_latency,
            l2_latency_ms=l2_latency,
            l3_latency_ms=l3_latency,
            total_latency_ms=(time.perf_counter() - started) * 1000.0,
            l2_success=bool(candidates),
            l3_success=final is not None,
            matches=top1.match_count if top1 else 0,
            inliers=top1.inlier_count if top1 else 0,
            inlier_ratio=top1.inlier_ratio if top1 else 0.0,
            reprojection_error=top1.reprojection_error if top1 else None,
            top1=top1.card_id if top1 else None,
            top2=top2.card_id if top2 else None,
            top1_top2_margin=(top1.score - top2.score if top1 and top2 else None),
            score=measured[0] if measured else 0.0,
            threshold_used=measured[3] if measured else None,
        )
        set_classification(metric)
        return metric

    def _select_l3_candidates(
        self, candidates: list[CardCandidate]
    ) -> list[CardCandidate]:
        if len(candidates) < 2:
            return candidates
        margin = candidates[0].score - candidates[1].score
        return candidates[:1] if margin > self.options.top2_margin else candidates[:2]

    @staticmethod
    def _score_l3(recognizer: CardRecognizer, candidate: CardCandidate):
        results: list[RecognitionCandidate] = recognizer.recognize_candidates(
            candidate.warped, hint_ids=[candidate.card_id]
        )
        if not results:
            return 0.0, False, candidate.card_id, None
        result = results[0]
        return result.score, result.accepted, result.card_id, result.threshold_used
