"""Stratégies L1 v2 isolées pour benchmark, sans activation runtime."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import cv2
import numpy as np

from ..fast_detector import QuadROI


L1_STRATEGIES = (
    "contour",
    "full_fallback",
    "calibrated_fallback",
    "quality_fallback",
    "acquisition_tracking",
)


@dataclass(frozen=True)
class NormalizedROI:
    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.w, self.h)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("La ROI calibrée doit contenir des valeurs finies")
        if self.x < 0 or self.y < 0 or self.w <= 0 or self.h <= 0:
            raise ValueError("ROI calibrée normalisée invalide")
        if self.x + self.w > 1 or self.y + self.h > 1:
            raise ValueError("La ROI calibrée doit rester dans [0, 1]")

    @classmethod
    def parse(cls, value: str) -> NormalizedROI:
        try:
            parts = [float(part.strip()) for part in value.split(",")]
        except ValueError as exc:
            raise ValueError("ROI attendue sous la forme x,y,w,h") from exc
        if len(parts) != 4:
            raise ValueError("ROI attendue sous la forme x,y,w,h")
        return cls(*parts)

    def to_bbox(self, shape) -> tuple[int, int, int, int]:
        height, width = shape[:2]
        x = min(width - 1, max(0, int(round(self.x * width))))
        y = min(height - 1, max(0, int(round(self.y * height))))
        right = min(width, max(x + 1, int(round((self.x + self.w) * width))))
        bottom = min(height, max(y + 1, int(round((self.y + self.h) * height))))
        return x, y, right - x, bottom - y

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class L1Quality:
    score: float = 0.0
    regularity: float = 0.0
    area_ratio: float = 0.0
    area_score: float = 0.0
    edge_support: float = 0.0
    contrast: float = 0.0
    temporal_stability: float = 0.0


@dataclass(frozen=True)
class L1Selection:
    bbox: tuple[int, int, int, int] | None
    source: str
    contour_found: bool
    quality: L1Quality
    fallback_used: bool
    tracking_quality: float | None = None

    def crop(self, frame: np.ndarray) -> np.ndarray | None:
        if self.bbox is None:
            return None
        x, y, w, h = self.bbox
        return frame[y : y + h, x : x + w]


@dataclass(frozen=True)
class ROICalibrationResult:
    roi: NormalizedROI
    samples_seen: int
    detections_used: int


def evaluate_l1_quality(
    frame: np.ndarray,
    quad: QuadROI | None,
    previous_bbox: tuple[int, int, int, int] | None = None,
) -> L1Quality:
    """Produit des composantes explicites, destinées à être benchmarkées."""
    if quad is None:
        return L1Quality()
    height, width = frame.shape[:2]
    frame_area = max(float(height * width), 1.0)
    contour_area = abs(float(cv2.contourArea(quad.corners.astype(np.float32))))
    area_ratio = contour_area / frame_area
    area_score = float(np.clip(math.sqrt(area_ratio / 0.08), 0.0, 1.0))

    gray = _to_gray(frame)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), dtype=np.uint8))
    outline = np.zeros_like(edges)
    cv2.polylines(
        outline,
        [quad.corners.astype(np.int32).reshape(-1, 1, 2)],
        True,
        255,
        1,
    )
    outline_pixels = outline > 0
    edge_support = (
        float(np.mean(edges[outline_pixels] > 0)) if np.any(outline_pixels) else 0.0
    )

    crop = quad.crop(gray)
    contrast = float(np.clip(np.std(crop) / 64.0, 0.0, 1.0)) if crop.size else 0.0
    bbox = (quad.x, quad.y, quad.w, quad.h)
    temporal = 0.5 if previous_bbox is None else _bbox_iou(bbox, previous_bbox)
    regularity = float(np.clip(quad.confidence, 0.0, 1.0))
    score = float(
        np.clip(
            0.30 * regularity
            + 0.25 * area_score
            + 0.25 * edge_support
            + 0.10 * contrast
            + 0.10 * temporal,
            0.0,
            1.0,
        )
    )
    return L1Quality(
        score=score,
        regularity=regularity,
        area_ratio=area_ratio,
        area_score=area_score,
        edge_support=edge_support,
        contrast=contrast,
        temporal_stability=temporal,
    )


def calibrate_normalized_roi(
    samples: Iterable[tuple[np.ndarray, QuadROI | None]],
    *,
    margin: float = 0.04,
    min_detections: int = 3,
) -> ROICalibrationResult:
    """Calibre une ROI robuste depuis les quads frontaux réellement observés."""
    boxes = []
    seen = 0
    for frame, quad in samples:
        seen += 1
        if quad is None:
            continue
        height, width = frame.shape[:2]
        boxes.append(
            (
                quad.x / width,
                quad.y / height,
                (quad.x + quad.w) / width,
                (quad.y + quad.h) / height,
            )
        )
    if len(boxes) < min_detections:
        raise ValueError(
            f"Calibration ROI impossible: {len(boxes)} détections, "
            f"minimum {min_detections}"
        )
    values = np.asarray(boxes, dtype=np.float64)
    left = max(0.0, float(np.percentile(values[:, 0], 5)) - margin)
    top = max(0.0, float(np.percentile(values[:, 1], 5)) - margin)
    right = min(1.0, float(np.percentile(values[:, 2], 95)) + margin)
    bottom = min(1.0, float(np.percentile(values[:, 3], 95)) + margin)
    return ROICalibrationResult(
        roi=NormalizedROI(left, top, right - left, bottom - top),
        samples_seen=seen,
        detections_used=len(boxes),
    )


class L1Controller:
    """Sélectionne la ROI d'une stratégie et maintient son état temporel."""

    def __init__(
        self,
        strategy: str,
        calibrated_roi: NormalizedROI | None,
        *,
        quality_threshold: float = 0.55,
        tracking_threshold: float = 0.35,
    ):
        if strategy not in L1_STRATEGIES:
            raise ValueError(f"Stratégie L1 inconnue: {strategy}")
        if not 0 <= quality_threshold <= 1:
            raise ValueError("quality_threshold doit rester dans [0, 1]")
        self.strategy = strategy
        self.calibrated_roi = calibrated_roi
        self.quality_threshold = quality_threshold
        self.previous_contour_bbox: tuple[int, int, int, int] | None = None
        self.tracker = OpticalFlowROITracker(min_quality=tracking_threshold)

    def select(self, frame: np.ndarray, quad: QuadROI | None) -> L1Selection:
        quality = evaluate_l1_quality(frame, quad, self.previous_contour_bbox)
        contour_bbox = None if quad is None else (quad.x, quad.y, quad.w, quad.h)
        if contour_bbox is not None:
            self.previous_contour_bbox = contour_bbox

        if self.strategy == "acquisition_tracking" and self.tracker.locked:
            tracked = self.tracker.track(frame)
            if tracked is not None:
                bbox, tracking_quality = tracked
                return L1Selection(
                    bbox=bbox,
                    source="tracked",
                    contour_found=quad is not None,
                    quality=quality,
                    fallback_used=True,
                    tracking_quality=tracking_quality,
                )

        if self.strategy == "contour":
            return self._selection(contour_bbox, "contour", quad, quality, False)
        if self.strategy == "full_fallback":
            if contour_bbox is not None:
                return self._selection(contour_bbox, "contour", quad, quality, False)
            return self._selection(_full_bbox(frame), "full_frame", quad, quality, True)
        if self.strategy == "calibrated_fallback":
            if contour_bbox is not None:
                return self._selection(contour_bbox, "contour", quad, quality, False)
            return self._fallback(frame, quad, quality)

        # quality_fallback et acquisition_tracking avant acquisition partagent
        # le même comportement conditionnel.
        if contour_bbox is not None and quality.score >= self.quality_threshold:
            return self._selection(contour_bbox, "contour", quad, quality, False)
        return self._fallback(frame, quad, quality)

    def observe(
        self,
        frame: np.ndarray,
        recognized_bbox: tuple[int, int, int, int] | None,
    ) -> None:
        if self.strategy != "acquisition_tracking":
            return
        if recognized_bbox is not None:
            self.tracker.acquire(frame, recognized_bbox)

    def _fallback(
        self, frame: np.ndarray, quad: QuadROI | None, quality: L1Quality
    ) -> L1Selection:
        if self.calibrated_roi is not None:
            return self._selection(
                self.calibrated_roi.to_bbox(frame.shape),
                "calibrated_roi",
                quad,
                quality,
                True,
            )
        return self._selection(_full_bbox(frame), "full_frame", quad, quality, True)

    @staticmethod
    def _selection(bbox, source, quad, quality, fallback) -> L1Selection:
        return L1Selection(
            bbox=bbox,
            source=source if bbox is not None else "none",
            contour_found=quad is not None,
            quality=quality,
            fallback_used=fallback,
        )


class OpticalFlowROITracker:
    """Tracking ROI léger par flot optique, réservé au benchmark."""

    def __init__(self, min_quality: float = 0.35, max_corners: int = 80):
        self.min_quality = min_quality
        self.max_corners = max_corners
        self.previous_gray: np.ndarray | None = None
        self.points: np.ndarray | None = None
        self.bbox: tuple[int, int, int, int] | None = None

    @property
    def locked(self) -> bool:
        return self.previous_gray is not None and self.points is not None

    def reset(self) -> None:
        self.previous_gray = None
        self.points = None
        self.bbox = None

    def acquire(self, frame: np.ndarray, bbox: tuple[int, int, int, int]) -> bool:
        gray = _to_gray(frame)
        x, y, w, h = _clamp_bbox(bbox, frame.shape)
        mask = np.zeros_like(gray)
        mask[y : y + h, x : x + w] = 255
        points = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=self.max_corners,
            qualityLevel=0.01,
            minDistance=6,
            mask=mask,
            blockSize=7,
        )
        if points is None or len(points) < 6:
            self.reset()
            return False
        self.previous_gray = gray
        self.points = points
        self.bbox = (x, y, w, h)
        return True

    def track(
        self, frame: np.ndarray
    ) -> tuple[tuple[int, int, int, int], float] | None:
        if not self.locked or self.bbox is None:
            return None
        gray = _to_gray(frame)
        next_points, status, errors = cv2.calcOpticalFlowPyrLK(
            self.previous_gray,
            gray,
            self.points,
            None,
            winSize=(21, 21),
            maxLevel=3,
        )
        if next_points is None or status is None:
            self.reset()
            return None
        valid = status.reshape(-1).astype(bool)
        old = self.points.reshape(-1, 2)[valid]
        new = next_points.reshape(-1, 2)[valid]
        if len(old) < 6:
            self.reset()
            return None
        matrix, inlier_mask = cv2.estimateAffinePartial2D(
            old,
            new,
            method=cv2.RANSAC,
            ransacReprojThreshold=3.0,
        )
        if matrix is None:
            self.reset()
            return None
        x, y, w, h = self.bbox
        corners = np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]).reshape(
            -1, 1, 2
        )
        transformed = cv2.transform(corners, matrix).reshape(-1, 2)
        tx, ty, tw, th = cv2.boundingRect(transformed.astype(np.float32))
        tracked_bbox = _clamp_bbox((tx, ty, tw, th), frame.shape)
        old_area = max(w * h, 1)
        new_area = tracked_bbox[2] * tracked_bbox[3]
        area_ratio = new_area / old_area
        if not 0.5 <= area_ratio <= 2.0:
            self.reset()
            return None

        inlier_ratio = (
            float(np.mean(inlier_mask.reshape(-1) > 0))
            if inlier_mask is not None
            else 0.0
        )
        median_error = (
            float(np.median(errors.reshape(-1)[valid])) if errors is not None else 0.0
        )
        quality = float(inlier_ratio * math.exp(-median_error / 12.0))
        if quality < self.min_quality:
            self.reset()
            return None

        kept = new if inlier_mask is None else new[inlier_mask.reshape(-1) > 0]
        self.previous_gray = gray
        self.points = kept.reshape(-1, 1, 2).astype(np.float32)
        self.bbox = tracked_bbox
        return tracked_bbox, quality


def candidate_bbox_in_frame(
    corners: np.ndarray,
    roi_bbox: tuple[int, int, int, int],
    frame_shape,
    margin: int = 16,
) -> tuple[int, int, int, int]:
    """Convertit le quad L2 relatif à la ROI en bbox frame pour le tracking."""
    x, y, _, _ = roi_bbox
    shifted = corners.astype(np.float32) + np.float32([x, y])
    rx, ry, rw, rh = cv2.boundingRect(shifted)
    return _clamp_bbox(
        (rx - margin, ry - margin, rw + 2 * margin, rh + 2 * margin), frame_shape
    )


def _full_bbox(frame: np.ndarray) -> tuple[int, int, int, int]:
    height, width = frame.shape[:2]
    return 0, 0, width, height


def _clamp_bbox(bbox, shape) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    x, y, w, h = (int(round(value)) for value in bbox)
    x = min(width - 1, max(0, x))
    y = min(height - 1, max(0, y))
    right = min(width, max(x + 1, x + max(w, 1)))
    bottom = min(height, max(y + 1, y + max(h, 1)))
    return x, y, right - x, bottom - y


def _bbox_iou(first, second) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _to_gray(frame: np.ndarray) -> np.ndarray:
    return frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
