"""Tests de la gestion locale et réversible des templates de plaques."""

import cv2
import numpy as np
import pytest

from apps.rpi.plates import PlateConflictError, PlateError, PlateStore


@pytest.fixture
def store(tmp_path):
    return PlateStore(tmp_path / "PLATEST", tmp_path / ".runtime" / "plate_trash")


def _image_bytes(extension=".jpg"):
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    image[5:35, 5:35] = (255, 255, 255)
    ok, encoded = cv2.imencode(extension, image)
    assert ok
    return encoded.tobytes()


def test_add_images_creates_plate_and_lists_it(store):
    result = store.add_images(
        "plate_test",
        [("face.jpg", _image_bytes()), ("angle.png", _image_bytes(".png"))],
    )

    assert result["added"] == ["face.jpg", "angle.png"]
    assert store.list_active() == [
        {
            "plate_id": "plate_test",
            "images": ["angle.png", "face.jpg"],
            "image_count": 2,
            "protected": False,
        }
    ]


def test_invalid_image_does_not_create_empty_plate(store):
    with pytest.raises(PlateError, match="illisible"):
        store.add_images("plate_bad", [("bad.jpg", b"not an image")])

    assert store.list_active() == []


def test_existing_file_is_never_overwritten(store):
    store.add_images("plate_test", [("face.jpg", _image_bytes())])

    with pytest.raises(PlateConflictError, match="déjà présent"):
        store.add_images("plate_test", [("face.jpg", _image_bytes())])


def test_archive_and_restore_are_reversible(store):
    store.add_images("plate_test", [("face.jpg", _image_bytes())])

    archived = store.archive("plate_test")
    assert store.list_active() == []
    assert store.list_archived()[0]["plate_id"] == "plate_test"

    store.restore(archived["archive_id"])
    assert store.list_active()[0]["plate_id"] == "plate_test"
    assert store.list_archived() == []


def test_ready_check_cannot_be_archived(store):
    store.add_images("plate_ready_check", [("face.jpg", _image_bytes())])

    with pytest.raises(PlateError, match="protégée"):
        store.archive("plate_ready_check")


@pytest.mark.parametrize("plate_id", ["test", "plate_../x", "plate-é", "plate_"])
def test_rejects_unsafe_plate_ids(store, plate_id):
    with pytest.raises(PlateError):
        store.add_images(plate_id, [("face.jpg", _image_bytes())])


def test_plate_id_is_normalized_to_lowercase(store):
    result = store.add_images("PLATE_TEST", [("face.jpg", _image_bytes())])

    assert result["plate_id"] == "plate_test"
