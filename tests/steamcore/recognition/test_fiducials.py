from __future__ import annotations

import cv2
import pytest

from steamcore.recognition.fiducials import (
    FiducialUnavailableError,
    create_aruco_backend,
    fiducials_available,
)


def test_aruco_generation_and_synthetic_detection(tmp_path):
    if not fiducials_available():
        with pytest.raises(FiducialUnavailableError):
            create_aruco_backend()
        pytest.skip("cv2.aruco absent de cette build OpenCV")
    backend = create_aruco_backend("DICT_4X4_50", {7: "door"})
    marker = backend.generate(7, 300)
    canvas = cv2.copyMakeBorder(marker, 50, 50, 50, 50, cv2.BORDER_CONSTANT, value=255)
    results = backend.detect(canvas)
    assert results
    assert results[0].id == "door"
    assert results[0].backend == "aruco"
    assert backend.export_png(7, tmp_path / "marker.png").exists()
    svg = backend.export_svg(7, tmp_path / "marker.svg", 80, 8)
    assert "<svg" in svg.read_text(encoding="utf-8")
