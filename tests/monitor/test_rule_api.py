"""Tests de l'endpoint de contrôle runtime de l'API admin."""

import json

from apps.rpi.admin_controls import UnknownAdminCommand
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
    assert _body(response)["commands"] == ["stop", "scan", "reset"]
