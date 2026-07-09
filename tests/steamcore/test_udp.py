"""
tests/steamcore/test_udp.py
Tests unitaires pour HeartbeatThread et UDPListener.
- Port configurable via features.yaml (udp_listen_port)
- Pas de dépendance réseau réelle (socket loopback uniquement)
"""
from __future__ import annotations
import socket
import threading
import time
import pytest

from steamcore.udp import HeartbeatThread, UDPListener, LISTEN_PORT


# ---------------------------------------------------------------------------
# Tests HeartbeatThread
# ---------------------------------------------------------------------------

class TestHeartbeatThread:
    def test_starts_and_stops_cleanly(self):
        hb = HeartbeatThread(interval=60.0)  # intervalle long pour ne pas broadcaster
        hb.start()
        hb.stop()
        hb.join(timeout=2.0)
        assert not hb.is_alive()

    def test_is_daemon(self):
        hb = HeartbeatThread(interval=60.0)
        assert hb.daemon is True


# ---------------------------------------------------------------------------
# Tests UDPListener — port configurable
# ---------------------------------------------------------------------------

class TestUDPListenerPort:
    def test_default_listen_port_constant(self):
        """La constante LISTEN_PORT correspond au port par défaut du fichier features.yaml."""
        assert LISTEN_PORT == 8888

    def test_custom_port_via_constructor(self):
        """UDPListener accepte un port personnalisé."""
        listener = UDPListener(port=19876)
        assert listener.port == 19876

    def test_receives_message_loopback(self):
        """UDPListener reçoit un message envoyé en loopback sur un port libre."""
        received = []
        event = threading.Event()

        def on_msg(msg, addr):
            received.append(msg)
            event.set()

        # Trouver un port libre
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tmp:
            tmp.bind(("127.0.0.1", 0))
            free_port = tmp.getsockname()[1]

        listener = UDPListener(port=free_port, on_message=on_msg)
        listener.start()
        time.sleep(0.1)  # laisser le thread démarrer

        # Envoyer un message en loopback
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"STEAM_TEST_MSG", ("127.0.0.1", free_port))

        event.wait(timeout=2.0)
        listener.stop()
        listener.join(timeout=2.0)

        assert "STEAM_TEST_MSG" in received

    def test_is_daemon(self):
        listener = UDPListener(port=19877)
        assert listener.daemon is True
