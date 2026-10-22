"""Modes de score L3 : fonction pure + effet réel sur une occlusion synthétique."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from steamcore.recognition.card_recognizer import CardRecognizer
from steamcore.recognition.scoring import (
    N_ZONES,
    SCORE_MODES,
    score_matches,
    zone_layout,
)


def test_zone_layout_assigns_quadrants():
    pts = np.array([[10, 10], [390, 10], [10, 390], [390, 390], [200, 200]])
    ids, counts = zone_layout(pts, 400)
    assert ids.tolist() == [0, 1, 2, 3, 3]
    assert counts.tolist() == [1, 1, 1, 2]


def test_zone_layout_clips_points_on_border():
    ids, _ = zone_layout(np.array([[400, 400], [-5, -5]]), 400)
    assert ids.tolist() == [3, 0]


def test_global_matches_historical_formula():
    assert score_matches("global", 30, 100, 150) == pytest.approx(30 / 150)
    assert score_matches("global", 30, 200, 150) == pytest.approx(30 / 200)


def test_template_ignores_query_clutter():
    # 30 bons matchs sur 100 points template : un doigt qui ajoute 400 points
    # côté requête ne doit plus changer le score.
    assert score_matches("template", 30, 100, 150) == pytest.approx(0.30)
    assert score_matches("template", 30, 100, 550) == pytest.approx(0.30)
    assert score_matches("global", 30, 100, 550) < 0.06


def test_zones_ignore_one_fully_masked_zone():
    ref = np.array([25, 25, 25, 25])
    good = np.array([10, 10, 10, 0])  # 4e zone entièrement masquée
    assert score_matches("zones", 30, 100, 100, good, ref) == pytest.approx(0.4)
    assert score_matches("zones", 30, 100, 100, good, ref, top_zones=4) == (
        pytest.approx(0.3)
    )


def test_zones_skips_poor_reference_zones():
    ref = np.array([40, 40, 40, 1])  # zone 4 quasi vide : non fiable
    good = np.array([8, 8, 8, 0])
    assert score_matches("zones", 24, 121, 120, good, ref) == pytest.approx(0.2)


def test_zones_falls_back_without_zone_info():
    assert score_matches("zones", 20, 100, 100) == pytest.approx(0.2)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        score_matches("bogus", 1, 1, 1)
    with pytest.raises(ValueError):
        CardRecognizer(platest_dir="inexistant", score_mode="bogus")
    assert N_ZONES == 4 and "zones" in SCORE_MODES


# ── Effet réel sur une carte synthétique partiellement masquée ──────────


def _pattern(size=400, seed=0):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 256, (size, size), dtype=np.uint8)
    for _ in range(40):
        cx, cy = rng.integers(30, size - 30, 2).tolist()
        cv2.circle(
            img, (cx, cy), int(rng.integers(5, 25)), int(rng.integers(30, 220)), -1
        )
    return img


@pytest.fixture
def platest(tmp_path):
    card = tmp_path / "PLATEST" / "plate_a"
    card.mkdir(parents=True)
    cv2.imwrite(str(card / "a.jpg"), _pattern())
    return str(tmp_path / "PLATEST")


def _occluded():
    """La carte avec un quart masqué par une zone de texture parasite."""
    img = _pattern().copy()
    rng = np.random.default_rng(99)
    img[200:400, 200:400] = rng.integers(0, 256, (200, 200), dtype=np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _score(platest, mode, image):
    rec = CardRecognizer(platest, min_matches=1, threshold=0.0, score_mode=mode)
    rec.recognize_candidates(image)
    return rec.last_score


def test_tolerant_modes_score_occluded_card_higher_than_global(platest):
    frame = _occluded()
    g = _score(platest, "global", frame)
    t = _score(platest, "template", frame)
    z = _score(platest, "zones", frame)
    assert t >= g and z > g


def test_clean_card_scores_high_in_every_mode(platest):
    clean = cv2.cvtColor(_pattern(), cv2.COLOR_GRAY2BGR)
    for mode in SCORE_MODES:
        assert _score(platest, mode, clean) > 0.5, mode
