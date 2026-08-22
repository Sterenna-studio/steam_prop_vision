"""Tests de l'endpoint de contrôle runtime de l'API admin."""

import asyncio
import base64
import json

import cv2
import numpy as np

from apps.rpi.admin_controls import UnknownAdminCommand
from apps.rpi.plates import PlateStore
from monitor import rule_api


class _Controls:
    def __init__(self):
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return {"status": "ok", "command": command}


def _body(response):
    return json.loads(response.body)


def test_admin_control_delegates_to_attached_runtime(monkeypatch):
    controls = _Controls()
    monkeypatch.setattr(rule_api, "_controls_ref", controls)

    response = rule_api.admin_control("scan")

    assert response.status_code == 200
    assert _body(response) == {"status": "ok", "command": "scan"}
    assert controls.commands == ["scan"]


def test_admin_control_requires_attached_runtime(monkeypatch):
    monkeypatch.setattr(rule_api, "_controls_ref", None)

    response = rule_api.admin_control("stop")

    assert response.status_code == 503
    assert _body(response)["status"] == "error"


def test_admin_control_rejects_unknown_command(monkeypatch):
    class _RejectingControls:
        def execute(self, command):
            raise UnknownAdminCommand(f"commande inconnue: {command}")

    monkeypatch.setattr(rule_api, "_controls_ref", _RejectingControls())

    response = rule_api.admin_control("shutdown")

    assert response.status_code == 400
    assert _body(response)["commands"] == [
        "stop",
        "scan",
        "reset",
        "reload_templates",
    ]


def test_status_exposes_runtime_health():
    response = rule_api.get_status()

    assert response.status_code == 200
    assert "runtime" in _body(response)
    assert "camera_on" in _body(response)["runtime"]


def test_add_plate_image_requests_hot_reload(monkeypatch, tmp_path):
    controls = _Controls()
    store = PlateStore(tmp_path / "PLATEST", tmp_path / ".runtime" / "trash")
    monkeypatch.setattr(rule_api, "_controls_ref", controls)
    monkeypatch.setattr(rule_api, "_plate_store", store)
    image = np.zeros((30, 30, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok

    class _Request:
        async def json(self):
            return {
                "files": [
                    {
                        "name": "face.jpg",
                        "data": base64.b64encode(encoded.tobytes()).decode("ascii"),
                    }
                ]
            }

    response = asyncio.run(rule_api.add_plate_images("plate_test", _Request()))

    assert response.status_code == 200
    assert _body(response)["added"] == ["face.jpg"]
    assert controls.commands == ["reload_templates"]
    assert store.list_active()[0]["plate_id"] == "plate_test"


def test_log_endpoint_rejects_path_traversal():
    response = rule_api.read_log_file("..-secret")

    assert response.status_code == 400
