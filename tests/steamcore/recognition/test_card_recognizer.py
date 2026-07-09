"""
tests/steamcore/recognition/test_card_recognizer.py
Tests unitaires pour CardRecognizer.

Hypothèses :
- CardRecognizer avec PLATEST vide → aucune carte chargée
- CardRecognizer avec un template synthétique → reconnaissance basique
- reload() recharge les templates
- hint_id filtre les templates testés
"""
from __future__ import annotations
import numpy as np
import cv2
import pytest
from pathlib import Path

from steamcore.recognition.card_recognizer import CardRecognizer, RecognitionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gray_pattern(size: int = 400, seed: int = 42) -> np.ndarray:
    """Génère une image synthétique reproductible avec des features ORB détectables."""
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 256, (size, size), dtype=np.uint8)
    # Ajouter des cercles pour des keypoints stables
    for i in range(20):
        cx, cy = int(rng.integers(50, size - 50, 2))
        cv2.circle(img, (cx, cy), int(rng.integers(5, 20)), int(rng.integers(50, 200)), -1)
    return img


def _make_bgr(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_platest(tmp_path) -> Path:
    """Dossier PLATEST vide."""
    p = tmp_path / "PLATEST"
    p.mkdir()
    return p


@pytest.fixture
def single_card_platest(tmp_path) -> tuple[Path, str]:
    """PLATEST avec une seule carte plate_test, une image synthétique."""
    platest = tmp_path / "PLATEST"
    card_dir = platest / "plate_test"
    card_dir.mkdir(parents=True)
    img = _make_bgr(_make_gray_pattern(400, seed=0))
    cv2.imwrite(str(card_dir / "source.jpg"), img)
    return platest, "plate_test"


@pytest.fixture
def recognizer_empty(empty_platest) -> CardRecognizer:
    return CardRecognizer(platest_dir=str(empty_platest), min_matches=4, threshold=0.01)


@pytest.fixture
def recognizer_single(single_card_platest) -> tuple[CardRecognizer, str]:
    platest, card_id = single_card_platest
    rec = CardRecognizer(platest_dir=str(platest), min_matches=4, threshold=0.01)
    return rec, card_id


# ---------------------------------------------------------------------------
# Tests — PLATEST vide
# ---------------------------------------------------------------------------

class TestEmptyPlatest:
    def test_no_templates_loaded(self, recognizer_empty):
        assert len(recognizer_empty.card_ids) == 0

    def test_recognize_returns_none_on_empty(self, recognizer_empty):
        frame = _make_bgr(_make_gray_pattern())
        result = recognizer_empty.recognize(frame)
        assert result is None

    def test_recognize_black_frame_returns_none(self, recognizer_empty):
        black = np.zeros((400, 400, 3), dtype=np.uint8)
        result = recognizer_empty.recognize(black)
        assert result is None


# ---------------------------------------------------------------------------
# Tests — CardRecognizer avec un template
# ---------------------------------------------------------------------------

class TestSingleCard:
    def test_card_loaded(self, recognizer_single):
        rec, card_id = recognizer_single
        assert card_id in rec.card_ids

    def test_recognize_same_image_returns_result(self, recognizer_single, single_card_platest):
        """Reconnaître l'image source elle-même doit retourner un match."""
        rec, card_id = recognizer_single
        platest, _ = single_card_platest
        img_path = platest / card_id / "source.jpg"
        frame = cv2.imread(str(img_path))
        assert frame is not None, "Image source introuvable"
        result = rec.recognize(frame)
        assert result is not None
        assert result.card_id == card_id
        assert isinstance(result.score, float)
        assert result.score >= 0.0
        assert result.matches >= 0

    def test_result_has_label(self, recognizer_single, single_card_platest):
        rec, card_id = recognizer_single
        platest, _ = single_card_platest
        frame = cv2.imread(str(platest / card_id / "source.jpg"))
        result = rec.recognize(frame)
        assert result is not None
        assert result.label == "Test"  # plate_test → Test

    def test_black_frame_returns_none(self, recognizer_single):
        rec, _ = recognizer_single
        black = np.zeros((400, 400, 3), dtype=np.uint8)
        result = rec.recognize(black)
        assert result is None

    def test_hint_id_correct_finds_card(self, recognizer_single, single_card_platest):
        """hint_id correct → cherche uniquement sur cette carte."""
        rec, card_id = recognizer_single
        platest, _ = single_card_platest
        frame = cv2.imread(str(platest / card_id / "source.jpg"))
        result = rec.recognize(frame, hint_id=card_id)
        assert result is not None
        assert result.card_id == card_id

    def test_hint_id_wrong_does_not_crash(self, recognizer_single, single_card_platest):
        """hint_id inconnu → fallback sur tous les templates, pas de crash."""
        rec, card_id = recognizer_single
        platest, _ = single_card_platest
        frame = cv2.imread(str(platest / card_id / "source.jpg"))
        result = rec.recognize(frame, hint_id="plate_inexistant")
        # Doit soit matcher (fallback) soit retourner None — jamais crasher
        assert result is None or isinstance(result, RecognitionResult)


# ---------------------------------------------------------------------------
# Tests — reload()
# ---------------------------------------------------------------------------

class TestReload:
    def test_reload_empty_clears_templates(self, recognizer_single, single_card_platest):
        """Après suppression du dossier, reload() vide les templates."""
        import shutil
        rec, card_id = recognizer_single
        platest, _ = single_card_platest
        assert card_id in rec.card_ids
        # Supprimer le dossier carte
        shutil.rmtree(platest / card_id)
        rec.reload()
        assert card_id not in rec.card_ids

    def test_reload_adds_new_card(self, recognizer_empty, empty_platest):
        """Ajout d'une carte puis reload() la charge."""
        assert len(recognizer_empty.card_ids) == 0
        # Créer une nouvelle carte
        card_dir = empty_platest / "plate_new"
        card_dir.mkdir()
        img = _make_bgr(_make_gray_pattern(400, seed=99))
        cv2.imwrite(str(card_dir / "source.jpg"), img)
        recognizer_empty.reload()
        assert "plate_new" in recognizer_empty.card_ids


# ---------------------------------------------------------------------------
# Tests — RecognitionResult dataclass
# ---------------------------------------------------------------------------

class TestRecognitionResult:
    def test_dataclass_fields(self):
        r = RecognitionResult(
            card_id="plate_x", label="X", score=0.85, matches=12, matched_img="source.jpg"
        )
        assert r.card_id == "plate_x"
        assert r.label == "X"
        assert r.score == 0.85
        assert r.matches == 12
        assert r.matched_img == "source.jpg"

    def test_default_matched_img_is_empty(self):
        r = RecognitionResult(card_id="x", label="X", score=0.5, matches=5)
        assert r.matched_img == ""
