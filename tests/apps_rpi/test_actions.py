"""
tests/apps_rpi/test_actions.py
Tests unitaires pour apps.rpi.actions (dispatch d'actions + commandes
Loxone). Aucune dépendance picamera2/matériel.

run_actions() est inconditionnel (pas de cooldown) : c'est le chemin appelé
par la boucle caméra, déjà protégée par le FSM IDLE/STANDBY. Le cooldown
(RuleEngine.try_trigger()) ne s'applique qu'au trigger manuel Loxone
(handle_loxone_command), seul chemin qui contourne ce FSM — voir le
docstring de apps/rpi/actions.py pour le raisonnement complet.
"""

from __future__ import annotations
import threading
import time

import pytest

from apps.rpi import actions
from steamcore.rules import RuleEngine


class _StubPlayer:
    def __init__(self):
        self.calls: list[str] = []

    def play_random(self, subdir: str = ""):
        self.calls.append(subdir)

    def show_random(self, subdir: str = ""):
        self.calls.append(subdir)

    def stop(self):
        pass

    def is_playing(self) -> bool:
        return False


@pytest.fixture
def rule_engine(tmp_path):
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        """
rules:
  plate_test:
    enabled: true
    cooldown: 8
    min_duration: 0
    actions:
      - type: audio
        subdir: test_audio
      - type: udp
        message: STEAM_CARD_TEST
""",
        encoding="utf-8",
    )
    return RuleEngine(str(rules_file))


@pytest.fixture(autouse=True)
def _no_real_io(monkeypatch):
    monkeypatch.setattr(actions, "send_event_reliable", lambda *a, **k: True)
    monkeypatch.setattr(actions, "udp_send_raw", lambda *a, **k: None)
    monkeypatch.setattr(actions, "push_event", lambda event: None)


def _settle(seconds: float = 0.05) -> None:
    time.sleep(seconds)  # laisse les threads daemon (audio/video/udp) tourner


def _players():
    return _StubPlayer(), _StubPlayer(), _StubPlayer()  # audio, video, image


def test_run_actions_dispatches_configured_actions(rule_engine):
    audio, video, image = _players()
    actions.run_actions({}, rule_engine, "plate_test", audio, video, image)
    _settle()
    assert audio.calls == ["test_audio"]


def test_run_actions_accepts_recognition_result_like_object(rule_engine):
    class _Result:
        card_id = "plate_test"

    audio, video, image = _players()
    actions.run_actions({}, rule_engine, _Result(), audio, video, image)
    _settle()
    assert audio.calls == ["test_audio"]


def test_run_actions_is_unconditional_ignores_cooldown(rule_engine):
    """La boucle caméra (déjà protégée par le FSM) n'est pas gatée ici —
    sinon l'état affiché désynchronise de ce qui se joue réellement."""
    audio, video, image = _players()
    actions.run_actions({}, rule_engine, "plate_test", audio, video, image)
    _settle()
    audio.calls.clear()

    actions.run_actions({}, rule_engine, "plate_test", audio, video, image)
    _settle()
    assert audio.calls == ["test_audio"]  # rejoue malgré le cooldown de 8s


def test_run_actions_dispatches_image_action_via_shared_player(tmp_path):
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        """
rules:
  plate_image:
    enabled: true
    actions:
      - type: image
        subdir: test_image
""",
        encoding="utf-8",
    )
    rule_engine = RuleEngine(str(rules_file))
    audio, video, image = _players()

    actions.run_actions({}, rule_engine, "plate_image", audio, video, image)
    _settle()
    assert image.calls == ["test_image"]


def test_run_actions_unconfigured_card_sends_fallback_udp_unconditionally(
    rule_engine, monkeypatch
):
    """Carte sans règle -> ping STEAM_DETECT_<id>."""
    sent = []
    monkeypatch.setattr(
        actions,
        "send_event_reliable",
        lambda msg, ip, port, **k: sent.append(msg) or True,
    )
    audio, video, image = _players()

    actions.run_actions({}, rule_engine, "plate_inconnue", audio, video, image)
    _settle()
    actions.run_actions({}, rule_engine, "plate_inconnue", audio, video, image)
    _settle()

    assert sent == ["STEAM_DETECT_PLATE_INCONNUE", "STEAM_DETECT_PLATE_INCONNUE"]


def test_handle_loxone_command_ping_sends_pong(monkeypatch, rule_engine):
    sent = []
    monkeypatch.setattr(
        actions, "udp_send_raw", lambda msg, ip, port: sent.append((msg, ip, port))
    )
    audio, video, image = _players()

    actions.handle_loxone_command(
        "STEAM_PING",
        ("192.168.1.50", 12345),
        {"loxone_port": 7777},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    assert sent == [("STEAM_PONG", "192.168.1.50", 7777)]


def test_handle_loxone_command_reset_sets_event(rule_engine):
    audio, video, image = _players()
    force_reset = threading.Event()

    actions.handle_loxone_command(
        "STEAM_RESET",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        force_reset,
    )
    assert force_reset.is_set()


def test_handle_loxone_command_trigger_runs_actions(rule_engine):
    audio, video, image = _players()

    actions.handle_loxone_command(
        "STEAM_TRIGGER:plate_test",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    _settle(0.1)
    assert audio.calls == ["test_audio"]


def test_handle_loxone_command_trigger_respects_cooldown(rule_engine):
    """Deuxième STEAM_TRIGGER rapproché pour la même carte -> ignoré."""
    audio, video, image = _players()

    actions.handle_loxone_command(
        "STEAM_TRIGGER:plate_test",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    _settle(0.1)
    audio.calls.clear()

    actions.handle_loxone_command(
        "STEAM_TRIGGER:plate_test",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    _settle(0.1)
    assert audio.calls == []  # cooldown de 8s actif


def test_handle_loxone_command_trigger_unconfigured_card_bypasses_cooldown(
    rule_engine, monkeypatch
):
    """Carte sans règle -> pas de gate try_trigger(), fallback ping direct."""
    sent = []
    monkeypatch.setattr(
        actions,
        "send_event_reliable",
        lambda msg, ip, port, **k: sent.append(msg) or True,
    )
    audio, video, image = _players()

    actions.handle_loxone_command(
        "STEAM_TRIGGER:plate_inconnue",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    _settle(0.1)
    actions.handle_loxone_command(
        "STEAM_TRIGGER:plate_inconnue",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    _settle(0.1)

    assert sent == ["STEAM_DETECT_PLATE_INCONNUE", "STEAM_DETECT_PLATE_INCONNUE"]


def test_handle_loxone_command_trigger_disabled_rule_is_ignored(tmp_path):
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        """
rules:
  plate_off:
    enabled: false
    actions:
      - type: audio
        subdir: should_not_play
""",
        encoding="utf-8",
    )
    rule_engine = RuleEngine(str(rules_file))
    audio, video, image = _players()

    actions.handle_loxone_command(
        "STEAM_TRIGGER:plate_off",
        ("192.168.1.50", 12345),
        {},
        rule_engine,
        audio,
        video,
        image,
        threading.Event(),
    )
    _settle(0.1)
    assert audio.calls == []
