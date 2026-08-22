"""Primitives de calibration Picamera2 importables et testables hors Pi."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Callable, Protocol


class Picamera2Like(Protocol):
    def set_controls(self, controls: dict) -> None: ...

    def capture_metadata(self) -> dict: ...


@dataclass(frozen=True)
class CameraCalibrationControls:
    af_mode_manual: int = 0
    af_mode_auto: int = 1
    af_trigger_start: int = 0
    af_state_focused: int = 2
    af_state_failed: int = 3


@dataclass
class CameraCalibrationResult:
    success: bool
    autofocus_status: str
    stabilized: bool
    locked: bool
    metadata: dict
    controls_applied: dict
    diagnostics: list[str] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class CameraCalibrator:
    """Pilote uniquement l'API publique Picamera2 reçue par injection."""

    METADATA_KEYS = (
        "LensPosition",
        "ExposureTime",
        "AnalogueGain",
        "ColourGains",
        "ColourTemperature",
        "AfState",
        "Lux",
        "SensorTimestamp",
        "FrameDuration",
    )

    def __init__(
        self,
        camera: Picamera2Like,
        controls: CameraCalibrationControls | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.camera = camera
        self.controls = controls or CameraCalibrationControls()
        self._sleep = sleep

    def calibrate(
        self,
        autofocus_timeout_s: float = 5.0,
        stabilization_s: float = 2.0,
        sample_interval_s: float = 0.2,
        lock: bool = False,
    ) -> CameraCalibrationResult:
        started = time.perf_counter()
        autofocus_status = self.run_autofocus(autofocus_timeout_s)
        samples = self.wait_for_stabilization(stabilization_s, sample_interval_s)
        metadata = self.read_metadata()
        stabilized, diagnostics = self._diagnose(samples, metadata)
        controls_applied = self.lock_values(metadata) if lock else {}
        success = autofocus_status != "failed" and bool(metadata)
        return CameraCalibrationResult(
            success=success,
            autofocus_status=autofocus_status,
            stabilized=stabilized,
            locked=bool(controls_applied),
            metadata=metadata,
            controls_applied=controls_applied,
            diagnostics=diagnostics,
            samples=samples,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def run_autofocus(self, timeout_s: float = 5.0) -> str:
        self.camera.set_controls(
            {
                "AfMode": self.controls.af_mode_auto,
                "AfTrigger": self.controls.af_trigger_start,
            }
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = self.camera.capture_metadata().get("AfState")
            if state == self.controls.af_state_focused:
                return "focused"
            if state == self.controls.af_state_failed:
                return "failed"
            self._sleep(min(0.1, max(timeout_s, 0.0)))
        return "timeout"

    def wait_for_stabilization(
        self, duration_s: float = 2.0, interval_s: float = 0.2
    ) -> list[dict]:
        samples = []
        count = max(1, int(duration_s / max(interval_s, 0.001)))
        for index in range(count):
            samples.append(self.read_metadata())
            if index + 1 < count:
                self._sleep(interval_s)
        return samples

    def read_metadata(self) -> dict:
        metadata = self.camera.capture_metadata() or {}
        return {key: metadata[key] for key in self.METADATA_KEYS if key in metadata}

    def lock_values(self, metadata: dict) -> dict:
        controls = {"AeEnable": False, "AwbEnable": False}
        mapping = {
            "LensPosition": "LensPosition",
            "ExposureTime": "ExposureTime",
            "AnalogueGain": "AnalogueGain",
            "ColourGains": "ColourGains",
        }
        for metadata_key, control_key in mapping.items():
            if metadata_key in metadata:
                controls[control_key] = metadata[metadata_key]
        if "LensPosition" in metadata:
            controls["AfMode"] = self.controls.af_mode_manual
        self.camera.set_controls(controls)
        return controls

    def restore_auto(self) -> dict:
        controls = {
            "AeEnable": True,
            "AwbEnable": True,
            "AfMode": self.controls.af_mode_auto,
        }
        self.camera.set_controls(controls)
        return controls

    @staticmethod
    def _diagnose(samples: list[dict], metadata: dict) -> tuple[bool, list[str]]:
        diagnostics = []
        required = ("LensPosition", "ExposureTime", "AnalogueGain")
        missing = [key for key in required if key not in metadata]
        if missing:
            diagnostics.append("Metadata absente: " + ", ".join(missing))
        stabilized = _stable_numeric(samples, "ExposureTime", 0.05) and _stable_numeric(
            samples, "AnalogueGain", 0.05
        )
        if not stabilized:
            diagnostics.append("Exposition/gain non stabilisés dans la fenêtre mesurée")
        return stabilized, diagnostics


def _stable_numeric(samples: list[dict], key: str, tolerance_ratio: float) -> bool:
    values = [float(sample[key]) for sample in samples if key in sample]
    if len(values) < 2:
        return False
    mean = sum(values) / len(values)
    if abs(mean) < 1e-9:
        return max(values) - min(values) < 1e-9
    return (max(values) - min(values)) / abs(mean) <= tolerance_ratio
