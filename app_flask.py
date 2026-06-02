# app_flask.py  -  steam_prop_vision (Pi headless)
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, threading, argparse, socket
os.environ.setdefault('OPENCV_LOG_LEVEL', 'SILENT')

from flask import Flask, Response, request, jsonify, send_file
import cv2
from picamera2 import Picamera2

from core.sim_core import SimulationEngine
from gui.config_manager import load_config_folder, get_plaques_folder
from gui.rule_engine import RuleEngine
from gui.action_router import ActionRouter

# ── Config ──────────────────────────────────────────────────────────────────
CAM_WIDTH     = 1280
CAM_HEIGHT    = 720
JPEG_QUALITY  = 80
AWB_WARMUP_S  = 2.0
FLASK_PORT    = 5050
LOOP_INTERVAL = 0.05   # ~20 fps

_DASHBOARD = os.path.join(os.path.dirname(__file__), 'monitor', 'dashboard.html')

# ── Loxone UDP ─────────────────────────────────────────────────────────────────
LOXONE_IP      = os.environ.get('LOXONE_IP',   '192.168.1.50')
LOXONE_PORT    = int(os.environ.get('LOXONE_PORT', '7777'))
LOXONE_ENABLED = os.environ.get('LOXONE_ENABLED', '1') not in ('0', 'false', 'False', 'no')

# Anti-spam : délai minimum entre deux envois du même message (secondes)
_LOX_COOLDOWN  = 2.0
_lox_last_sent: dict[str, float] = {}
_lox_lock = threading.Lock()

def lox_send(msg: str, force: bool = False) -> bool:
    """
    Envoie un message UDP au Miniserver Loxone.
    Retourne True si envoyé, False si throttlé ou désactivé.
    Anti-spam : un même message ne peut être renvoyé qu'après _LOX_COOLDOWN secondes.
    """
    if not LOXONE_ENABLED:
        return False
    now = time.time()
    with _lox_lock:
        last = _lox_last_sent.get(msg, 0.0)
        if not force and (now - last) < _LOX_COOLDOWN:
            return False
        _lox_last_sent[msg] = now
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.sendto(msg.encode('utf-8'), (LOXONE_IP, LOXONE_PORT))
        print(f"[loxone] → {LOXONE_IP}:{LOXONE_PORT}  '{msg}'")
        return True
    except Exception as e:
        print(f"[loxone] ERR send '{msg}': {e}")
        return False

def lox_send_value(key: str, value: float) -> bool:
    """Envoie un message analogique : 'key VALUE' (ex: 'presence 0.92')."""
    return lox_send(f"{key} {value:.3f}")

# ── Globals ──────────────────────────────────────────────────────────────────
app        = Flask(__name__)
engine     = SimulationEngine()
rules      = RuleEngine()
router     = ActionRouter()
_detectors = []

_lock         = threading.Lock()
_latest_frame = None
_status       = {
    "fsm": "IDLE", "presence": False, "presence_score": 0.0,
    "plaque": None, "plaque_score": 0.0, "t": 0.0,
    "action_log": [], "config_folder": None,
    "loxone_ip": LOXONE_IP, "loxone_port": LOXONE_PORT, "loxone_enabled": LOXONE_ENABLED,
}
_presence_prev    = False
_plaque_prev: str | None = None
_fsm_prev: str            = "IDLE"
_action_log_lines = []

# ── Picamera2 ─────────────────────────────────────────────────────────────────
def init_camera() -> Picamera2:
    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"size": (CAM_WIDTH, CAM_HEIGHT), "format": "RGB888"}
    ))
    cam.start()
    print(f"[cam] AWB warmup {AWB_WARMUP_S}s...")
    time.sleep(AWB_WARMUP_S)
    print("[cam] Ready")
    return cam

# ── Pipeline thread ───────────────────────────────────────────────────────────
def pipeline_loop(cam: Picamera2):
    global _latest_frame, _presence_prev, _plaque_prev, _fsm_prev, _action_log_lines

    while True:
        t0 = time.time()

        rgb   = cam.capture_array()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        validated = rules.process_frame(frame)

        action_lines = []

        # ── PRÉSENCE : front montant (absent → présent)
        if validated.presence and not _presence_prev:
            action_lines += router.handle(
                key="presence", presence=True,
                sim_engine=engine,
                default_conf=max(0.0, min(1.0, validated.presence_score)),
            )
            lox_send("presence")
            lox_send_value("presence_score", validated.presence_score)

        # ── PRÉSENCE : front descendant (présent → absent)
        if not validated.presence and _presence_prev:
            lox_send("presence_off")

        _presence_prev = bool(validated.presence)

        # ── PLAQUE : nouvelle plaque détectée
        if validated.plaque_id and validated.plaque_id != _plaque_prev:
            action_lines += router.handle(
                key=f"PLAQUE:{validated.plaque_id}",
                presence=validated.presence,
                sim_engine=engine,
                default_conf=max(0.0, min(1.0, validated.plaque_score)),
            )
            engine.inject_detection(
                f"PLAQUE:{validated.plaque_id}",
                max(0.0, min(1.0, validated.plaque_score)),
            )
            plaque_key = f"PLAQUE_{validated.plaque_id.upper().replace(' ', '_').replace('-', '_')}"
            lox_send(plaque_key)
            lox_send_value(f"{plaque_key}_score", validated.plaque_score)

        # ── PLAQUE : disparition
        if not validated.plaque_id and _plaque_prev:
            lox_send("plaque_off")

        _plaque_prev = validated.plaque_id

        if validated.presence:
            engine.inject_detection("presence",
                max(0.0, min(1.0, validated.presence_score)))

        engine.step(LOOP_INTERVAL)

        for det in _detectors:
            try:
                results = det.process_frame(frame)
            except Exception:
                results = []
            for r in results:
                al = router.handle(
                    key=r.label, presence=validated.presence,
                    sim_engine=engine, default_conf=r.confidence,
                )
                action_lines += al
                engine.inject_detection(r.label, r.confidence)

        _action_log_lines = (action_lines + _action_log_lines)[:50]

        snap = engine.snapshot()
        fsm_state = snap["fsm"]["state"]

        # ── FSM : changement d'état
        if fsm_state != _fsm_prev:
            lox_send(f"FSM_{fsm_state}")
            if fsm_state == "DONE":
                lox_send("STEAM_RUN_OK", force=True)
            elif fsm_state == "ERROR":
                lox_send("STEAM_ERROR", force=True)
            _fsm_prev = fsm_state

        cv2.putText(frame,
            f"presence={validated.presence} score={validated.presence_score:.2f}"
            f" ({rules.last_presence.detail})",
            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        plaque_txt = "plaque=none"
        if rules.last_plaque:
            plaque_txt = (f"plaque={rules.last_plaque.plaque_id}"
                          f" score={rules.last_plaque.score:.2f}"
                          f" good={rules.last_plaque.good_matches}")
        cv2.putText(frame, plaque_txt,
            (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(frame, f"FSM:{fsm_state} t={snap['t']:.1f}s",
            (10, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
        lox_str = f"LOX:{LOXONE_IP}:{LOXONE_PORT}" if LOXONE_ENABLED else "LOX:OFF"
        cv2.putText(frame, lox_str,
            (10, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 60), 1)

        with _lock:
            _latest_frame = frame.copy()
            _status.update({
                "fsm": fsm_state,
                "presence": bool(validated.presence),
                "presence_score": round(validated.presence_score, 3),
                "plaque": validated.plaque_id,
                "plaque_score": round(validated.plaque_score, 3),
                "t": round(snap["t"], 1),
                "action_log": _action_log_lines[:10],
                "config_folder": _status.get("config_folder"),
                "loxone_ip": LOXONE_IP,
                "loxone_port": LOXONE_PORT,
                "loxone_enabled": LOXONE_ENABLED,
            })

        elapsed = time.time() - t0
        time.sleep(max(0.0, LOOP_INTERVAL - elapsed))

# ── MJPEG generator ───────────────────────────────────────────────────────────
def gen_frames():
    while True:
        with _lock:
            frame = _latest_frame
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n'
               + buf.tobytes() + b'\r\n')

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return """<!DOCTYPE html><html><head>
<title>steam_prop_vision</title>
<style>
  body{background:#111;color:#eee;font-family:monospace;padding:16px;margin:0}
  img{max-width:100%;border:1px solid #333}
  .card{background:#222;padding:12px;margin:8px 0;border-radius:6px;line-height:1.8}
  input{background:#333;color:#eee;border:1px solid #555;padding:4px;width:360px}
  button{background:#444;color:#eee;border:none;padding:6px 14px;cursor:pointer;border-radius:4px}
  h2{color:#0df}
  .monitor-link{display:inline-block;margin:12px 0;padding:8px 18px;background:#00c8b4;color:#000;text-decoration:none;border-radius:6px;font-weight:700;font-family:monospace;}
  .monitor-link:hover{background:#00b0a0;}
</style>
</head><body>
<h2>&#127909; steam_prop_vision</h2>
<a class="monitor-link" href="/monitor">&#128202; Ouvrir le Monitor</a>
<img src="/stream"><br>
<div class="card">
  <b>FSM:</b> <span id="fsm">-</span> &nbsp;|&nbsp; <b>t:</b> <span id="time">-</span><br>
  <b>Presence:</b> <span id="presence">-</span><br>
  <b>Plaque:</b> <span id="plaque">-</span><br>
  <b>Config:</b> <span id="config">-</span><br>
  <b>Loxone:</b> <span id="loxone">-</span>
</div>
<div class="card" id="actions"><b>Action log:</b><br>(none)</div>
<hr>
<form onsubmit="loadConfig(event)">
  Config folder: <input id="cfolder" placeholder="/home/steam/steam_prop_vision/configs/enigme1">
  <button type="submit">Load</button>
</form>
<script>
let prev = {};
function refresh() {
  fetch('/api/status')
    .then(r => r.json())
    .then(s => {
      if (s.fsm !== prev.fsm || s.t !== prev.t ||
          s.presence !== prev.presence || s.plaque !== prev.plaque ||
          s.presence_score !== prev.presence_score) {
        document.getElementById('fsm').textContent      = s.fsm;
        document.getElementById('time').textContent     = s.t + 's';
        document.getElementById('presence').textContent = s.presence + ' (' + s.presence_score + ')';
        document.getElementById('plaque').textContent   = (s.plaque || 'none') + ' (' + s.plaque_score + ')';
        document.getElementById('config').textContent   = s.config_folder || '(none)';
        document.getElementById('loxone').textContent   = (s.loxone_enabled ? '\u2713 ' : '\u2717 ') + s.loxone_ip + ':' + s.loxone_port;
      }
      if (JSON.stringify(s.action_log) !== JSON.stringify(prev.action_log)) {
        document.getElementById('actions').innerHTML =
          '<b>Action log:</b><br>' +
          (s.action_log.length ? s.action_log.join('<br>') : '(none)');
      }
      prev = s;
    });
}
setInterval(refresh, 1000);
refresh();
function loadConfig(e) {
  e.preventDefault();
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({folder: document.getElementById('cfolder').value})
  }).then(r => r.json()).then(d => alert(JSON.stringify(d)));
}
</script>
</body></html>"""

@app.route('/monitor')
def monitor():
    """Sert le dashboard de monitoring complet."""
    return send_file(_DASHBOARD, mimetype='text/html')

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def api_status():
    with _lock:
        return jsonify(_status)

@app.route('/api/loxone', methods=['POST'])
def api_loxone():
    """Envoie manuellement un message UDP Loxone (test / debug).
    Body JSON : {"msg": "PLAQUE_BOIS", "value": 0.95}  (value optionnel)
    """
    data  = request.json or {}
    msg   = str(data.get('msg', '')).strip()
    value = data.get('value', None)
    if not msg:
        return jsonify({"error": "msg required"}), 400
    if value is not None:
        sent = lox_send_value(msg, float(value))
    else:
        sent = lox_send(msg, force=True)
    return jsonify({"ok": sent, "msg": msg, "target": f"{LOXONE_IP}:{LOXONE_PORT}"})

@app.route('/api/config', methods=['POST'])
def api_config():
    global _detectors
    folder = (request.form.get('folder') or
              (request.json or {}).get('folder', '')).strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "folder not found"}), 400
    try:
        loaded = load_config_folder(folder)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    rules.apply_config(loaded.data)
    plaques_folder = get_plaques_folder(folder)
    loaded_ids = []
    if os.path.isdir(plaques_folder):
        loaded_ids = rules.plaque.load_from_folder(plaques_folder)
    ok, msg = router.load_rules(folder)
    try:
        from core.detectors import build_detectors
        _detectors = build_detectors(loaded.data)
    except Exception:
        _detectors = []
    with _lock:
        _status["config_folder"] = folder
    return jsonify({
        "plaques": loaded_ids,
        "rules": msg,
        "detectors": [type(d).__name__ for d in _detectors],
    })

@app.route('/api/inject', methods=['POST'])
def api_inject():
    data  = request.json or {}
    label = str(data.get('label', '')).strip()
    conf  = float(data.get('conf', 0.9))
    if not label:
        return jsonify({"error": "label required"}), 400
    engine.inject_detection(label, conf)
    return jsonify({"ok": True, "label": label, "conf": conf})

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',       default='',          help='Config folder to load at startup')
    parser.add_argument('--port',         default=FLASK_PORT,  type=int)
    parser.add_argument('--loxone-ip',    default=LOXONE_IP,   help='IP du Miniserver Loxone')
    parser.add_argument('--loxone-port',  default=LOXONE_PORT, type=int, help='Port UDP Loxone')
    parser.add_argument('--no-loxone',    action='store_true', help="Désactiver l'envoi UDP Loxone")
    args = parser.parse_args()

    LOXONE_IP      = args.loxone_ip
    LOXONE_PORT    = args.loxone_port
    LOXONE_ENABLED = not args.no_loxone
    _status.update({"loxone_ip": LOXONE_IP, "loxone_port": LOXONE_PORT, "loxone_enabled": LOXONE_ENABLED})

    cam = init_camera()

    if args.config and os.path.isdir(args.config):
        try:
            loaded = load_config_folder(args.config)
            rules.apply_config(loaded.data)
            pf = get_plaques_folder(args.config)
            if os.path.isdir(pf):
                rules.plaque.load_from_folder(pf)
            router.load_rules(args.config)
            _status["config_folder"] = args.config
            print(f"[config] Loaded: {args.config}")
        except Exception as e:
            print(f"[config] Error: {e}")

    t = threading.Thread(target=pipeline_loop, args=(cam,), daemon=True)
    t.start()

    lox_status = f"{LOXONE_IP}:{LOXONE_PORT}" if LOXONE_ENABLED else "DISABLED"
    print(f"[flask]  Listening on http://0.0.0.0:{args.port}")
    print(f"[flask]  Monitor:    http://0.0.0.0:{args.port}/monitor")
    print(f"[loxone] Target:     {lox_status}")
    app.run(host='0.0.0.0', port=args.port, threaded=True)
