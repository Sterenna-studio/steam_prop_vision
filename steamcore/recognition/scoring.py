"""
steamcore/recognition/scoring.py
Modes de score L3 (pur : aucune image, aucun OpenCV).

Le score historique ("global") vaut  bons_matchs / max(points_template,
points_requête). Le dénominateur contient les points de la REQUÊTE : un doigt,
une main ou un arrière-plan chargé ajoutent leurs propres points, donc le
score baisse alors même que la carte visible matche aussi bien qu'avant. Une
partie masquée retire en plus de vrais matchs. D'où deux modes tolérants :

- "template" : bons_matchs / points_template. Ne dépend plus de ce qu'il y a
  autour de la carte ; seule la part de la carte retrouvée compte.
- "zones"    : la carte (référence) est découpée en 2x2 ; chaque zone a son
  score template-normalisé ; on moyenne les `top_zones` meilleures (3 sur 4
  par défaut), donc une zone entièrement masquée ne noie pas le score.

Le mode par défaut reste "global" : les échelles de score diffèrent selon le
mode, tout changement de mode impose de recalibrer les seuils au benchmark.
"""

from __future__ import annotations

import numpy as np

SCORE_MODES = ("global", "template", "zones")
ZONE_GRID = 2
N_ZONES = ZONE_GRID * ZONE_GRID
MIN_ZONE_KEYPOINTS = 3  # zone de référence trop pauvre : ignorée


def zone_layout(points: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """(zone de chaque point, nombre de points par zone) pour des points (N,2)
    en coordonnées de l'image de référence `size` x `size`."""
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    cell = size / ZONE_GRID
    cols = np.clip((pts[:, 0] // cell).astype(int), 0, ZONE_GRID - 1)
    rows = np.clip((pts[:, 1] // cell).astype(int), 0, ZONE_GRID - 1)
    ids = rows * ZONE_GRID + cols
    return ids, np.bincount(ids, minlength=N_ZONES)


def score_matches(
    mode: str,
    n_good: int,
    n_ref: int,
    n_query: int,
    good_zone_counts: np.ndarray | None = None,
    ref_zone_counts: np.ndarray | None = None,
    top_zones: int = 3,
) -> float:
    if mode == "global":
        return n_good / max(n_ref, n_query, 1)
    if mode == "template":
        return n_good / max(n_ref, 1)
    if mode == "zones":
        if good_zone_counts is None or ref_zone_counts is None:
            return n_good / max(n_ref, 1)
        valid = ref_zone_counts >= MIN_ZONE_KEYPOINTS
        if not valid.any():
            return n_good / max(n_ref, 1)
        per_zone = good_zone_counts[valid] / ref_zone_counts[valid]
        best = np.sort(per_zone)[::-1][: max(1, top_zones)]
        return float(best.mean())
    raise ValueError(f"score_mode inconnu : {mode!r} (attendu : {SCORE_MODES})")
