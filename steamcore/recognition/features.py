"""Backends de points d'intérêt classiques partagés par L2 et le benchmark."""

from __future__ import annotations

from dataclasses import dataclass

import cv2


@dataclass(frozen=True)
class FeatureBackend:
    name: str
    extractor: object
    matcher: object
    cache_key: str


def create_feature_backend(name: str, nfeatures: int = 600) -> FeatureBackend:
    """Construit un couple extracteur/matcher sans dépendance hors OpenCV."""
    normalized = name.lower()
    if normalized == "orb":
        extractor = cv2.ORB_create(nfeatures=nfeatures)
        norm = cv2.NORM_HAMMING
        cache_key = f"orb:{nfeatures}"
    elif normalized == "sift":
        if not hasattr(cv2, "SIFT_create"):
            raise RuntimeError("SIFT n'est pas disponible dans cette version d'OpenCV")
        extractor = cv2.SIFT_create(nfeatures=nfeatures)
        norm = cv2.NORM_L2
        cache_key = f"sift:{nfeatures}"
    elif normalized == "akaze":
        if not hasattr(cv2, "AKAZE_create"):
            raise RuntimeError("AKAZE n'est pas disponible dans cette version d'OpenCV")
        extractor = cv2.AKAZE_create()
        norm = cv2.NORM_HAMMING
        cache_key = "akaze:default"
    else:
        raise ValueError(f"Backend de features inconnu: {name}")

    return FeatureBackend(
        name=normalized,
        extractor=extractor,
        matcher=cv2.BFMatcher(norm),
        cache_key=cache_key,
    )


def available_feature_backends() -> list[str]:
    names = ["orb"]
    if hasattr(cv2, "SIFT_create"):
        names.append("sift")
    if hasattr(cv2, "AKAZE_create"):
        names.append("akaze")
    return names
