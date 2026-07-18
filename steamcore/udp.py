"""
steamcore/udp.py
- send_event()          : envoie un message UDP à Loxone (fire-and-forget)
- send_event_reliable() : idem + attend un ACK:<msg> en retour, retente sinon
- broadcast()           : envoie STEAM_RUN_OK en broadcast LAN
- UDPListener           : écoute les ACK/commandes entrants

Voir LOXONE.md pour le catalogue complet des messages et ce que Loxone doit
implémenter côté Miniserver pour participer aux ACK.
"""

from __future__ import annotations
import socket
import threading


BROADCAST_PORT = 9999
LOXONE_PORT = 7777
LISTEN_PORT = 8888
ACK_PREFIX = "ACK:"


def send_event(msg: str, ip: str, port: int = LOXONE_PORT) -> None:
    """Envoie un message UDP texte à l'IP:port cible (ex: Loxone)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg.encode(), (ip, port))
    print(f"[udp] → {ip}:{port}  {msg}")


# ── ACK (Loxone -> STYX, réponse à send_event_reliable) ────────────────────
_ack_waiters: dict[str, threading.Event] = {}
_ack_lock = threading.Lock()


def _notify_ack(msg: str) -> None:
    """Appelé par UDPListener à la réception de 'ACK:<msg>'."""
    with _ack_lock:
        ev = _ack_waiters.pop(msg, None)
    if ev:
        ev.set()


def send_event_reliable(
    msg: str,
    ip: str,
    port: int = LOXONE_PORT,
    retries: int = 2,
    timeout: float = 1.0,
) -> bool:
    """Envoie msg et attend 'ACK:<msg>' en retour (via UDPListener).

    Retente jusqu'à `retries` fois si pas d'ACK dans `timeout`s. Bloquant —
    à lancer dans un thread depuis un appelant temps réel. Le message part
    systématiquement à chaque tentative (fire-and-forget préservé) : si
    Loxone ne participe pas à l'ACK, le comportement reste au moins aussi
    bon qu'un send_event() simple, jamais pire.
    """
    for attempt in range(retries + 1):
        ev = threading.Event()
        with _ack_lock:
            _ack_waiters[msg] = ev
        send_event(msg, ip, port)
        if ev.wait(timeout):
            return True
        with _ack_lock:
            _ack_waiters.pop(msg, None)
        if attempt < retries:
            print(f"[udp] Pas d'ACK pour {msg!r} — nouvelle tentative")
    print(f"[udp] ERREUR : aucun ACK pour {msg!r} après {retries + 1} envoi(s)")
    return False


def broadcast(msg: str = "STEAM_RUN_OK", port: int = BROADCAST_PORT) -> None:
    """Broadcast UDP sur le LAN."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(msg.encode(), ("<broadcast>", port))


class HeartbeatThread(threading.Thread):
    """Envoie STEAM_RUN_OK en broadcast toutes les `interval` secondes."""

    def __init__(self, interval: float = 5.0):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        print(f"[udp] Heartbeat broadcast STEAM_RUN_OK toutes les {self.interval}s")
        while not self._stop_event.wait(self.interval):
            broadcast("STEAM_RUN_OK")

    def stop(self):
        self._stop_event.set()


class UDPListener(threading.Thread):
    """
    Écoute les messages UDP entrants (ACK Loxone, commandes réseau).
    Appelle on_message(msg: str, addr: tuple) à chaque réception.
    """

    def __init__(self, port: int = LISTEN_PORT, on_message=None):
        super().__init__(daemon=True)
        self.port = port
        self.on_message = on_message or (
            lambda msg, addr: print(f"[udp] ← {addr} : {msg}")
        )
        self._stop_event = threading.Event()

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(1.0)
            s.bind(("0.0.0.0", self.port))
            print(f"[udp] Écoute sur port {self.port}")
            while not self._stop_event.is_set():
                try:
                    data, addr = s.recvfrom(1024)
                    msg = data.decode().strip()
                    if msg.startswith(ACK_PREFIX):
                        _notify_ack(msg[len(ACK_PREFIX) :])
                    else:
                        self.on_message(msg, addr)
                except socket.timeout:
                    continue

    def stop(self):
        self._stop_event.set()
