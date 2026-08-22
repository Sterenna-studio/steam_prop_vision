"""Rejeu d'un corpus identique sur chaque variante/estimateur."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import time

import cv2

from ..appearance import GlobalAppearanceRecognizer
from ..card_detector import CardCandidate, CardDetector
from ..card_recognizer import CardRecognizer, RecognitionCandidate
from ..fast_detector import FastDetector
from ..thresholds import RecognitionThresholds
from .corpus import CorpusFrame, discover_corpus, iter_frames
from .metrics import VisionMetric, VisionMetricsAccumulator, classify
from .variants import BenchmarkVariant


@dataclass
class BenchmarkOptions:
    corpus: str
    templates: str = "PLATEST"
    roi_mode: str = "l1"
    top_k: int = 2
    top2_margin: float = 0.10
    limit: int | None = None
    object_id: str | None = None
    verbose: bool = False
    save_failures: str | None = None
    appearance_threshold: float = 0.55
    orb_threshold: float = 0.20
    l3_min_matches: int = 12
    fast_min_area: int = 4000
    camera_rotation: int = 0


class VisionBenchmarkRunner:
    def __init__(
        self,
        variants: list[BenchmarkVariant],
        homographies: list[str],
        options: BenchmarkOptions,
        thresholds: RecognitionThresholds | None = None,
    ):
        if options.roi_mode not in {"l1", "full", "hybrid"}:
            raise ValueError("roi_mode doit valoir l1, full ou hybrid")
        self.variants = variants
        self.homographies = homographies
        self.options = options
        self.thresholds = thresholds or RecognitionThresholds(
            default_threshold=options.orb_threshold
        )
        self.entries = discover_corpus(options.corpus, options.object_id)
        self.metrics = VisionMetricsAccumulator()

    def run(self) -> VisionMetricsAccumulator:
        for variant in self.variants:
            for homography in self.homographies:
                self._run_configuration(variant, homography)
        return self.metrics

    def _run_configuration(self, variant: BenchmarkVariant, homography: str) -> None:
        detector = CardDetector(
            platest_dir=self.options.templates,
            backend=variant.l2_backend,
            homography=homography,
        )
        recognizer = self._create_l3(variant)
        fast_detector = FastDetector(min_area=self.options.fast_min_area)
        processed = 0
        for entry in self.entries:
            miss_streak = 0
            longest_miss_streak = 0
            first_detection_seen = False
            for frame in iter_frames(entry):
                if self.options.limit is not None and processed >= self.options.limit:
                    return
                metric = self._process_frame(
                    frame, variant, homography, fast_detector, detector, recognizer
                )
                if metric.object_expected is not None and not metric.true_positive:
                    miss_streak += 1
                    longest_miss_streak = max(longest_miss_streak, miss_streak)
                else:
                    miss_streak = 0
                metric.miss_streak = miss_streak
                metric.longest_miss_streak = longest_miss_streak
                if metric.true_positive and not first_detection_seen:
                    metric.time_to_first_detection = frame.timestamp_s
                    first_detection_seen = True
                self.metrics.add(metric)
                processed += 1
                if self.options.verbose:
                    print(
                        f"[{variant.code}/{homography}] {frame.entry.relative_path}"
                        f"#{frame.frame_index}: {metric.object_detected or '-'}"
                    )
                if metric.false_positive or metric.false_negative:
                    self._save_failure(frame, metric)

    def _create_l3(self, variant: BenchmarkVariant):
        if variant.l3_backend == "orb":
            return CardRecognizer(
                platest_dir=self.options.templates,
                min_matches=self.options.l3_min_matches,
                thresholds=self.thresholds,
            )
        appearance_thresholds = RecognitionThresholds(
            default_threshold=self.options.appearance_threshold,
            use_per_object_thresholds=False,
        )
        return GlobalAppearanceRecognizer(
            platest_dir=self.options.templates,
            thresholds=appearance_thresholds,
        )

    def _process_frame(
        self,
        frame: CorpusFrame,
        variant: BenchmarkVariant,
        homography: str,
        fast_detector: FastDetector,
        detector: CardDetector,
        recognizer,
    ) -> VisionMetric:
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        image = _rotate_frame(frame.image, self.options.camera_rotation)
        quad = fast_detector.detect(image)
        l1_hit = quad is not None
        roi = image
        if quad is not None and self.options.roi_mode in {"l1", "hybrid"}:
            roi = quad.crop(image)
        elif quad is None and self.options.roi_mode == "l1":
            return self._empty_metric(
                frame, variant, homography, wall_started, cpu_started
            )

        l2_started = time.perf_counter()
        candidates = detector.detect_candidates(roi, top_k=self.options.top_k)
        l2_latency = (time.perf_counter() - l2_started) * 1000.0
        selected = self._select_l3_candidates(candidates)
        l3_started = time.perf_counter()
        l3_results = [
            self._score_l3(recognizer, candidate, variant) for candidate in selected
        ]
        l3_latency = (time.perf_counter() - l3_started) * 1000.0
        accepted = [result for result in l3_results if result[1]]
        final = max(accepted, key=lambda result: result[0]) if accepted else None
        detected = final[2] if final else None
        best_l3 = max(l3_results, key=lambda result: result[0], default=None)
        measured_l3 = final or best_l3
        score = measured_l3[0] if measured_l3 else 0.0
        threshold = measured_l3[3] if measured_l3 else None
        top1 = candidates[0] if candidates else None
        top2 = candidates[1] if len(candidates) > 1 else None
        flags = classify(frame.entry.metadata.expected, detected)
        total_latency = (time.perf_counter() - wall_started) * 1000.0
        cpu_elapsed = time.process_time() - cpu_started
        return VisionMetric(
            sample_id=frame.entry.relative_path,
            frame_index=frame.frame_index,
            timestamp_s=frame.timestamp_s,
            backend=variant.l2_backend,
            variant=variant.code,
            homography_backend=(
                top1.homography_backend if top1 else _resolved_name(homography)
            ),
            homography_requested=homography,
            homography_fallback_used=(top1.homography_fallback_used if top1 else False),
            object_expected=frame.entry.metadata.expected,
            object_detected=detected,
            condition=frame.entry.metadata.condition,
            l1_hit=l1_hit,
            l1_miss=not l1_hit,
            l2_success=bool(candidates),
            l2_fail=not candidates,
            l2_latency_ms=l2_latency,
            l3_success=final is not None,
            l3_fail=final is None,
            l3_latency_ms=l3_latency,
            matches=top1.match_count if top1 else 0,
            inliers=top1.inlier_count if top1 else 0,
            inlier_ratio=top1.inlier_ratio if top1 else 0.0,
            reprojection_error=top1.reprojection_error if top1 else None,
            quadrilateral_area=top1.quadrilateral_area if top1 else None,
            geometry_valid=top1.geometry_valid if top1 else False,
            top1=top1.card_id if top1 else None,
            top2=top2.card_id if top2 else None,
            top1_score=top1.score if top1 else None,
            top2_score=top2.score if top2 else None,
            top1_top2_margin=(top1.score - top2.score if top1 and top2 else None),
            final_candidate=detected,
            l3_best_candidate=best_l3[2] if best_l3 else None,
            l3_corrected_top1=bool(
                final
                and top1
                and detected != top1.card_id
                and detected == frame.entry.metadata.expected
            ),
            score=score,
            threshold_used=threshold,
            total_latency_ms=total_latency,
            cpu_percent=(cpu_elapsed / max(total_latency / 1000.0, 1e-9)) * 100.0,
            ram_mb=_current_ram_mb(),
            fps=1000.0 / total_latency if total_latency > 0 else None,
            **flags,
        )

    def _empty_metric(
        self,
        frame: CorpusFrame,
        variant: BenchmarkVariant,
        homography: str,
        wall_started: float,
        cpu_started: float,
    ) -> VisionMetric:
        total_latency = (time.perf_counter() - wall_started) * 1000.0
        cpu_elapsed = time.process_time() - cpu_started
        flags = classify(frame.entry.metadata.expected, None)
        return VisionMetric(
            sample_id=frame.entry.relative_path,
            frame_index=frame.frame_index,
            timestamp_s=frame.timestamp_s,
            backend=variant.l2_backend,
            variant=variant.code,
            homography_backend=_resolved_name(homography),
            homography_requested=homography,
            homography_fallback_used=(
                homography.lower() in {"magsac", "usac_magsac"}
                and not hasattr(cv2, "USAC_MAGSAC")
            ),
            object_expected=frame.entry.metadata.expected,
            object_detected=None,
            condition=frame.entry.metadata.condition,
            l1_hit=False,
            l1_miss=True,
            l2_success=False,
            l2_fail=True,
            l2_latency_ms=0.0,
            l3_success=False,
            l3_fail=True,
            l3_latency_ms=0.0,
            total_latency_ms=total_latency,
            cpu_percent=(cpu_elapsed / max(total_latency / 1000.0, 1e-9)) * 100.0,
            ram_mb=_current_ram_mb(),
            fps=1000.0 / total_latency if total_latency > 0 else None,
            **flags,
        )

    def _select_l3_candidates(
        self, candidates: list[CardCandidate]
    ) -> list[CardCandidate]:
        if len(candidates) < 2:
            return candidates
        margin = candidates[0].score - candidates[1].score
        return candidates[:1] if margin > self.options.top2_margin else candidates[:2]

    @staticmethod
    def _score_l3(recognizer, candidate: CardCandidate, variant: BenchmarkVariant):
        if variant.l3_backend == "orb":
            results: list[RecognitionCandidate] = recognizer.recognize_candidates(
                candidate.warped, hint_ids=[candidate.card_id]
            )
            if not results:
                return 0.0, False, candidate.card_id, None
            result = results[0]
            return (
                result.score,
                result.accepted,
                result.card_id,
                result.threshold_used,
            )
        results = recognizer.compare_candidates(candidate.warped, [candidate.card_id])
        if not results:
            return 0.0, False, candidate.card_id, None
        result = results[0]
        return result.score, result.accepted, result.card_id, result.threshold_used

    def _save_failure(self, frame: CorpusFrame, metric: VisionMetric) -> None:
        if not self.options.save_failures:
            return
        output = Path(self.options.save_failures)
        output.mkdir(parents=True, exist_ok=True)
        safe_name = frame.entry.relative_path.replace("/", "__").replace("\\", "__")
        name = (
            f"{metric.variant}_{metric.homography_requested}_"
            f"{safe_name}_{frame.frame_index:06d}.jpg"
        )
        cv2.imwrite(str(output / name), frame.image)


def _resolved_name(requested: str) -> str:
    if requested.lower() in {"magsac", "usac_magsac"} and not hasattr(
        cv2, "USAC_MAGSAC"
    ):
        return "ransac"
    return "magsac" if requested.lower() == "usac_magsac" else requested.lower()


def _rotate_frame(frame, rotation: int):
    if rotation == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if rotation == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if rotation != 0:
        raise ValueError("camera_rotation doit valoir 0, 90, 180 ou 270")
    return frame


def _current_ram_mb() -> float | None:
    try:
        import resource

        maximum = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        divisor = 1024.0 * 1024.0 if platform.system() == "Darwin" else 1024.0
        return maximum / divisor
    except (ImportError, OSError, ValueError):
        return None
