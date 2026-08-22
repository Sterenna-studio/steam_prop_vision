"""Tests des commandes runtime de la page admin."""

import threading

import pytest

from apps.rpi.admin_controls import AdminControls


class _Player:
    def __init__(self):
        self.stop_count = 0

    def stop(self):
        self.stop_count += 1


class _RuleEngine:
    def __init__(self):
        self.reset_count = 0

    def reset_runtime(self):
        self.reset_count += 1


@pytest.fixture
def controls():
    players = [_Player(), _Player(), _Player()]
    force_scan = threading.Event()
    template_reload = threading.Event()
    engine = _RuleEngine()
    events = []
    instance = AdminControls(
        audio=players[0],
        video=players[1],
        image=players[2],
        force_scan=force_scan,
        template_reload=template_reload,
        rule_engine=engine,
        event_sink=events.append,
    )
    return instance, players, force_scan, template_reload, engine, events


def test_stop_only_stops_current_media(controls):
    instance, players, force_scan, template_reload, engine, events = controls

    assert instance.execute("stop") == {"status": "ok", "command": "stop"}

    assert [player.stop_count for player in players] == [1, 1, 1]
    assert not force_scan.is_set()
    assert not template_reload.is_set()
    assert engine.reset_count == 0
    assert events == [{"type": "admin_control", "command": "stop"}]


def test_scan_stops_media_and_requests_idle_scan(controls):
    instance, players, force_scan, template_reload, engine, _ = controls

    instance.execute("scan")

    assert [player.stop_count for player in players] == [1, 1, 1]
    assert force_scan.is_set()
    assert not template_reload.is_set()
    assert engine.reset_count == 0


def test_reset_also_clears_rule_runtime(controls):
    instance, players, force_scan, template_reload, engine, _ = controls

    instance.execute("reset")

    assert [player.stop_count for player in players] == [1, 1, 1]
    assert force_scan.is_set()
    assert not template_reload.is_set()
    assert engine.reset_count == 1


def test_unknown_command_has_no_side_effect(controls):
    instance, players, force_scan, template_reload, engine, events = controls

    with pytest.raises(ValueError, match="commande inconnue"):
        instance.execute("shutdown")

    assert [player.stop_count for player in players] == [0, 0, 0]
    assert not force_scan.is_set()
    assert not template_reload.is_set()
    assert engine.reset_count == 0
    assert events == []


def test_reload_templates_stops_media_and_sets_both_events(controls):
    instance, players, force_scan, template_reload, engine, events = controls

    instance.execute("reload_templates")

    assert [player.stop_count for player in players] == [1, 1, 1]
    assert force_scan.is_set()
    assert template_reload.is_set()
    assert engine.reset_count == 0
    assert events[-1] == {"type": "admin_control", "command": "reload_templates"}
