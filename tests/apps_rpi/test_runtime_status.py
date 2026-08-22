"""Tests de l'état de santé exposé au monitor."""

from apps.rpi.runtime_status import RuntimeStatus


def test_healthy_requires_camera_pipeline_detectors_and_recent_frame():
    status = RuntimeStatus()
    status.configure("card")
    status.set_camera(True)
    status.set_pipeline(True)
    status.set_detectors(True, ["plate_b", "plate_a", "plate_a"])
    status.touch_frame(now=100.0)
    status.set_fps(40.84)

    snapshot = status.snapshot(now=101.0)

    assert snapshot["healthy"] is True
    assert snapshot["frame_recent"] is True
    assert snapshot["template_ids"] == ["plate_a", "plate_b"]
    assert snapshot["templates_loaded"] == 2
    assert snapshot["fps"] == 40.8


def test_old_frame_marks_runtime_unhealthy():
    status = RuntimeStatus()
    status.set_camera(True)
    status.set_pipeline(True)
    status.set_detectors(True, ["plate_test"])
    status.touch_frame(now=100.0)

    snapshot = status.snapshot(now=104.1)

    assert snapshot["frame_recent"] is False
    assert snapshot["healthy"] is False
    assert snapshot["last_frame_age_s"] == 4.1
