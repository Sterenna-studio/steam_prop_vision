"""Commandes runtime exposées par la page d'administration.

Ce module reste indépendant de la caméra afin d'être testable hors Raspberry Pi.
La boucle caméra observe ``force_scan`` et applique elle-même le retour à IDLE.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


VALID_ADMIN_COMMANDS = ("stop", "scan", "reset")


class UnknownAdminCommand(ValueError):
    """Commande absente du protocole de contrôle admin."""


class AdminControls:
    """Pilote les médias et demande un retour au scan à la boucle principale."""

    def __init__(
        self,
        *,
        audio,
        video,
        image,
        force_scan,
        rule_engine,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._players = (audio, video, image)
        self._force_scan = force_scan
        self._rule_engine = rule_engine
        self._event_sink = event_sink

    def execute(self, command: str) -> dict[str, str]:
        """Exécute une commande admin et retourne un résultat sérialisable."""
        command = command.strip().lower()
        if command not in VALID_ADMIN_COMMANDS:
            raise UnknownAdminCommand(f"commande inconnue: {command}")

        self._stop_current_work()

        if command == "reset":
            self._rule_engine.reset_runtime()

        if command in ("scan", "reset"):
            self._force_scan.set()

        if self._event_sink:
            self._event_sink({"type": "admin_control", "command": command})

        return {"status": "ok", "command": command}

    def _stop_current_work(self) -> None:
        for player in self._players:
            if player is not None:
                player.stop()
