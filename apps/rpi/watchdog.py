"""
apps/rpi/watchdog.py
Watchdog anti-freeze.

systemd (Restart=on-failure) ne relance que si le PROCESS meurt. Si la boucle
principale se fige (ex: appel caméra/IPC bloqué) sans faire mourir le process,
rien ne le détecte. Watchdog force un os._exit(1) si touch() n'a pas été
appelé depuis timeout_s — systemd relance alors normalement.

Suit le même idiome que HeartbeatThread/UDPListener (steamcore/udp.py) :
Thread daemon + Event pour l'intervalle/l'arrêt, plutôt qu'un thread anonyme
+ time.sleep().
"""

from __future__ import annotations
import logging
import os
import threading
import time

log = logging.getLogger("steam")


class Watchdog(threading.Thread):
    def __init__(self, timeout_s: float):
        super().__init__(daemon=True, name="watchdog")
        self.timeout_s = timeout_s
        self._last_alive = time.time()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def touch(self) -> None:
        with self._lock:
            self._last_alive = time.time()

    def is_stale(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            elapsed = now - self._last_alive
        return elapsed > self.timeout_s

    def run(self) -> None:
        while not self._stop_event.wait(5.0):
            # Un seul acquire pour la décision ET la valeur loguée — éviter
            # que touch() s'intercale entre les deux (voir is_stale() plus
            # haut) et rende le message d'erreur trompeur.
            with self._lock:
                stale = time.time() - self._last_alive
            if stale > self.timeout_s:
                log.error(
                    f"[watchdog] Boucle principale figée depuis {stale:.0f}s "
                    "-> arrêt forcé (systemd relancera)"
                )
                os._exit(1)

    def stop(self) -> None:
        self._stop_event.set()
