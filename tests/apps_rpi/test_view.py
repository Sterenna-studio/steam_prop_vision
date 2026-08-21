"""
tests/apps_rpi/test_view.py
Tests unitaires pour la logique pure de apps.rpi.view : mutation de
_view_status par push_event()/set_service_mode(). Le serveur HTTP/MJPEG
lui-même n'est pas testé ici (nécessite un vrai socket) — voir
LOXONE.md/RUNBOOK.md pour la checklist de validation manuelle sur STYX.
"""

from __future__ import annotations

import pytest

from apps.rpi import view


@pytest.fixture(autouse=True)
def _no_real_ws(monkeypatch):
    monkeypatch.setattr(view, "_push_event_raw", lambda event: None)


@pytest.fixture(autouse=True)
def _reset_status():
    """_view_status est un dict de module — état partagé entre tests."""
    yield
    view._view_status.update(
        {
            "fsm": "IDLE",
            "card_id": None,
            "card_label": None,
            "hold_pct": 0,
            "service_mode": "prod",
        }
    )


def test_set_service_mode_updates_status():
    view.set_service_mode("dev")
    assert view._view_status["service_mode"] == "dev"


def test_push_event_state_idle_resets_card_fields():
    view.push_event({"type": "card_detected", "card_id": "plate_x", "label": "X"})
    view.push_event({"type": "state", "state": "IDLE"})
    assert view._view_status["fsm"] == "IDLE"
    assert view._view_status["card_id"] is None
    assert view._view_status["card_label"] is None
    assert view._view_status["hold_pct"] == 0


def test_push_event_state_standby_keeps_card_fields():
    view.push_event({"type": "card_detected", "card_id": "plate_x", "label": "X"})
    view.push_event({"type": "state", "state": "STANDBY"})
    assert view._view_status["fsm"] == "STANDBY"
    assert view._view_status["card_id"] == "plate_x"  # pas réinitialisé


def test_push_event_card_detected_sets_fields():
    view.push_event({"type": "card_detected", "card_id": "plate_y", "label": "Y"})
    assert view._view_status["card_id"] == "plate_y"
    assert view._view_status["card_label"] == "Y"


def test_push_event_hold_sets_pct():
    view.push_event({"type": "hold", "pct": 42})
    assert view._view_status["hold_pct"] == 42


def test_push_event_unknown_type_is_noop():
    before = dict(view._view_status)
    view.push_event({"type": "fps", "value": 12.3})
    assert view._view_status == before
