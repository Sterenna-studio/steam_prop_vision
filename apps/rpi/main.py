"""
apps/rpi/main.py  —  S.T.E.A.M Vision STYX
Piloté par config/features.yaml

╔══════════════════════════════════════════════════════╗
║  pipeline_mode: "card"   (défaut — lance une vidéo)  ║
║  ─────────────────────────────────────────────────── ║
║  Scan continu de la carte via L1→L2→L3               ║
║  Même carte maintenue card_hold_ms (2000ms) → TRIGGER ║
║  Lecture vidéo + UDP → retour IDLE après idle_after_s ║
║  Pas de YOLO requis                                  ║
╠══════════════════════════════════════════════════════╣
║  pipeline_mode: "person"  (mode spécial — joue MP3)  ║
║  ─────────────────────────────────────────────────── ║
║  YOLO person détecté X secondes → lecture audio      ║
║  → retour IDLE après idle_after_s                    ║
╚══════════════════════════════════════════════════════╝

Logique pure (dispatch d'actions, QR flux, watchdog, boot checks, page /view)
vit dans apps/rpi/{actions,qr_flux,watchdog,boot,view}.py — sans dépendance
picamera2, donc importable et testable hors Raspberry Pi. Ce fichier garde la
boucle caméra elle-même (a besoin du matériel) et l'orchestration.
"""

from __future__ import annotations
import logging
import logging.handlers
import signal
import sys
import time
import threading
from pathlib import Path
from enum import Enum, auto

# Lancé en pratique via `python apps/rpi/main.py` (scripts/linux_run.sh,
# deploy/steam-vision.service) : Python place alors le dossier du script
# (apps/rpi/) en sys.path[0], PAS la racine du dépôt -> "from steamcore..."
# échoue avec ModuleNotFoundError sans cette ligne. Même correctif déjà en
# place dans tools/card_test.py, tools/plate_bench.py, tools/pipeline_test.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2
import yaml
from picamera2 import Picamera2

from steamcore.audio import AudioPlayer
from steamcore.video_player import VideoPlayer
from steamcore.rules import RuleEngine
from steamcore.udp import HeartbeatThread, UDPListener
from steamcore.recognition.fast_detector import FastDetector
from steamcore.recognition.card_detector import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from steamcore.recognition.template_registry import TemplateRegistry
from monitor.ws_bridge import start_in_thread as start_ws
from monitor.rule_api import start_in_thread as start_rule_api

from apps.rpi.actions import run_actions, handle_loxone_command
from apps.rpi.qr_flux import QRFluxChecker
from apps.rpi.watchdog import Watchdog
from apps.rpi.boot import boot_checks
from apps.rpi.view import push_event, update_stream_frame, start_mjpeg_server

CONFIG_FILE = "config/features.yaml"
LOG_FILE = "logs/steam_vision.log"

# Carte réservée : auto-test GM (PLATEST/plate_ready_check/). La montrer à la
# caméra confirme que la chaîne caméra->L1->L2->L3->WebSocket fonctionne, via
# un bandeau dédié sur /view — sans déclencher UDP Loxone, vidéo ni audio.
READY_CHECK_CARD_ID = "plate_ready_check"

# ── Monitoring /view (FPS + score continu) ──────────────────────────
FPS_PUSH_INTERVAL = 1.0  # s entre deux mises à jour du compteur FPS
SCORE_PUSH_INTERVAL = 0.3  # s entre deux mises à jour du score ORB en direct

# ── Orientation caméra ───────────────────────────────────────────────
# camera_rotation dans features.yaml (0/90/180/270) corrige le montage
# physique de la caméra. Appliqué juste après capture, avant détection ET
# stream — toute la pipeline (pas seulement /view) voit une image droite.
_ROTATE_MAP = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def _rotate_frame(frame, rotation: int):
    code = _ROTATE_MAP.get(rotation)
    return cv2.rotate(frame, code) if code is not None else frame


# ── Logging ────────────────────────────────────────────────────────


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, console])


log = logging.getLogger("steam")


# ── Config ─────────────────────────────────────────────────────────


def load_config():
    p = Path(CONFIG_FILE)
    if not p.exists():
        log.warning("[config] features.yaml introuvable, valeurs par defaut")
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class State(Enum):
    IDLE = auto()
    STANDBY = auto()  # vidéo en cours — aucune détection


# ── Helpers de boucle partagés card/person ─────────────────────────


class _RunFlag:
    """Installe SIGINT/SIGTERM et expose .running — partagé par les deux
    boucles (run_card_mode/run_person_mode), qui avaient chacune leur propre
    copie du même couple running/nonlocal/_stop. Armé dès la construction :
    pas d'étape séparée à oublier d'appeler."""

    def __init__(self):
        self.running = True

        def _stop(sig, frame):
            self.running = False
            log.info("[stop] Arret propre...")

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)


def _apply_force_reset(video, audio, reset_fn) -> State:
    """Remet à IDLE sur réception de STEAM_RESET (voir apps/rpi/actions.py)."""
    video.stop()
    audio.stop()
    reset_fn()
    log.info("[state] -> IDLE (reset Loxone)")
    push_event({"type": "state", "state": "IDLE"})
    return State.IDLE


# ══════════════════════════════════════════════════════════════════
# MODE CARD  —  L1→L2→L3, hold 2s, vidéo
# ══════════════════════════════════════════════════════════════════


def run_card_mode(cfg, cam, rule_engine, audio, video, watchdog, force_reset):
    card_hold_ms = cfg.get("card_hold_ms", 1000)
    idle_after_s = cfg.get("idle_after_s", 3.0)
    card_min_area = cfg.get("card_min_area", 4000)
    card_min_match = cfg.get("card_min_matches", 12)
    card_threshold = cfg.get("card_score_threshold", 0.20)
    camera_rotation = cfg.get("camera_rotation", 0)
    consec_required = cfg.get("card_consec_frames", 5)

    fast_detector = FastDetector(min_area=card_min_area)
    # Registre partagé : L2 (CardDetector) et L3 (CardRecognizer) chargent
    # les mêmes images PLATEST au démarrage — évite de les lire/décoder deux
    # fois (voir steamcore/recognition/template_registry.py). Les
    # descripteurs restent calculés séparément par backend+config (orb:600
    # vs orb:800) : jamais mélangés.
    template_registry = TemplateRegistry("PLATEST")
    card_detector = CardDetector(registry=template_registry)
    recognizer = CardRecognizer(
        "PLATEST",
        min_matches=card_min_match,
        threshold=card_threshold,
        registry=template_registry,
    )
    qr_checker = QRFluxChecker(cfg.get("mission_id", ""))

    state = State.IDLE
    last_triggered = 0.0
    hold_card_id = None
    hold_start = 0.0
    consec_card_id = None
    consec_count = 0
    frame_count = 0

    fps_count = 0
    fps_last_push = time.time()
    last_score_push = 0.0

    log.info(
        "[card] Pipeline card — IDLE (hold="
        + str(card_hold_ms)
        + "ms, consec="
        + str(consec_required)
        + ")"
    )
    push_event({"type": "state", "state": "IDLE"})

    flag = _RunFlag()

    def _reset_detection():
        nonlocal hold_card_id, hold_start, consec_card_id, consec_count
        hold_card_id = None
        hold_start = 0.0
        consec_card_id = None
        consec_count = 0

    def _push_score(now, card_id, score):
        nonlocal last_score_push
        if now - last_score_push < SCORE_PUSH_INTERVAL:
            return
        last_score_push = now
        push_event({"type": "score", "card_id": card_id, "score": round(score, 3)})

    while flag.running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        watchdog.touch()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame = _rotate_frame(frame, camera_rotation)
        update_stream_frame(frame)
        frame_count += 1
        now = time.time()

        fps_count += 1
        if now - fps_last_push >= FPS_PUSH_INTERVAL:
            fps = fps_count / (now - fps_last_push)
            push_event({"type": "fps", "value": round(fps, 1)})
            fps_count = 0
            fps_last_push = now

        if force_reset.is_set():
            force_reset.clear()
            state = _apply_force_reset(video, audio, _reset_detection)
            continue

        if state == State.STANDBY:
            elapsed = now - last_triggered
            video_done = not video.is_playing()
            if video_done and elapsed >= idle_after_s:
                state = State.IDLE
                _reset_detection()
                log.info("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        qr_event = qr_checker.check(frame, frame_count, now)
        if qr_event:
            push_event(qr_event)

        quad = fast_detector.detect(frame)
        if quad is None:
            if consec_card_id is not None:
                _reset_detection()
            _push_score(now, None, 0.0)
            continue

        roi = quad.crop(frame)
        l2_start = time.time()
        region = card_detector.detect(roi)
        l2_ms = (time.time() - l2_start) * 1000
        if region is None:
            if consec_card_id is not None:
                _reset_detection()
            _push_score(now, None, 0.0)
            continue

        # hint_id = candidat produit par L2 : borne L3 aux seules images de
        # cette plaque au lieu de rescanner tout PLATEST à chaque frame.
        hint_id = region.card_id
        l3_start = time.time()
        result = recognizer.recognize(region.warped, hint_id=hint_id)
        l3_ms = (time.time() - l3_start) * 1000
        log.debug(
            f"[perf] L2={l2_ms:.1f}ms L3={l3_ms:.1f}ms hint_id={hint_id!r} "
            f"templates={recognizer.last_templates_scanned} "
            f"images={recognizer.last_images_scanned}"
        )
        _push_score(now, recognizer.last_card_id, recognizer.last_score)
        if result is None:
            if consec_card_id is not None:
                _reset_detection()
            continue

        if result.card_id != consec_card_id:
            consec_card_id = result.card_id
            consec_count = 1
            hold_card_id = None
            hold_start = 0.0
            continue

        consec_count += 1
        if consec_count < consec_required:
            continue

        if hold_card_id is None:
            hold_card_id = result.card_id
            hold_start = now
            push_event(
                {
                    "type": "card_detected",
                    "card_id": result.card_id,
                    "label": result.label,
                    "score": round(result.score, 3),
                }
            )
            log.info(
                "[card] confirmée ("
                + str(consec_required)
                + "f) : "
                + result.label
                + "  score="
                + str(round(result.score, 3))
            )

        held_ms = (now - hold_start) * 1000
        pct = min(100, int(held_ms / card_hold_ms * 100))
        push_event(
            {
                "type": "hold",
                "card_id": result.card_id,
                "label": result.label,
                "pct": pct,
                "held_ms": int(held_ms),
                "target_ms": card_hold_ms,
            }
        )

        if held_ms < card_hold_ms:
            continue

        if result.card_id == READY_CHECK_CARD_ID:
            log.info("[ready-check] STEAM VISION READY (auto-test GM)")
            push_event({"type": "system_ready", "label": "STEAM VISION READY"})
            _reset_detection()
            continue

        log.info(
            "[TRIGGER] "
            + result.label
            + "  score="
            + str(round(result.score, 3))
            + "  hold="
            + str(int(held_ms))
            + "ms"
        )
        push_event({"type": "state", "state": "STANDBY"})
        run_actions(cfg, rule_engine, result, audio, video)
        state = State.STANDBY
        last_triggered = now
        _reset_detection()
        log.info("[state] -> STANDBY (" + str(idle_after_s) + "s)")

    log.info("[stop] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════
# MODE PERSON  —  YOLO + audio seulement
# ══════════════════════════════════════════════════════════════════


def run_person_mode(cfg, cam, rule_engine, audio, video, watchdog, force_reset):
    from steamcore.detector import YOLODetector
    from steamcore.person_tracker import PersonTracker

    person_duration = cfg.get("person_duration", 2.0)
    persist = cfg.get("persist_after_loss", 5.0)
    idle_after_s = cfg.get("idle_after_s", 3.0)
    camera_rotation = cfg.get("camera_rotation", 0)

    detector = YOLODetector(
        model_path=cfg.get("yolo_model", "yolov8n.pt"),
        imgsz=cfg.get("yolo_imgsz", 320),
        conf=cfg.get("yolo_conf", 0.5),
    )
    tracker = PersonTracker(
        person_duration=person_duration,
        persist_after_loss=persist,
        grace_frames=15,
    )

    state = State.IDLE
    last_triggered = 0.0
    last_count = 0.0
    frame_count = 0

    log.info("[person] Pipeline person — IDLE (duration=" + str(person_duration) + "s)")
    push_event({"type": "state", "state": "IDLE"})

    flag = _RunFlag()

    while flag.running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        watchdog.touch()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame = _rotate_frame(frame, camera_rotation)
        update_stream_frame(frame)
        frame_count += 1
        now = time.time()

        if force_reset.is_set():
            force_reset.clear()
            state = _apply_force_reset(video, audio, tracker.reset)
            continue

        if state == State.STANDBY:
            if now - last_triggered >= idle_after_s:
                state = State.IDLE
                tracker.reset()
                log.info("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        pf = detector.detect_persons(frame)
        ts = tracker.update(pf)

        if now - last_count > 3.0 and pf.count > 0:
            push_event({"type": "count", "value": pf.count})
            last_count = now

        if ts.ready_for_inspect and state == State.IDLE:
            log.info(
                "[person] Joueur détecté depuis "
                + str(round(ts.presence_elapsed, 1))
                + "s -> TRIGGER"
            )
            push_event({"type": "state", "state": "STANDBY"})
            run_actions(cfg, rule_engine, "person", audio, video)
            state = State.STANDBY
            last_triggered = now
            log.info("[state] -> STANDBY (" + str(idle_after_s) + "s)")

    log.info("[stop] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════


def main():
    setup_logging()
    boot_checks()  # ← vérifie mpv, PLATEST, rules.yaml — abort si critique

    cfg = load_config()

    pipeline_mode = cfg.get("pipeline_mode", "card")
    monitor_on = cfg.get("enable_monitor", True)
    rule_api_on = cfg.get("enable_rule_api", True)
    heartbeat_on = cfg.get("enable_heartbeat", True)
    listen_port = cfg.get("udp_listen_port", 8888)
    stream_on = cfg.get("enable_stream", True)
    stream_port = cfg.get("stream_port", 5050)
    watchdog_on = cfg.get("enable_watchdog", True)
    watchdog_timeout_s = cfg.get("watchdog_timeout_s", 20.0)

    log.info("=" * 55)
    log.info("  S.T.E.A.M Vision — STYX  |  Pi 5")
    log.info("=" * 55)
    log.info("  Mode        : " + pipeline_mode.upper())
    if pipeline_mode == "card":
        log.info("  Hold        : " + str(cfg.get("card_hold_ms", 2000)) + "ms")
    log.info("  Idle after  : " + str(cfg.get("idle_after_s", 3.0)) + "s")
    log.info("  Monitor WS  : " + ("ON :8889" if monitor_on else "OFF"))
    log.info("  Rule API    : " + ("ON :8890" if rule_api_on else "OFF"))
    log.info(
        "  Stream MJPEG: "
        + (f"ON  http://0.0.0.0:{stream_port}/stream" if stream_on else "OFF")
    )
    log.info(
        "  View page   : "
        + (f"ON  http://0.0.0.0:{stream_port}/view" if stream_on else "OFF")
    )
    log.info(
        "  Watchdog    : "
        + (f"ON  timeout={watchdog_timeout_s}s" if watchdog_on else "OFF")
    )

    rule_engine = RuleEngine("config/rules.yaml")
    audio = AudioPlayer("assets/audio")
    video = VideoPlayer("assets/video")
    force_reset = threading.Event()
    watchdog = Watchdog(watchdog_timeout_s)

    if monitor_on:
        start_ws()
    if rule_api_on:
        start_rule_api(engine=rule_engine)
    if stream_on:
        start_mjpeg_server(port=stream_port)
    if heartbeat_on:
        HeartbeatThread(interval=5.0).start()
    if watchdog_on:
        watchdog.touch()
        watchdog.start()

    UDPListener(
        port=listen_port,
        on_message=lambda msg, addr: handle_loxone_command(
            msg, addr, cfg, rule_engine, audio, video, force_reset
        ),
    ).start()

    cam = Picamera2()
    cam.configure(
        cam.create_preview_configuration(
            main={
                "format": "RGB888",
                "size": (cfg.get("camera_width", 1280), cfg.get("camera_height", 720)),
            }
        )
    )
    cam.start()
    log.info("[init] Camera OK")

    if pipeline_mode == "person":
        run_person_mode(cfg, cam, rule_engine, audio, video, watchdog, force_reset)
    else:
        run_card_mode(cfg, cam, rule_engine, audio, video, watchdog, force_reset)

    cam.stop()
    audio.stop()
    video.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("[main] Interruption clavier — arrêt propre.")
    except Exception:
        logging.exception("[main] CRASH NON GÉRÉ — voir logs/steam_vision.log")
        sys.exit(1)
