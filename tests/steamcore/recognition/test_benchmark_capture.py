from io import BytesIO

import cv2
import numpy as np
import pytest

from steamcore.recognition.benchmark.capture import (
    CaptureOptions,
    iter_mjpeg_jpegs,
)


def _jpeg(value: int) -> bytes:
    image = np.full((12, 16, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_iter_mjpeg_jpegs_handles_boundaries_across_chunks():
    first = _jpeg(25)
    second = _jpeg(200)
    payload = (
        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        + first
        + b"\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        + second
        + b"\r\n"
    )

    assert list(iter_mjpeg_jpegs(BytesIO(payload), chunk_size=7)) == [first, second]


@pytest.mark.parametrize("condition", ["../frontal", "angle forte", ""])
def test_capture_options_reject_unsafe_condition(condition, tmp_path):
    from steamcore.recognition.benchmark.capture import _validate_options

    with pytest.raises(ValueError):
        _validate_options(
            CaptureOptions(
                corpus=tmp_path,
                object_id="plate_cellule",
                condition=condition,
            )
        )


def test_capture_options_reject_unknown_source_orientation(tmp_path):
    from steamcore.recognition.benchmark.capture import _validate_options

    with pytest.raises(ValueError, match="Orientation source invalide"):
        _validate_options(
            CaptureOptions(
                corpus=tmp_path,
                object_id="plate_cellule",
                condition="frontal",
                source_orientation="unknown",
            )
        )
