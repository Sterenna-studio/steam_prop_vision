"""
steamcore/rules.py
Moteur de règles S.T.E.A.M.

Charge config/rules.yaml et décide si un label détecté doit déclencher
des actions, en tenant compte de :
  - enabled          : label actif ?
  - cooldown         : délai minimum entre deux déclenchements
  - min_duration     : durée de détection continue requise (ex: 2s pour person)
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
    _YAML = True
except ImportError:
    import json
    _YAML = False
    print("[rules] WARN: pyyaml manquant, fallback JSON -> pip install pyyaml")


# ── Constantes de validation ───────────────────────────────────────────────
_VALID_ACTION_TYPES = {"audio", "video", "image", "udp", "http"}
_COOLDOWN_MIN, _COOLDOWN_MAX = 0.0, 3600.0
_MIN_DURATION_MIN, _MIN_DURATION_MAX = 0.0, 60.0


class RulesSchemaError(ValueError):
    """Levée quand rules.yaml ne respecte pas le schéma attendu."""


def validate_rules_schema(raw: dict) -> None:
    """
    Valide la structure de rules.yaml.
    Lève RulesSchemaError avec un message explicite si quelque chose cloche.
    """
    if not isinstance(raw, dict):
        raise RulesSchemaError("rules.yaml : la racine doit être un mapping YAML")

    # Section default optionnelle
    if "default" in raw:
        _validate_rule_entry("__default__", raw["default"])

    # Section rules obligatoire (peut être vide)
    rules_section = raw.get("rules", {})
    if not isinstance(rules_section, dict):
        raise RulesSchemaError("rules.yaml : 'rules' doit être un mapping")

    for label, cfg in rules_section.items():
        _validate_rule_entry(label, cfg)


def _validate_rule_entry(label: str, cfg: Any) -> None:
    if not isinstance(cfg, dict):
        raise RulesSchemaError(f"[{label}] doit être un mapping, reçu : {type(cfg).__name__}")

    # enabled
    enabled = cfg.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RulesSchemaError(f"[{label}].enabled doit être un booléen (true/false)")

    # cooldown
    cooldown = cfg.get("cooldown", 5.0)
    try:
        cooldown = float(cooldown)
    except (TypeError, ValueError):
        raise RulesSchemaError(f"[{label}].cooldown doit être un nombre")
    if not (_COOLDOWN_MIN <= cooldown <= _COOLDOWN_MAX):
        raise RulesSchemaError(
            f"[{label}].cooldown={cooldown} hors plage [{_COOLDOWN_MIN}, {_COOLDOWN_MAX}]s"
        )

    # min_duration
    min_dur = cfg.get("min_duration", 0.0)
    try:
        min_dur = float(min_dur)
    except (TypeError, ValueError):
        raise RulesSchemaError(f"[{label}].min_duration doit être un nombre")
    if not (_MIN_DURATION_MIN <= min_dur <= _MIN_DURATION_MAX):
        raise RulesSchemaError(
            f"[{label}].min_duration={min_dur} hors plage [{_MIN_DURATION_MIN}, {_MIN_DURATION_MAX}]s"
        )

    # actions
    actions = cfg.get("actions", [])
    if not isinstance(actions, list):
        raise RulesSchemaError(f"[{label}].actions doit être une liste")
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            raise RulesSchemaError(f"[{label}].actions[{i}] doit être un mapping")
        atype = action.get("type", "")
        if atype not in _VALID_ACTION_TYPES:
            raise RulesSchemaError(
                f"[{label}].actions[{i}].type='{atype}' invalide. "
                f"Valeurs acceptées : {sorted(_VALID_ACTION_TYPES)}"
            )


@dataclass
class ActionDef:
    type: str                     # audio | video | image | udp | http
    subdir: str = ""
    message: str = ""
    url: str = ""

    @staticmethod
    def from_dict(d: dict) -> "ActionDef":
        return ActionDef(
            type    = d.get("type", ""),
            subdir  = d.get("subdir", ""),
            message = d.get("message", ""),
            url     = d.get("url", ""),
        )


@dataclass
class LabelRule:
    label: str
    enabled: bool = True
    cooldown: float = 5.0
    min_duration: float = 0.0
    actions: list[ActionDef] = field(default_factory=list)


class RuleEngine:
    def __init__(self, config_path: str = "config/rules.yaml"):
        self.config_path = Path(config_path)
        self._rules: dict[str, LabelRule] = {}
        self._default: LabelRule = LabelRule(label="__default__", enabled=False)

        # État runtime
        self._last_trigger: dict[str, float] = {}
        self._first_seen:   dict[str, float] = {}   # pour min_duration

        self.reload()

    # ── Chargement config ─────────────────────────────────────────
    def reload(self) -> None:
        if not self.config_path.exists():
            print(f"[rules] Config introuvable : {self.config_path} — règles vides")
            return
        raw = self._load_file()

        # Validation schéma avant parsing
        try:
            validate_rules_schema(raw)
        except RulesSchemaError as exc:
            print(f"[rules] ERREUR schéma — rechargement annulé : {exc}")
            return

        rules_raw = raw.get("rules", {})
        default_raw = raw.get("default", {})

        self._default = self._parse_rule("__default__", default_raw)
        self._rules = {
            label: self._parse_rule(label, cfg)
            for label, cfg in rules_raw.items()
        }
        print(f"[rules] {len(self._rules)} règles chargées depuis {self.config_path}")

    def _load_file(self) -> dict:
        with open(self.config_path, encoding="utf-8") as fh:
            if _YAML:
                return yaml.safe_load(fh) or {}
            return {}  # fallback minimal

    @staticmethod
    def _parse_rule(label: str, cfg: dict) -> LabelRule:
        return LabelRule(
            label        = label,
            enabled      = cfg.get("enabled", True),
            cooldown     = float(cfg.get("cooldown", 5.0)),
            min_duration = float(cfg.get("min_duration", 0.0)),
            actions      = [ActionDef.from_dict(a) for a in cfg.get("actions", [])],
        )

    # ── API principale ────────────────────────────────────────────
    def get_rule(self, label: str) -> LabelRule:
        return self._rules.get(label.lower(), self._default)

    def should_trigger(self, label: str, now: float | None = None) -> bool:
        """
        Retourne True si le label doit déclencher des actions.
        Gère enabled, cooldown et min_duration.
        """
        label = label.lower()
        now = time.time() if now is None else now
        rule = self.get_rule(label)

        if not rule.enabled:
            return False

        # Cooldown
        if now - self._last_trigger.get(label, 0.0) < rule.cooldown:
            return False

        # min_duration : enregistre le premier instant de détection
        if rule.min_duration > 0:
            if label not in self._first_seen:
                self._first_seen[label] = now
                return False
            elapsed = now - self._first_seen[label]
            if elapsed < rule.min_duration:
                return False

        return True

    def mark_triggered(self, label: str, now: float | None = None) -> None:
        """Appelé après que les actions ont été exécutées."""
        label = label.lower()
        now = time.time() if now is None else now
        self._last_trigger[label] = now
        self._first_seen.pop(label, None)

    def reset_seen(self, label: str) -> None:
        """Appelé quand le label disparaît de la frame (détection perdue)."""
        self._first_seen.pop(label.lower(), None)

    def get_actions(self, label: str) -> list[ActionDef]:
        return self.get_rule(label.lower()).actions

    # ── Infos debug ───────────────────────────────────────────────
    def summary(self) -> str:
        active = [l for l, r in self._rules.items() if r.enabled]
        return f"rules: {len(active)} actives / {len(self._rules)} totales"
