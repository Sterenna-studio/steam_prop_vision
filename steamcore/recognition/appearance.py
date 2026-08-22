"""L3 léger fondé sur l'apparence globale d'une image rectifiée."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ._images import find_template_images
from .thresholds import RecognitionThresholds


@dataclass
class AppearanceResult:
    card_id: str
    score: float
    intensity_score: float
    gradient_score: float
    matched_img: str
    threshold_used: float
    accepted: bool


class GlobalAppearanceRecognizer:
    """Compare intensité normalisée et gradients Sobel, sans keypoints."""

    def __init__(
        self,
        platest_dir: str = "PLATEST",
        threshold: float = 0.55,
        thresholds: RecognitionThresholds | None = None,
        size: int = 256,
    ):
        self.platest_dir = Path(platest_dir)
        self.size = size
        self.thresholds = thresholds or RecognitionThresholds(
            default_threshold=threshold
        )
        self._templates: dict[str, list[tuple[str, np.ndarray, np.ndarray]]] = {}
        self.reload()

    @property
    def card_ids(self) -> list[str]:
        return sorted(self._templates)

    def reload(self) -> None:
        self._templates.clear()
        if not self.platest_dir.exists():
            return
        for directory in sorted(self.platest_dir.iterdir()):
            if not directory.is_dir():
                continue
            entries = []
            for path in find_template_images(directory):
                image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if image is None:
                    continue
                normalized, gradient = self._prepare(image)
                entries.append((path.name, normalized, gradient))
            if entries:
                self._templates[directory.name] = entries

    def compare_candidates(
        self, warped: np.ndarray, candidate_ids: list[str] | None = None
    ) -> list[AppearanceResult]:
        gray = warped
        if warped.ndim == 3:
            gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        query, query_gradient = self._prepare(gray)
        ids = candidate_ids or self.card_ids
        results = []
        for card_id in ids:
            best: AppearanceResult | None = None
            threshold = self.thresholds.resolve(card_id)
            for image_name, reference, reference_gradient in self._templates.get(
                card_id, []
            ):
                intensity = _cosine_similarity(query, reference)
                gradient = _cosine_similarity(query_gradient, reference_gradient)
                score = 0.6 * intensity + 0.4 * gradient
                result = AppearanceResult(
                    card_id=card_id,
                    score=float(np.clip(score, 0.0, 1.0)),
                    intensity_score=intensity,
                    gradient_score=gradient,
                    matched_img=image_name,
                    threshold_used=threshold,
                    accepted=score >= threshold,
                )
                if best is None or result.score > best.score:
                    best = result
            if best is not None:
                results.append(best)
        return sorted(results, key=lambda result: result.score, reverse=True)

    def recognize(
        self, warped: np.ndarray, candidate_ids: list[str] | None = None
    ) -> AppearanceResult | None:
        return next(
            (
                result
                for result in self.compare_candidates(warped, candidate_ids)
                if result.accepted
            ),
            None,
        )

    def _prepare(self, image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        resized = cv2.resize(image, (self.size, self.size)).astype(np.float32)
        normalized = _standardize(resized)
        grad_x = cv2.Sobel(resized, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(resized, cv2.CV_32F, 0, 1, ksize=3)
        gradient = _standardize(cv2.magnitude(grad_x, grad_y))
        return normalized, gradient


def _standardize(image: np.ndarray) -> np.ndarray:
    std = float(image.std())
    if std < 1e-6:
        return np.zeros_like(image, dtype=np.float32)
    return ((image - float(image.mean())) / std).astype(np.float32)


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator < 1e-9:
        return 0.0
    correlation = float(np.dot(left.ravel(), right.ravel()) / denominator)
    return max(0.0, min(1.0, correlation))
