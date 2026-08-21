"""
apps/rpi/actions.py
Dispatch des actions déclenchées par une carte reconnue ou une commande
Loxone, et gestion des commandes entrantes (voir LOXONE.md).

Câblage RuleEngine.try_trigger() : protège spécifiquement le trigger manuel
Loxone (STEAM_TRIGGER:<id>), seul chemin qui contourne le FSM caméra
(IDLE/STANDBY) et peut donc arriver en rafale (plusieurs threads
"loxone-trigger" concurrents, voir handle_loxone_command). try_trigger() est
atomique (verrou dans RuleEngine) pour fermer la fenêtre entre vérification
et marquage — sans ça, deux STEAM_TRIGGER pour la même carte à quelques ms
d'écart pourraient tous les deux passer la vérification avant qu'aucun
n'ait marqué le déclenchement, et rejouer l'action deux fois.

run_actions() lui-même reste inconditionnel (pas de cooldown) : c'est le
chemin appelé par la boucle caméra (run_card_mode/run_person_mode), où le
FSM (IDLE/STANDBY) empêche déjà tout re-déclenchement rapproché. Y ajouter
aussi le cooldown désynchroniserait l'état affiché de ce qui se passe
réellement : main.py pousse STANDBY et attend idle_after_s inconditionnellement
après un hold confirmé, donc si run_actions() n'avait rien fait (cooldown
actif), le système resterait plusieurs secondes en STANDBY sans rien jouer,
sans aucun retour visuel — un vrai "trou" côté GM. Le cooldown de rules.yaml
ne protège donc que le chemin qui n'a pas déjà cette protection : Loxone.

min_duration reste sans effet avec le point d'appel actuel de
RuleEngine.should_trigger() (appelé une seule fois par try_trigger(), au
moment où la commande Loxone arrive) — RuleEngine.reload() avertit si une
règle enabled en a un (voir steamcore/rules.py).
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


def run_actions(cfg, rule_engine, label_or_result, audio, video, image):
    """
    Dispatche les actions d'une règle (carte ou person). Inconditionnel —
    voir docstring du module pour pourquoi le cooldown n'est pas ici.
    label_or_result : RecognitionResult (mode card) ou str (mode person).
    image : instance ImagePlayer partagée (construite une fois dans main(),
    pas à chaque trigger — son constructeur scanne le PATH pour détecter
    mpv/feh/eog).
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
            threading.Thread(
                target=image.show_random, args=(action.subdir,), daemon=True
            ).start()
            push_event({"type": "image", "card": cid, "subdir": action.subdir})

        elif action.type == "udp":
            msg = action.message or ("STEAM_DETECT_" + cid.upper())
            udp_send(msg, lox_ip, lox_port)


def handle_loxone_command(
    msg, addr, cfg, rule_engine, audio, video, image, force_reset
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
        # Le cooldown ne protège que ce qui a un effet à rejouer. Une carte
        # sans règle (ou avec une liste actions vide) tombe dans le fallback
        # STEAM_DETECT_<id> de run_actions(), inconditionnel — rien à
        # protéger, donc pas de passage par try_trigger() pour ce cas.
        if rule_engine.get_actions(card_id) and not rule_engine.try_trigger(card_id):
            log.info(f"[rules] {card_id} ignoré (désactivé ou cooldown actif)")
            return
        threading.Thread(
            target=run_actions,
            args=(cfg, rule_engine, card_id, audio, video, image),
            daemon=True,
            name="loxone-trigger",
        ).start()
