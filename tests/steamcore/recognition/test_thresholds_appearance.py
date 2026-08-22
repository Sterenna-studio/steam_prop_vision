from __future__ import annotations

import cv2
import numpy as np

from steamcore.recognition.appearance import GlobalAppearanceRecognizer
from steamcore.recognition.thresholds import RecognitionThresholds


def test_default_threshold_from_legacy_config():
    thresholds = RecognitionThresholds.from_config({"card_score_threshold": 0.31})
    assert thresholds.resolve("plate_x") == 0.31


def test_per_object_threshold_and_fallback():
    thresholds = RecognitionThresholds.from_config(
        {
            "recognition": {
                "default_threshold": 0.20,
                "use_per_object_thresholds": True,
            },
            "objects": {"plate_x": {"threshold": 0.27}},
        }
    )
    assert thresholds.resolve("plate_x") == 0.27
    assert thresholds.resolve("plate_y") == 0.20
    thresholds.reset_object_threshold("plate_x")
    assert thresholds.resolve("plate_x") == 0.20


def test_per_object_thresholds_can_be_disabled():
    thresholds = RecognitionThresholds(
        default_threshold=0.2,
        use_per_object_thresholds=False,
        object_thresholds={"plate_x": 0.9},
    )
    assert thresholds.resolve("plate_x") == 0.2


def test_global_appearance_recognizer(tmp_path):
    directory = tmp_path / "PLATEST" / "plate_x"
    directory.mkdir(parents=True)
    image = np.zeros((256, 256), dtype=np.uint8)
    cv2.circle(image, (128, 128), 70, 255, 8)
    cv2.line(image, (40, 40), (210, 190), 180, 5)
    cv2.imwrite(str(directory / "source.png"), image)
    recognizer = GlobalAppearanceRecognizer(str(tmp_path / "PLATEST"), threshold=0.8)
    result = recognizer.recognize(image, ["plate_x"])
    assert result is not None
    assert result.card_id == "plate_x"
    assert result.score > 0.99
    assert result.intensity_score > 0.99
    assert result.gradient_score > 0.99
