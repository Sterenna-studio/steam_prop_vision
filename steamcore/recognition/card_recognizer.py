"""
steamcore/recognition/card_recognizer.py

Logique de reconnaissance :
  - Chaque plaque peut avoir N images dans son dossier PLATEST (ex: bougie.jpg,
    bougie_top.jpg, bougie_bottom.jpg, bougie_left.jpg, bougie_right.jpg).
  - Pour chaque image template, on tente un match ORB global.
  - Si AU MOINS UNE image template matche (score >= threshold ET matches >= min_matches)
    → la plaque est validée.
  - Le score final retourné est le meilleur score parmi toutes les images.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .template_registry import TemplateRegistry
from .thresholds import RecognitionThresholds

_NFEATURES = 800
_MIN_KEYPOINTS = 4


@dataclass
class RecognitionResult:
    card_id: str
    label: str
    score: float
    matches: int
    matched_img: str = ""  # nom de l'image qui a matché
    threshold_used: float = 0.0


@dataclass
class RecognitionCandidate:
    card_id: str
    score: float
    matches: int
    matched_img: str
    threshold_used: float
    accepted: bool


class CardRecognizer:
    WARP_SIZE = 400
    RATIO_TEST = 0.75

    def __init__(
        self,
        platest_dir: str = "PLATEST",
        min_matches: int = 6,
        threshold: float = 0.03,
        thresholds: RecognitionThresholds | None = None,
        registry: TemplateRegistry | None = None,
    ):
        self.platest_dir = platest_dir
        self.min_matches = min_matches
        self.thresholds = thresholds or RecognitionThresholds(
            default_threshold=threshold
        )
        self._orb = cv2.ORB_create(nfeatures=_NFEATURES)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        # Registre partagé avec CardDetector si fourni (évite de relire les
        # mêmes images PLATEST deux fois) — sinon un registre privé, non
        # partagé, pour rester utilisable de façon autonome (tests, outils).
        self._registry = registry or TemplateRegistry(platest_dir)
        self._templates: list = []
        self._load()

        # Dernier score tenté, mis à jour à CHAQUE appel de recognize() —
        # y compris sous le seuil (recognize() retourne None dans ce cas).
        # Permet un affichage continu (ex: /view) sans changer le contrat
        # de recognize() ni casser les appelants existants.
        self.last_score = 0.0
        self.last_card_id: str | None = None
        # Métriques de coût du dernier appel — utile pour vérifier l'effet
        # de hint_id (doit réduire drastiquement templates/images scannés).
        self.last_templates_scanned = 0
        self.last_images_scanned = 0

    def load_config(self, cfg: dict):
        det = cfg.get("detection", {})
        self.min_matches = det.get("min_matches", self.min_matches)
        legacy_default = det.get("threshold", self.threshold)
        self.thresholds = RecognitionThresholds.from_config(cfg, legacy_default)
        self.reload()

    def recognize(self, warped: np.ndarray, hint_id: str | None = None):
        candidates = self.recognize_candidates(
            warped,
            hint_ids=[hint_id] if hint_id else None,
            fallback_on_unknown_hint=True,
        )
        accepted = next(
            (candidate for candidate in candidates if candidate.accepted), None
        )
        if accepted is None:
            return None

        label = accepted.card_id.replace("plate_", "").replace("_", " ").capitalize()
        return RecognitionResult(
            card_id=accepted.card_id,
            label=label,
            score=round(accepted.score, 4),
            matches=accepted.matches,
            matched_img=accepted.matched_img,
            threshold_used=accepted.threshold_used,
        )

    def recognize_candidates(
        self,
        warped: np.ndarray,
        hint_ids: list[str] | None = None,
        fallback_on_unknown_hint: bool = False,
    ) -> list[RecognitionCandidate]:
        """Score les candidats L3, y compris ceux situés sous leur seuil."""
        gray = self._to_gray(warped)
        gray = cv2.resize(gray, (self.WARP_SIZE, self.WARP_SIZE))

        kps_q, desc_q = self._orb.detectAndCompute(gray, None)
        if desc_q is None:
            self.last_score = 0.0
            self.last_card_id = None
            self.last_templates_scanned = 0
            self.last_images_scanned = 0
            return []

        templates = self._templates
        if hint_ids:
            requested = set(hint_ids)
            filtered = [t for t in self._templates if t.card_id in requested]
            if filtered or not fallback_on_unknown_hint:
                templates = filtered

        self.last_templates_scanned = len(templates)
        self.last_images_scanned = sum(len(t.images) for t in templates)

        candidates = []
        for tmpl in templates:
            best_score, best_matches, best_img = 0.0, 0, ""
            # Tente chaque image du template — valide si UNE seule matche
            for img_name, kps_r, desc_r in tmpl.images:
                try:
                    ms = self._matcher.knnMatch(desc_q, desc_r, k=2)
                    good = []
                    for pair in ms:
                        if len(pair) == 2:
                            match, neighbor = pair
                            if match.distance < self.RATIO_TEST * neighbor.distance:
                                good.append(match)
                    score = len(good) / max(len(kps_r), len(kps_q), 1)
                    if score > best_score:
                        best_score = score
                        best_matches = len(good)
                        best_img = img_name
                except Exception:
                    continue
            threshold = self.thresholds.resolve(tmpl.card_id)
            candidates.append(
                RecognitionCandidate(
                    card_id=tmpl.card_id,
                    score=best_score,
                    matches=best_matches,
                    matched_img=best_img,
                    threshold_used=threshold,
                    accepted=(
                        best_score >= threshold and best_matches >= self.min_matches
                    ),
                )
            )

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        best = candidates[0] if candidates else None
        self.last_score = best.score if best else 0.0
        self.last_card_id = best.card_id if best else None
        return candidates

    @property
    def threshold(self) -> float:
        return self.thresholds.default_threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self.thresholds.default_threshold = float(value)

    def reload(self):
        self._registry.invalidate()
        self._templates.clear()
        self._load()

    @property
    def card_ids(self) -> list:
        return [t.card_id for t in self._templates]

    def _load(self):
        cache_key = f"orb:{_NFEATURES}"
        by_card = self._registry.get_templates(
            self._orb, cache_key, resize=self.WARP_SIZE, min_keypoints=_MIN_KEYPOINTS
        )
        for card_id, entries in by_card.items():
            tmpl = _OrbTemplate(card_id)
            tmpl.images = [(name, kps, desc) for (name, kps, desc, _h, _w) in entries]
            self._templates.append(tmpl)
            print(f"[recognizer] {card_id} ({len(tmpl.images)} imgs)")
        print(f"[recognizer] {len(self._templates)} cartes chargees")

    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        return img if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


class _OrbTemplate:
    """Conteneur simple : le chargement réel passe par TemplateRegistry."""

    def __init__(self, card_id: str):
        self.card_id = card_id
        self.images: list = []  # [(nom_fichier, kps, desc), ...]
