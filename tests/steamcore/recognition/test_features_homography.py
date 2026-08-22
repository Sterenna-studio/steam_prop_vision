from __future__ import annotations

import cv2
import numpy as np
import pytest

from steamcore.recognition import homography
from steamcore.recognition.card_detector import CardDetector
from steamcore.recognition.features import create_feature_backend
from steamcore.recognition.homography import estimate_homography, resolve_estimator


def _pattern(seed: int, size: int = 320) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 256, (size, size), dtype=np.uint8)
    cv2.putText(image, f"STEAM-{seed}", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 1, 255, 3)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)


@pytest.mark.parametrize("backend", ["orb", "akaze"])
def test_binary_feature_backends(backend):
    if backend == "akaze" and not hasattr(cv2, "AKAZE_create"):
        pytest.skip("AKAZE absent de cette build OpenCV hors contrainte projet")
    feature = create_feature_backend(backend)
    keypoints, descriptors = feature.extractor.detectAndCompute(_pattern(1), None)
    assert keypoints
    assert descriptors is not None


def test_sift_backend_if_available():
    if not hasattr(cv2, "SIFT_create"):
        pytest.skip("SIFT absent de cette build OpenCV")
    feature = create_feature_backend("sift")
    assert feature.name == "sift"


def test_unknown_feature_backend_rejected():
    with pytest.raises(ValueError):
        create_feature_backend("unknown")


@pytest.mark.parametrize("backend", ["orb", "sift", "akaze"])
def test_detector_backends_and_top_k(tmp_path, backend):
    if backend == "sift" and not hasattr(cv2, "SIFT_create"):
        pytest.skip("SIFT absent de cette build OpenCV")
    if backend == "akaze" and not hasattr(cv2, "AKAZE_create"):
        pytest.skip("AKAZE absent de cette build OpenCV hors contrainte projet")
    platest = tmp_path / "PLATEST"
    for index in (1, 2):
        directory = platest / f"plate_{index}"
        directory.mkdir(parents=True)
        cv2.imwrite(str(directory / "source.png"), _pattern(index))
    detector = CardDetector(str(platest), backend=backend, min_matches=4, min_inliers=4)
    roi = cv2.copyMakeBorder(
        _pattern(1), 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(127, 127, 127)
    )
    candidates = detector.detect_candidates(roi, top_k=2)
    assert candidates
    assert candidates[0].card_id == "plate_1"
    assert candidates[0].match_count >= candidates[0].inlier_count
    assert 0.0 <= candidates[0].score <= 1.0
    assert len(candidates) <= 2
    legacy = detector.detect(roi)
    assert legacy is not None
    assert legacy.card_id == "plate_1"


def test_ransac_homography_metrics():
    source = np.float32([[0, 0], [10, 0], [10, 10], [0, 10], [5, 5]])
    destination = source + np.float32([4, 7])
    result = estimate_homography(source, destination, "ransac", 1.0)
    assert result.matrix is not None
    assert result.estimator == "ransac"
    assert result.inlier_count == 5
    assert result.inlier_ratio == 1.0
    assert result.reprojection_error is not None
    assert result.reprojection_error < 1e-4


def test_magsac_selection_when_available():
    method, used, fallback = resolve_estimator("magsac")
    if hasattr(cv2, "USAC_MAGSAC"):
        assert method == cv2.USAC_MAGSAC
        assert used == "magsac"
        assert fallback is False
    else:
        assert method == cv2.RANSAC
        assert used == "ransac"
        assert fallback is True


def test_magsac_falls_back_when_constant_absent(monkeypatch):
    monkeypatch.delattr(homography.cv2, "USAC_MAGSAC", raising=False)
    method, used, fallback = homography.resolve_estimator("magsac")
    assert method == cv2.RANSAC
    assert used == "ransac"
    assert fallback is True
