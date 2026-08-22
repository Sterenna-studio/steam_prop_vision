"""
steamcore/recognition/card_detector.py
Niveau 2 -- identification precise sur ROI.
Supporte ORB (baseline), SIFT et AKAZE.
Travaille sur la ROI retournee par FastDetector.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .features import create_feature_backend
from .homography import estimate_homography
from .template_registry import TemplateRegistry

_MIN_KEYPOINTS = 6


@dataclass
class CardRegion:
    warped: np.ndarray
    corners: np.ndarray
    match_count: int
    card_id: str | None = None


@dataclass
class CardCandidate:
    card_id: str
    match_count: int
    inlier_count: int
    inlier_ratio: float
    homography_quality: float
    reprojection_error: float | None
    corners: np.ndarray
    warped: np.ndarray
    score: float
    quadrilateral_area: float
    geometry_valid: bool
    homography_backend: str
    homography_fallback_used: bool
    homography_latency_ms: float


class CardDetector:
    """
    backend : "orb"  -> ORB  ~15-25fps sur Pi 5 sur ROI
    backend : "sift" -> SIFT ~10-15fps sur Pi 5 sur ROI
    backend : "akaze" -> AKAZE, à mesurer sur Pi 5
    """

    WARP_SIZE = 400

    def __init__(
        self,
        platest_dir: str = "PLATEST",
        backend: str = "orb",
        min_matches: int = 8,
        min_inliers: int = 6,
        ratio_test: float = 0.75,
        homography: str = "ransac",
        registry: TemplateRegistry | None = None,
    ):
        self.platest_dir = platest_dir
        self.backend = backend.lower()
        self.min_matches = min_matches
        self.min_inliers = min_inliers
        self.ratio_test = ratio_test
        self.homography = homography.lower()
        # Registre partagé avec CardRecognizer si fourni (évite de relire les
        # mêmes images PLATEST deux fois) — sinon un registre privé, non
        # partagé, pour rester utilisable de façon autonome (tests, outils).
        self._registry = registry or TemplateRegistry(platest_dir)
        self._templates: list = []
        self._build_matcher()
        self._load_templates()

    def load_config(self, cfg: dict):
        cd = cfg.get("card_detector", {})
        self.backend = cd.get("backend", self.backend)
        self.min_matches = cd.get("min_matches", self.min_matches)
        self.min_inliers = cd.get("min_inliers", self.min_inliers)
        self.ratio_test = cd.get("ratio_test", self.ratio_test)
        self.homography = cd.get("homography", self.homography)
        self._build_matcher()
        self.reload()

    def _build_matcher(self):
        self._nfeatures = 800 if self.backend == "sift" else 600
        feature_backend = create_feature_backend(self.backend, self._nfeatures)
        self._feat = feature_backend.extractor
        self._matcher = feature_backend.matcher
        self._cache_key = feature_backend.cache_key

    # ── public ───────────────────────────────────────────────────────────────

    def detect(self, roi: np.ndarray) -> CardRegion | None:
        """Retourne le meilleur candidat avec le contrat historique."""
        candidates = self.detect_candidates(roi, top_k=1)
        if not candidates:
            return None
        best = candidates[0]
        return CardRegion(
            warped=best.warped,
            corners=best.corners,
            # Historiquement match_count contenait le nombre d'inliers.
            match_count=best.inlier_count,
            card_id=best.card_id,
        )

    def detect_candidates(self, roi: np.ndarray, top_k: int = 1) -> list[CardCandidate]:
        """Retourne jusqu'à ``top_k`` candidats L2, triés comme le baseline.

        Le nombre d'inliers reste le seul critère de tri afin que ``detect()``
        conserve le choix historique. Le score normalisé sert à mesurer la marge.
        """
        if top_k < 1:
            raise ValueError("top_k doit être supérieur ou égal à 1")
        gray = self._to_gray(roi)
        kps_f, desc_f = self._feat.detectAndCompute(gray, None)
        if desc_f is None or len(kps_f) < self.min_matches:
            return []
        candidates = []
        for tmpl in self._templates:
            candidate = self._match(tmpl, kps_f, desc_f, roi)
            if candidate is not None:
                candidates.append(candidate)
        # Tri stable sur le nombre d'inliers uniquement : en cas d'égalité,
        # l'ordre PLATEST historique est conservé par Python.
        candidates.sort(key=lambda candidate: candidate.inlier_count, reverse=True)
        return candidates[:top_k]

    def reload(self):
        self._registry.invalidate()
        self._templates.clear()
        self._load_templates()

    @property
    def card_ids(self) -> list:
        return [t.card_id for t in self._templates]

    # ── private ──────────────────────────────────────────────────────────────

    def _load_templates(self):
        by_card = self._registry.get_templates(
            self._feat,
            self._cache_key,
            resize=None,
            min_keypoints=_MIN_KEYPOINTS,
        )
        for card_id, entries in by_card.items():
            tmpl = _Template(card_id)
            tmpl.descs = [(kps, desc, h, w) for (_name, kps, desc, h, w) in entries]
            self._templates.append(tmpl)
            print(f"[detector] loaded {card_id} ({len(tmpl.descs)} imgs)")
        print(
            "[detector] "
            + str(len(self._templates))
            + " templates charges (backend="
            + self.backend
            + ")"
        )

    def _match(self, tmpl, kps_f, desc_f, roi):
        best_inliers = 0
        best_H = None
        best_sz = None
        best_stats = None
        for kps_t, desc_t, th, tw in tmpl.descs:
            pairs = self._matcher.knnMatch(desc_t, desc_f, k=2)
            good = []
            for pair in pairs:
                if len(pair) == 2:
                    m, n = pair
                    if m.distance < self.ratio_test * n.distance:
                        good.append(m)
            if len(good) < self.min_matches:
                continue
            pts_t = np.float32([kps_t[m.queryIdx].pt for m in good])
            pts_f = np.float32([kps_f[m.trainIdx].pt for m in good])
            stats = estimate_homography(
                pts_t, pts_f, estimator=self.homography, reprojection_threshold=5.0
            )
            if stats.matrix is None:
                continue
            inliers = stats.inlier_count
            if inliers >= self.min_inliers and inliers > best_inliers:
                best_inliers = inliers
                best_H = stats.matrix
                best_sz = (tw, th)
                best_stats = stats
        if best_H is None:
            return None
        w, h = best_sz
        c_t = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        c_f = cv2.perspectiveTransform(c_t, best_H).reshape(-1, 2)
        geometry_valid = _valid_quad(c_f, roi.shape)
        if not geometry_valid:
            return None
        M = cv2.getPerspectiveTransform(
            c_f.astype(np.float32),
            np.float32(
                [
                    [0, 0],
                    [self.WARP_SIZE - 1, 0],
                    [self.WARP_SIZE - 1, self.WARP_SIZE - 1],
                    [0, self.WARP_SIZE - 1],
                ]
            ),
        )
        warped = cv2.warpPerspective(roi, M, (self.WARP_SIZE, self.WARP_SIZE))
        area = float(cv2.contourArea(c_f.astype(np.float32)))
        geometry_quality = min(1.0, area / max(roi.shape[0] * roi.shape[1] * 0.1, 1))
        reprojection_quality = 1.0 / (1.0 + (best_stats.reprojection_error or 0.0))
        inlier_strength = best_stats.inlier_count / (
            best_stats.inlier_count + max(self.min_inliers, 1)
        )
        quality = float(
            np.clip(
                best_stats.inlier_ratio
                * reprojection_quality
                * geometry_quality
                * inlier_strength,
                0.0,
                1.0,
            )
        )
        return CardCandidate(
            card_id=tmpl.card_id,
            match_count=best_stats.match_count,
            inlier_count=best_stats.inlier_count,
            inlier_ratio=best_stats.inlier_ratio,
            homography_quality=quality,
            reprojection_error=best_stats.reprojection_error,
            corners=c_f,
            warped=warped,
            score=float(inlier_strength),
            quadrilateral_area=area,
            geometry_valid=geometry_valid,
            homography_backend=best_stats.estimator,
            homography_fallback_used=best_stats.fallback_used,
            homography_latency_ms=best_stats.latency_ms,
        )

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        return (
            frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        )


def _valid_quad(corners: np.ndarray, shape) -> bool:
    h, w = shape[:2]
    for x, y in corners:
        if x < 0 or y < 0 or x > w or y > h:
            return False
    return cv2.contourArea(corners.astype(np.float32)) > 500


class _Template:
    """Conteneur simple : le chargement réel passe par TemplateRegistry."""

    def __init__(self, card_id: str):
        self.card_id = card_id
        self.descs: list = []
