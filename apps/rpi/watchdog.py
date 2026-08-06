"""
apps/rpi/watchdog.py
Watchdog anti-freeze.

systemd (Restart=on-failure) ne relance que si le PROCESS meurt. Si la boucle
principale se fige (ex: appel caméra/IPC bloqué) sans faire mourir le process,
rien ne le détecte. Watchdog.start() force un os._exit(1) si touch() n'a pas
été appelé depuis timeout_s — systemd relance alors normalement.
"""

from __future__ import annotations
import logging
import os
import threading
import time

log = logging.getLogger("steam")


class Watchdog:
    def __init__(self, timeout_s: float):
        self.timeout_s = timeout_s
        self._last_alive = time.time()
        self._lock = threading.Lock()

    def touch(self) -> None:
        with self._lock:
            self._last_alive = time.time()

    def is_stale(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            elapsed = now - self._last_alive
        return elapsed > self.timeout_s

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="watchdog").start()

    def _loop(self) -> None:
        while True:
            time.sleep(5.0)
            if self.is_stale():
                with self._lock:
                    stale = time.time() - self._last_alive
                log.error(
                    f"[watchdog] Boucle principale figée depuis {stale:.0f}s "
                    "-> arrêt forcé (systemd relancera)"
                )
                os._exit(1)
