"""Estimation d'homographie instrumentée et sélection RANSAC/MAGSAC."""

from __future__ import annotations

from dataclasses import dataclass
import time

import cv2
import numpy as np


@dataclass
class HomographyResult:
    matrix: np.ndarray | None
    mask: np.ndarray | None
    requested_estimator: str
    estimator: str
    fallback_used: bool
    match_count: int
    inlier_count: int
    inlier_ratio: float
    reprojection_error: float | None
    latency_ms: float


def resolve_estimator(name: str) -> tuple[int, str, bool]:
    normalized = name.lower()
    if normalized == "ransac":
        return cv2.RANSAC, "ransac", False
    if normalized not in {"magsac", "usac_magsac"}:
        raise ValueError(f"Estimateur d'homographie inconnu: {name}")
    if hasattr(cv2, "USAC_MAGSAC"):
        return cv2.USAC_MAGSAC, "magsac", False
    return cv2.RANSAC, "ransac", True


def estimate_homography(
    source_points: np.ndarray,
    destination_points: np.ndarray,
    estimator: str = "ransac",
    reprojection_threshold: float = 5.0,
) -> HomographyResult:
    requested = estimator.lower()
    method, used, fallback = resolve_estimator(requested)
    started = time.perf_counter()
    matrix, mask = cv2.findHomography(
        source_points,
        destination_points,
        method,
        reprojection_threshold,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    match_count = len(source_points)
    inlier_count = int(mask.sum()) if mask is not None else 0
    inlier_ratio = inlier_count / match_count if match_count else 0.0
    error = _median_reprojection_error(matrix, source_points, destination_points, mask)
    return HomographyResult(
        matrix=matrix,
        mask=mask,
        requested_estimator=requested,
        estimator=used,
        fallback_used=fallback,
        match_count=match_count,
        inlier_count=inlier_count,
        inlier_ratio=inlier_ratio,
        reprojection_error=error,
        latency_ms=latency_ms,
    )


def _median_reprojection_error(
    matrix: np.ndarray | None,
    source_points: np.ndarray,
    destination_points: np.ndarray,
    mask: np.ndarray | None,
) -> float | None:
    if matrix is None or len(source_points) == 0:
        return None
    projected = cv2.perspectiveTransform(
        source_points.reshape(-1, 1, 2), matrix
    ).reshape(-1, 2)
    expected = destination_points.reshape(-1, 2)
    errors = np.linalg.norm(projected - expected, axis=1)
    if mask is not None:
        selected = mask.reshape(-1).astype(bool)
        errors = errors[selected]
    if len(errors) == 0:
        return None
    return float(np.median(errors))
