"""
apps/rpi/actions.py
Dispatch des actions déclenchées par une carte reconnue ou une commande
Loxone, et gestion des commandes entrantes (voir LOXONE.md).
"""

from __future__ import annotations
import logging
import threading

from steamcore.udp import send_event as udp_send_raw, send_event_reliable
from apps.rpi.view import push_event

log = logging.getLogger("steam")


def udp_send(msg, ip, port):
    """Envoie UDP (ACK+retry en tâche de fond, non-bloquant) + event WS."""
    push_event({"type": "udp_sent", "msg": msg, "ip": ip, "port": port})

    def _send():
        try:
            ok = send_event_reliable(msg, ip, port)
        except Exception as e:
            log.error("[udp] ERREUR : " + str(e))
            ok = False
        if not ok:
            push_event({"type": "udp_ack_failed", "msg": msg, "ip": ip, "port": port})

    threading.Thread(target=_send, daemon=True, name="udp-send").start()


def run_actions(cfg, rule_engine, label_or_result, audio, video, card_id=None):
    """
    Dispatche les actions d'une règle (carte ou person).
    label_or_result : RecognitionResult (mode card) ou str (mode person).
    """
    cid = getattr(label_or_result, "card_id", label_or_result)
    lox_ip = cfg.get("loxone_ip", "192.168.1.50")
    lox_port = cfg.get("loxone_port", 7777)

    actions = rule_engine.get_actions(cid)
    if not actions:
        msg = "STEAM_DETECT_" + cid.upper()
        udp_send(msg, lox_ip, lox_port)
        return

    for action in actions:
        if action.type == "audio" and cfg.get("enable_audio", True):
            threading.Thread(
                target=audio.play_random, args=(action.subdir,), daemon=True
            ).start()
            push_event({"type": "audio", "card": cid, "subdir": action.subdir})

        elif action.type == "video" and cfg.get("enable_video", True):
            threading.Thread(
                target=video.play_random, args=(action.subdir,), daemon=True
            ).start()
            push_event({"type": "video", "card": cid, "subdir": action.subdir})

        elif action.type == "image" and cfg.get("enable_video", True):
            from steamcore.image_player import ImagePlayer

            threading.Thread(
                target=ImagePlayer("assets/img").show_random,
                args=(action.subdir,),
                daemon=True,
            ).start()
            push_event({"type": "image", "card": cid, "subdir": action.subdir})

        elif action.type == "udp":
            msg = action.message or ("STEAM_DETECT_" + cid.upper())
            udp_send(msg, lox_ip, lox_port)


def handle_loxone_command(
    msg, addr, cfg, rule_engine, audio, video, force_reset
) -> None:
    """Dispatche les commandes reçues de Loxone sur udp_listen_port."""
    log.info("[UDP RX] " + addr[0] + " -> " + msg)
    push_event({"type": "udp_rx", "msg": msg, "from": addr[0]})

    if msg == "STEAM_PING":
        udp_send_raw("STEAM_PONG", addr[0], cfg.get("loxone_port", 7777))
    elif msg == "STEAM_RESET":
        log.info("[loxone] STEAM_RESET reçu -> retour IDLE forcé")
        force_reset.set()
    elif msg.startswith("STEAM_TRIGGER:"):
        card_id = msg[len("STEAM_TRIGGER:") :]
        log.info(f"[loxone] STEAM_TRIGGER reçu -> {card_id}")
        threading.Thread(
            target=run_actions,
            args=(cfg, rule_engine, card_id, audio, video),
            daemon=True,
            name="loxone-trigger",
        ).start()
