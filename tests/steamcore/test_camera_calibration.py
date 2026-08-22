from __future__ import annotations

from steamcore.camera_calibration import CameraCalibrator


class FakeCamera:
    def __init__(self):
        self.controls = []
        self.metadata = {
            "AfState": 2,
            "LensPosition": 4.0,
            "ExposureTime": 10000,
            "AnalogueGain": 1.5,
            "ColourGains": (1.1, 1.2),
        }

    def set_controls(self, controls):
        self.controls.append(controls)

    def capture_metadata(self):
        return dict(self.metadata)


def test_camera_calibration_and_lock_without_picamera_import():
    camera = FakeCamera()
    calibrator = CameraCalibrator(camera, sleep=lambda _seconds: None)
    result = calibrator.calibrate(
        autofocus_timeout_s=0.1,
        stabilization_s=0.3,
        sample_interval_s=0.1,
        lock=True,
    )
    assert result.success is True
    assert result.autofocus_status == "focused"
    assert result.stabilized is True
    assert result.locked is True
    assert result.metadata["LensPosition"] == 4.0
    assert result.controls_applied["AeEnable"] is False
    assert result.to_dict()["duration_ms"] >= 0


def test_restore_auto():
    camera = FakeCamera()
    controls = CameraCalibrator(camera).restore_auto()
    assert controls["AeEnable"] is True
    assert camera.controls[-1] == controls
