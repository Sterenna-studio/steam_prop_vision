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
"""

from __future__ import annotations
import logging
import logging.handlers
import os
import shutil
import signal
import subprocess
import sys
import time
import threading
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from enum import Enum, auto

import json

import cv2
import yaml
from picamera2 import Picamera2

from steamcore.audio import AudioPlayer
from steamcore.video_player import VideoPlayer
from steamcore.rules import RuleEngine
from steamcore.udp import send_event as udp_send_raw, HeartbeatThread, UDPListener
from steamcore.recognition.fast_detector import FastDetector
from steamcore.recognition.card_detector import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from monitor.ws_bridge import start_in_thread as start_ws, push_event as _push_event_raw
from monitor.rule_api import start_in_thread as start_rule_api

try:
    from pyzbar.pyzbar import decode as _zbar_decode

    _QR_BACKEND = "zbar"
except ImportError:
    _zbar_decode = None
    _QR_BACKEND = "cv2"

CONFIG_FILE = "config/features.yaml"
LOG_FILE = "logs/steam_vision.log"

# Carte réservée : auto-test GM (PLATEST/plate_ready_check/). La montrer à la
# caméra confirme que la chaîne caméra->L1->L2->L3->WebSocket fonctionne, via
# un bandeau dédié sur /view — sans déclencher UDP Loxone, vidéo ni audio.
READY_CHECK_CARD_ID = "plate_ready_check"

# QR de validation de flux/mission. Format attendu : "STEAM_FLUX:<mission_id>"
# (ex: STEAM_FLUX:flux_1). Comparé à cfg["mission_id"] — lecture seule, ne
# modifie jamais la config active.
#
# Décodage : pyzbar/ZBar en priorité (pip install pyzbar + apt install
# libzbar0). cv2.QRCodeDetector (natif, sans dépendance) est utilisé en
# repli, mais s'est montré peu fiable en pratique : il échoue de façon
# reproductible sur certains QR pourtant valides (ex. contenu se terminant
# par un chiffre impair dans nos tests) — voir DEPENDENCIES.md. À n'utiliser
# que si pyzbar/libzbar0 ne peuvent pas être installés.
QR_FLUX_PREFIX = "STEAM_FLUX:"
QR_CHECK_EVERY = 5  # ne scanne le QR qu'une frame sur N (coût CPU)
QR_REPEAT_COOLDOWN = 3.0  # s avant de repousser le même event pour le même QR


def _decode_qr(frame, cv2_detector) -> str | None:
    """Décode un QR dans la frame (pyzbar si dispo, sinon cv2 en repli)."""
    if _zbar_decode is not None:
        results = _zbar_decode(frame)
        return results[0].data.decode("utf-8", errors="ignore") if results else None
    data, _, _ = cv2_detector.detectAndDecode(frame)
    return data or None


class QRFluxChecker:
    """Scan QR de validation de flux/mission (1 frame sur QR_CHECK_EVERY).

    Lecture seule : compare le flux scanné à mission_id, ne modifie jamais la
    config active. check() retourne l'event à pousser sur le monitor WS
    (system_ready / flux_mismatch), ou None si rien à signaler.
    """

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._cv2_detector = cv2.QRCodeDetector()  # utilisé si pyzbar absent
        self._last_payload: str | None = None
        self._last_time = 0.0
        log.info(f"[qr] Backend décodage : {_QR_BACKEND}")
        if _QR_BACKEND != "zbar":
            log.warning(
                "[qr] pyzbar/libzbar0 absent — repli sur cv2.QRCodeDetector, "
                "moins fiable (voir DEPENDENCIES.md). "
                "Installer : sudo apt install libzbar0 && pip install pyzbar"
            )

    def check(self, frame, frame_count: int, now: float) -> dict | None:
        if frame_count % QR_CHECK_EVERY != 0:
            return None
        data = _decode_qr(frame, self._cv2_detector)
        if not data or not data.startswith(QR_FLUX_PREFIX):
            return None

        flux_id = data[len(QR_FLUX_PREFIX) :]
        repeat = (
            flux_id == self._last_payload
            and (now - self._last_time) < QR_REPEAT_COOLDOWN
        )
        if repeat:
            return None
        self._last_payload = flux_id
        self._last_time = now

        if flux_id == self.mission_id:
            log.info(f"[qr] Flux valide : {flux_id}")
            return {
                "type": "system_ready",
                "label": f"STEAM VISION READY — {flux_id.upper()}",
            }
        log.warning(
            f"[qr] Flux inattendu : scanné={flux_id!r} attendu={self.mission_id!r}"
        )
        return {
            "type": "flux_mismatch",
            "expected": self.mission_id,
            "scanned": flux_id,
        }


# ── MJPEG stream (optionnel, thread daemon) ────────────────────────
_stream_frame: bytes | None = None
_stream_lock = threading.Lock()
_stream_last_update: float = 0.0


def _update_stream_frame(frame, fps_limit: float = 20.0) -> None:
    """Encode la frame courante en JPEG et la partage avec le serveur MJPEG.
    Throttlé à fps_limit pour ne pas impacter le pipeline principal."""
    global _stream_frame, _stream_last_update
    now = time.time()
    if now - _stream_last_update < 1.0 / fps_limit:
        return
    _stream_last_update = now
    try:
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with _stream_lock:
                _stream_frame = buf.tobytes()
    except Exception:
        pass


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _start_mjpeg_server(port: int = 5050) -> None:
    """Démarre un serveur MJPEG minimal en thread daemon.
    Si ça plante, le pipeline principal continue sans le stream."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silence logs HTTP

        def do_GET(self):
            if self.path in ("/", "/view"):
                body = _VIEW_HTML
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/status":
                with _view_lock:
                    data = dict(_view_status)
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/stream":
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.end_headers()
                try:
                    while True:
                        with _stream_lock:
                            data = _stream_frame
                        if data is None:
                            time.sleep(0.05)
                            continue
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                            + data
                            + b"\r\n"
                        )
                        time.sleep(0.05)  # ~20 fps côté client
                except Exception:
                    pass
            else:
                self.send_response(404)
                self.end_headers()

    def _run():
        try:
            srv = _ThreadedHTTPServer(("0.0.0.0", port), Handler)
            log.info(f"[stream] MJPEG  →  http://0.0.0.0:{port}/stream")
            srv.serve_forever()
        except Exception as e:
            log.warning(f"[stream] Désactivé — {e}")

    threading.Thread(target=_run, daemon=True, name="mjpeg-stream").start()


# ── View status (partagé pipeline → HTTP) ─────────────────────────
_view_status: dict = {
    "fsm": "IDLE",
    "card_id": None,
    "card_label": None,
    "hold_pct": 0,
}
_view_lock = threading.Lock()


# ── Watchdog anti-freeze ─────────────────────────────────────────────
# systemd (Restart=on-failure) ne relance que si le PROCESS meurt. Si la
# boucle principale se fige (ex: appel caméra/IPC bloqué) sans faire mourir
# le process, rien ne le détecte. Ce watchdog force un os._exit(1) si aucune
# itération de la boucle n'a "touché" _last_alive depuis watchdog_timeout_s
# — systemd relance alors normalement.
_last_alive = time.time()
_alive_lock = threading.Lock()


def _touch_alive() -> None:
    global _last_alive
    with _alive_lock:
        _last_alive = time.time()


def _watchdog_loop(timeout_s: float) -> None:
    while True:
        time.sleep(5.0)
        with _alive_lock:
            stale = time.time() - _last_alive
        if stale > timeout_s:
            log.error(
                f"[watchdog] Boucle principale figée depuis {stale:.0f}s "
                "-> arrêt forcé (systemd relancera)"
            )
            os._exit(1)


def push_event(event: dict) -> None:
    """Transmet l'event au WebSocket ET met à jour le statut view."""
    _push_event_raw(event)
    t = event.get("type")
    if t == "state":
        st = event.get("state", "")
        with _view_lock:
            _view_status["fsm"] = st
            if st == "IDLE":
                _view_status["card_id"] = None
                _view_status["card_label"] = None
                _view_status["hold_pct"] = 0
    elif t == "card_detected":
        with _view_lock:
            _view_status["card_id"] = event.get("card_id")
            _view_status["card_label"] = event.get("label")
    elif t == "hold":
        with _view_lock:
            _view_status["hold_pct"] = event.get("pct", 0)


# ── Page /view ─────────────────────────────────────────────────────
_VIEW_HTML = b"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>S.T.E.A.M \xe2\x80\x94 View</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#000;color:#fff;font-family:monospace;height:100vh;display:flex;flex-direction:column;overflow:hidden}
#wrap{flex:1;position:relative;overflow:hidden;background:#111}
#stream{width:100%;height:100%;object-fit:contain;display:block}
#hold{position:absolute;bottom:14px;left:5%;right:5%;display:none}
#hold-track{background:rgba(255,255,255,.15);border-radius:6px;height:8px;overflow:hidden}
#hold-fill{height:8px;background:#00e5cc;border-radius:6px;width:0%;transition:width .1s linear}
#hold-txt{text-align:center;margin-top:5px;font-size:13px;color:#00e5cc;text-shadow:0 0 8px #00e5cc}
#standby{position:absolute;inset:0;background:rgba(0,0,0,.78);display:none;flex-direction:column;align-items:center;justify-content:center;gap:16px}
#standby .icon{font-size:72px;color:#00e5cc;text-shadow:0 0 40px #00e5cc88}
#standby .name{font-size:clamp(18px,3vw,32px);letter-spacing:.12em}
#standby .sub{font-size:13px;color:#888;letter-spacing:.08em}
.banner{position:absolute;inset:0;background:rgba(0,0,0,.85);display:none;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.banner .check{width:64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px}
.banner .txt{font-size:clamp(15px,2.6vw,26px);letter-spacing:.06em;font-weight:bold}
.banner .sub{font-size:11px;letter-spacing:.05em}
.banner.ok .check{background:#0d2318;border:2px solid #4caf50;color:#4caf50}
.banner.ok .txt{color:#4caf50}
.banner.ok .sub{color:#666}
.banner.warn .check{background:#2b1710;border:2px solid #ff9800;color:#ff9800}
.banner.warn .txt{color:#ff9800}
.banner.warn .sub{color:#999}
#bar{height:44px;background:rgba(0,0,0,.92);border-top:1px solid #1a1a1a;display:flex;align-items:center;padding:0 18px;gap:20px;font-size:12px}
.badge{padding:2px 9px;border-radius:3px;font-weight:bold;letter-spacing:.08em;font-size:11px}
#fsm-b{background:#222;color:#666}
#fsm-b.idle{background:#0d1f0d;color:#4caf50}
#fsm-b.standby{background:#001f1f;color:#00e5cc}
#card-d{color:#bbb}
#ws-d{margin-left:auto;font-size:10px;color:#444}
#ws-d.ok{color:#4caf50}
#ws-d.err{color:#e53935}
</style>
</head>
<body>
<div id="wrap">
  <img id="stream" src="/stream" alt="">
  <div id="hold">
    <div id="hold-track"><div id="hold-fill"></div></div>
    <div id="hold-txt"></div>
  </div>
  <div id="standby">
    <div class="icon">&#9654;</div>
    <div class="name" id="sb-name">\xe2\x80\x94</div>
    <div class="sub">en cours de lecture</div>
  </div>
  <div id="ready" class="banner ok">
    <div class="check">&#10003;</div>
    <div class="txt" id="ready-txt">STEAM VISION READY</div>
    <div class="sub">CAM&Eacute;RA &middot; D&Eacute;TECTION &middot; RECONNAISSANCE &mdash; OK</div>
  </div>
  <div id="mismatch" class="banner warn">
    <div class="check">&#33;</div>
    <div class="txt">FLUX INATTENDU</div>
    <div class="sub" id="mismatch-sub">&mdash;</div>
  </div>
</div>
<div id="bar">
  <span>FSM&nbsp;<span id="fsm-b" class="badge idle">IDLE</span></span>
  <span id="card-d">\xe2\x80\x94</span>
  <span id="ws-d">&#9679; ws\xe2\x80\xa6</span>
</div>
<script>
const $=id=>document.getElementById(id);
const fsmEl=$('fsm-b'),cardEl=$('card-d'),wsEl=$('ws-d');
const holdEl=$('hold'),holdFill=$('hold-fill'),holdTxt=$('hold-txt');
const sbEl=$('standby'),sbName=$('sb-name');
const readyEl=$('ready'),readyTxt=$('ready-txt');
const mismatchEl=$('mismatch'),mismatchSub=$('mismatch-sub');

function flash(el,ms){
  el.style.display='flex';
  clearTimeout(el._t);
  el._t=setTimeout(()=>{el.style.display='none';},ms||4000);
}
function fsm(s){
  fsmEl.textContent=s;
  fsmEl.className='badge '+(s==='STANDBY'?'standby':'idle');
}
function handle(ev){
  if(ev.type==='state'){
    fsm(ev.state);
    if(ev.state==='STANDBY'){sbEl.style.display='flex';holdEl.style.display='none';}
    else{sbEl.style.display='none';if(ev.state==='IDLE'){holdEl.style.display='none';cardEl.textContent='\xe2\x80\x94';}}
  }else if(ev.type==='card_detected'){
    cardEl.textContent=ev.label;sbName.textContent=ev.label;
  }else if(ev.type==='hold'){
    holdEl.style.display='block';
    holdFill.style.width=ev.pct+'%';
    holdTxt.textContent=ev.label+'  '+ev.pct+'%';
    cardEl.textContent=ev.label;
  }else if(ev.type==='system_ready'){
    holdEl.style.display='none';
    cardEl.textContent='\xe2\x80\x94';
    readyTxt.textContent=ev.label||'STEAM VISION READY';
    flash(readyEl);
  }else if(ev.type==='flux_mismatch'){
    holdEl.style.display='none';
    cardEl.textContent='\xe2\x80\x94';
    mismatchSub.textContent='attendu '+(ev.expected||'?')+' \xe2\x80\x94 re\xc3\xa7u '+(ev.scanned||'?');
    flash(mismatchEl);
  }
}
function connect(){
  const ws=new WebSocket('ws://'+location.hostname+':8889');
  ws.onopen=()=>{wsEl.textContent='\xe2\x97\x8f connect\xe9';wsEl.className='ok';};
  ws.onclose=()=>{wsEl.textContent='\xe2\x97\x8b reconnexion\xe2\x80\xa6';wsEl.className='err';setTimeout(connect,3000);};
  ws.onerror=()=>ws.close();
  ws.onmessage=e=>{try{handle(JSON.parse(e.data));}catch(_){}};
}
fetch('/api/status').then(r=>r.json()).then(s=>{
  fsm(s.fsm||'IDLE');
  if(s.card_label){cardEl.textContent=s.card_label;sbName.textContent=s.card_label;}
  if(s.fsm==='STANDBY'){sbEl.style.display='flex';}
}).catch(()=>{});
connect();
</script>
</body>
</html>
"""


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


# ── Boot checks ────────────────────────────────────────────────────


def _kill_orphan_players():
    """Tue les mpv/ffplay orphelins d'un crash précédent (best-effort).

    Un crash brutal du process principal (SIGKILL, freeze -> watchdog) laisse
    le sous-processus mpv/ffplay tourner indépendamment (reparenté à init) :
    sans ce nettoyage, il continue d'afficher/boucler par-dessus la nouvelle
    instance qui redémarre.
    """
    if not shutil.which("pkill"):
        return
    for name in ("mpv", "ffplay"):
        try:
            subprocess.run(
                ["pkill", "-x", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            log.warning(f"[boot] pkill {name} : {e}")


def boot_checks():
    """Vérifie les dépendances critiques au démarrage. Abort si manquant."""
    _kill_orphan_players()
    errors = []

    # Lecteur vidéo
    players = ["mpv", "ffplay", "vlc"]
    if not any(shutil.which(p) for p in players):
        errors.append(
            "Aucun lecteur vidéo trouvé (mpv / ffplay / vlc). "
            "Installer avec : sudo apt install mpv"
        )
    else:
        found = next(p for p in players if shutil.which(p))
        log.info(f"[boot] Lecteur vidéo : {found} OK")

    # aplay pour l'audio
    if not shutil.which("aplay") and not shutil.which("mpg123"):
        log.warning("[boot] WARN : aplay et mpg123 introuvables — audio désactivé")

    # PLATEST
    if not Path("PLATEST").exists() or not any(Path("PLATEST").iterdir()):
        errors.append("Dossier PLATEST vide ou absent — aucun template de plate.")
    else:
        plates = [d for d in Path("PLATEST").iterdir() if d.is_dir()]
        log.info(f"[boot] PLATEST : {len(plates)} plate(s) trouvée(s)")

    # config/rules.yaml
    if not Path("config/rules.yaml").exists():
        log.warning(
            "[boot] WARN : config/rules.yaml absent — aucune action ne sera déclenchée"
        )

    if errors:
        for e in errors:
            log.error(f"[boot] ERREUR CRITIQUE : {e}")
        log.error("[boot] Démarrage annulé.")
        sys.exit(1)


class State(Enum):
    IDLE = auto()
    STANDBY = auto()  # vidéo en cours — aucune détection


# ── Helpers ───────────────────────────────────────────────────────


def udp_send(msg, ip, port):
    """Envoie UDP + pousse l'event sur le monitor WS."""
    try:
        udp_send_raw(msg, ip, port)
    except Exception as e:
        log.error("[udp] ERREUR : " + str(e))
    push_event({"type": "udp_sent", "msg": msg, "ip": ip, "port": port})


def run_actions(cfg, rule_engine, label_or_result, audio, video, card_id=None):
    """
    Dispatche les actions d'une règle (carte ou person).
    label_or_result : RecognitionResult (mode card) ou str (mode person).
    """
    lox_ip = cfg.get("loxone_ip", "192.168.1.50")
    lox_port = cfg.get("loxone_port", 7777)

    if hasattr(label_or_result, "card_id"):
        cid = label_or_result.card_id
    else:
        cid = label_or_result

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


# ══════════════════════════════════════════════════════════════════
# MODE CARD  —  L1→L2→L3, hold 2s, vidéo
# ══════════════════════════════════════════════════════════════════


def run_card_mode(cfg, cam, rule_engine, audio, video):
    card_hold_ms = cfg.get("card_hold_ms", 1000)
    idle_after_s = cfg.get("idle_after_s", 3.0)
    card_min_area = cfg.get("card_min_area", 4000)
    card_min_match = cfg.get("card_min_matches", 12)
    card_threshold = cfg.get("card_score_threshold", 0.20)
    consec_required = cfg.get("card_consec_frames", 5)

    fast_detector = FastDetector(min_area=card_min_area)
    card_detector = CardDetector()
    recognizer = CardRecognizer(
        "PLATEST", min_matches=card_min_match, threshold=card_threshold
    )
    qr_checker = QRFluxChecker(cfg.get("mission_id", ""))

    state = State.IDLE
    last_triggered = 0.0
    hold_card_id = None
    hold_start = 0.0
    consec_card_id = None
    consec_count = 0
    frame_count = 0

    log.info(
        "[card] Pipeline card — IDLE (hold="
        + str(card_hold_ms)
        + "ms, consec="
        + str(consec_required)
        + ")"
    )
    push_event({"type": "state", "state": "IDLE"})

    running = True

    def _stop(s, f):
        nonlocal running
        running = False
        log.info("[stop] Arret propre...")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def _reset_detection():
        nonlocal hold_card_id, hold_start, consec_card_id, consec_count
        hold_card_id = None
        hold_start = 0.0
        consec_card_id = None
        consec_count = 0

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        _touch_alive()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _update_stream_frame(frame)
        frame_count += 1
        now = time.time()

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
            continue

        roi = quad.crop(frame)
        region = card_detector.detect(roi)
        if region is None:
            if consec_card_id is not None:
                _reset_detection()
            continue

        result = recognizer.recognize(region.warped)
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


def run_person_mode(cfg, cam, rule_engine, audio, video):
    from steamcore.detector import YOLODetector
    from steamcore.person_tracker import PersonTracker

    person_duration = cfg.get("person_duration", 2.0)
    persist = cfg.get("persist_after_loss", 5.0)
    idle_after_s = cfg.get("idle_after_s", 3.0)

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

    running = True

    def _stop(s, f):
        nonlocal running
        running = False
        log.info("[stop] Arret propre...")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        _touch_alive()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _update_stream_frame(frame)
        frame_count += 1
        now = time.time()

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

    if monitor_on:
        start_ws()
    if rule_api_on:
        start_rule_api(engine=rule_engine)
    if stream_on:
        _start_mjpeg_server(port=stream_port)
    if heartbeat_on:
        HeartbeatThread(interval=5.0).start()
    if watchdog_on:
        _touch_alive()
        threading.Thread(
            target=_watchdog_loop,
            args=(watchdog_timeout_s,),
            daemon=True,
            name="watchdog",
        ).start()

    UDPListener(
        port=listen_port,
        on_message=lambda msg, addr: (
            log.info("[UDP RX] " + addr[0] + " -> " + msg),
            push_event({"type": "udp_rx", "msg": msg, "from": addr[0]}),
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
        run_person_mode(cfg, cam, rule_engine, audio, video)
    else:
        run_card_mode(cfg, cam, rule_engine, audio, video)

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
