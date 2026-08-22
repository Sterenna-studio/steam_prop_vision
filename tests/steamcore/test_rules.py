"""
tests/steamcore/test_rules.py
Tests unitaires pour RuleEngine et validate_rules_schema.
"""

import pytest
import threading
import time
from pathlib import Path

from steamcore.rules import (
    RuleEngine,
    RulesSchemaError,
    validate_rules_schema,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_YAML_CONTENT = """
default:
  enabled: false
  cooldown: 10
  min_duration: 0
  actions: []
rules:
  plate_test:
    enabled: true
    cooldown: 5
    min_duration: 0
    actions:
      - type: udp
        message: TEST_MSG
"""


@pytest.fixture
def rules_yaml(tmp_path) -> Path:
    f = tmp_path / "rules.yaml"
    f.write_text(VALID_YAML_CONTENT, encoding="utf-8")
    return f


@pytest.fixture
def engine(rules_yaml) -> RuleEngine:
    return RuleEngine(config_path=str(rules_yaml))


# ---------------------------------------------------------------------------
# Tests validate_rules_schema
# ---------------------------------------------------------------------------


class TestValidateSchema:
    def test_valid_schema_passes(self):
        raw = {
            "default": {
                "enabled": False,
                "cooldown": 10,
                "min_duration": 0,
                "actions": [],
            },
            "rules": {
                "plate_x": {
                    "enabled": True,
                    "cooldown": 5.0,
                    "min_duration": 0,
                    "actions": [{"type": "udp", "message": "X"}],
                }
            },
        }
        validate_rules_schema(raw)  # ne doit pas lever

    def test_invalid_root_type_raises(self):
        with pytest.raises(RulesSchemaError, match="racine"):
            validate_rules_schema("not a dict")

    def test_invalid_action_type_raises(self):
        raw = {"rules": {"plate_x": {"actions": [{"type": "INVALID"}]}}}
        with pytest.raises(RulesSchemaError, match="invalide"):
            validate_rules_schema(raw)

    def test_cooldown_out_of_range_raises(self):
        raw = {"rules": {"plate_x": {"cooldown": 9999}}}
        with pytest.raises(RulesSchemaError, match="cooldown"):
            validate_rules_schema(raw)

    def test_enabled_wrong_type_raises(self):
        raw = {"rules": {"plate_x": {"enabled": "yes"}}}
        with pytest.raises(RulesSchemaError, match="enabled"):
            validate_rules_schema(raw)

    def test_missing_rules_section_ok(self):
        """Section 'rules' absente == dict vide, pas d'erreur."""
        validate_rules_schema({})


# ---------------------------------------------------------------------------
# Tests RuleEngine
# ---------------------------------------------------------------------------


class TestRuleEngine:
    def test_loads_rules(self, engine):
        assert "plate_test" in engine._rules

    def test_unknown_label_returns_default(self, engine):
        rule = engine.get_rule("inexistant")
        assert rule.label == "__default__"

    def test_should_trigger_enabled(self, engine):
        """Un label actif doit se déclencher au premier appel."""
        assert engine.should_trigger("plate_test") is True

    def test_cooldown_prevents_retrigger(self, engine):
        now = time.time()
        engine.mark_triggered("plate_test", now=now)
        assert engine.should_trigger("plate_test", now=now + 1.0) is False

    def test_cooldown_elapsed_allows_trigger(self, engine):
        now = time.time()
        engine.mark_triggered("plate_test", now=now)
        assert engine.should_trigger("plate_test", now=now + 10.0) is True

    def test_get_actions_returns_list(self, engine):
        actions = engine.get_actions("plate_test")
        assert isinstance(actions, list)
        assert actions[0].type == "udp"

    def test_reload_with_invalid_yaml_keeps_previous_rules(self, engine, rules_yaml):
        """reload() avec schéma invalide ne doit pas écraser les règles existantes."""
        original_rules = dict(engine._rules)
        # Écrire du YAML invalide
        rules_yaml.write_text(
            "rules:\n  bad_entry:\n    enabled: 'not_a_bool'\n", encoding="utf-8"
        )
        engine.reload()
        # Les règles doivent être inchangées
        assert engine._rules == original_rules

    def test_reset_runtime_clears_cooldowns_and_pending_detections(self, engine):
        engine.mark_triggered("plate_test", now=100.0)
        engine._first_seen["plate_test"] = 99.0

        engine.reset_runtime()

        assert engine._last_trigger == {}
        assert engine._first_seen == {}


class TestTryTrigger:
    """try_trigger() : version atomique (verrouillée) de should_trigger()+
    mark_triggered(), utilisée par apps/rpi/actions.py pour le trigger
    manuel Loxone (seul chemin où plusieurs threads peuvent appeler la même
    carte en même temps)."""

    def test_first_call_triggers_and_marks(self, engine):
        assert engine.try_trigger("plate_test") is True
        assert "plate_test" in engine._last_trigger

    def test_second_call_within_cooldown_blocked(self, engine):
        now = time.time()
        assert engine.try_trigger("plate_test", now=now) is True
        assert engine.try_trigger("plate_test", now=now + 1.0) is False

    def test_call_after_cooldown_elapsed_allowed(self, engine):
        now = time.time()
        assert engine.try_trigger("plate_test", now=now) is True
        assert engine.try_trigger("plate_test", now=now + 10.0) is True

    def test_disabled_label_never_triggers(self, engine):
        assert (
            engine.try_trigger("inexistant") is False
        )  # -> __default__, enabled=False

    def test_concurrent_calls_only_one_wins(self, engine):
        """Simule deux threads (ex: deux STEAM_TRIGGER Loxone rapprochés)
        appelant try_trigger() pour la même carte en même temps : un seul
        doit passer, quel que soit l'ordre d'exécution du GIL."""
        results = []
        results_lock = threading.Lock()
        start = threading.Barrier(2)

        def _attempt():
            start.wait()
            ok = engine.try_trigger("plate_test")
            with results_lock:
                results.append(ok)

        threads = [threading.Thread(target=_attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [False, True]
