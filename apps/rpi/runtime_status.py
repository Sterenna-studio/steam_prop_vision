"""État de santé partagé entre la boucle caméra et l'API d'administration."""

from __future__ import annotations

import threading
import time


class RuntimeStatus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = {
            "camera_on": False,
            "pipeline_on": False,
            "pipeline_mode": None,
            "detectors_ready": False,
            "template_ids": [],
            "fps": 0.0,
            "last_frame_at": None,
        }

    def configure(self, pipeline_mode: str) -> None:
        with self._lock:
            self._data["pipeline_mode"] = pipeline_mode

    def set_camera(self, enabled: bool) -> None:
        with self._lock:
            self._data["camera_on"] = enabled

    def set_pipeline(self, enabled: bool) -> None:
        with self._lock:
            self._data["pipeline_on"] = enabled

    def set_detectors(self, ready: bool, template_ids=()) -> None:
        with self._lock:
            self._data["detectors_ready"] = ready
            self._data["template_ids"] = sorted(set(template_ids))

    def touch_frame(self, now: float | None = None) -> None:
        with self._lock:
            self._data["last_frame_at"] = time.time() if now is None else now

    def set_fps(self, fps: float) -> None:
        with self._lock:
            self._data["fps"] = round(float(fps), 1)

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            data = dict(self._data)
            data["template_ids"] = list(self._data["template_ids"])
        last_frame_at = data["last_frame_at"]
        age = None if last_frame_at is None else max(0.0, now - last_frame_at)
        data["last_frame_age_s"] = None if age is None else round(age, 2)
        data["frame_recent"] = age is not None and age <= 3.0
        data["templates_loaded"] = len(data["template_ids"])
        data["healthy"] = bool(
            data["camera_on"]
            and data["pipeline_on"]
            and data["detectors_ready"]
            and data["frame_recent"]
        )
        return data


runtime_status = RuntimeStatus()
