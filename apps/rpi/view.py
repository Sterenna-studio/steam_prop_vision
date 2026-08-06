"""
apps/rpi/view.py
Page /view (statut live + flux MJPEG) et relais vers le WebSocket monitor.
Aucune dépendance caméra — juste du HTTP/JPEG encoding sur des frames déjà
capturées par l'appelant.
"""

from __future__ import annotations
import json
import logging
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2

from monitor.ws_bridge import push_event as _push_event_raw

log = logging.getLogger("steam")

# ── View status (partagé pipeline → HTTP) ─────────────────────────
_view_status: dict = {
    "fsm": "IDLE",
    "card_id": None,
    "card_label": None,
    "hold_pct": 0,
}
_view_lock = threading.Lock()


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


# ── MJPEG stream (optionnel, thread daemon) ────────────────────────
_stream_frame: bytes | None = None
_stream_lock = threading.Lock()
_stream_last_update: float = 0.0


def update_stream_frame(frame, fps_limit: float = 20.0) -> None:
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


def start_mjpeg_server(port: int = 5050) -> None:
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
#fps-d{color:#555;font-variant-numeric:tabular-nums}
#ws-d{margin-left:auto;font-size:10px;color:#444}
#ws-d.ok{color:#4caf50}
#ws-d.err{color:#e53935}
#score{position:absolute;top:10px;left:10px;background:rgba(0,0,0,.55);padding:4px 10px;border-radius:4px;font-size:12px;color:#666;letter-spacing:.03em;font-variant-numeric:tabular-nums}
#score.hit{color:#00e5cc}
#history{position:absolute;top:10px;right:10px;background:rgba(0,0,0,.55);border-radius:4px;padding:6px 10px;font-size:11px;max-width:190px}
#history .h-title{color:#555;font-size:9px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}
#history .h-item{display:flex;justify-content:space-between;gap:10px;color:#bbb;padding:2px 0}
#history .h-time{color:#555;font-size:10px;font-variant-numeric:tabular-nums}
</style>
</head>
<body>
<div id="wrap">
  <img id="stream" src="/stream" alt="">
  <div id="score">score: \xe2\x80\x94</div>
  <div id="history">
    <div class="h-title">Historique</div>
    <div id="history-list"></div>
  </div>
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
  <span id="fps-d">\xe2\x80\x94 fps</span>
  <span id="ws-d">&#9679; ws\xe2\x80\xa6</span>
</div>
<script>
const $=id=>document.getElementById(id);
const fsmEl=$('fsm-b'),cardEl=$('card-d'),wsEl=$('ws-d'),fpsEl=$('fps-d');
const holdEl=$('hold'),holdFill=$('hold-fill'),holdTxt=$('hold-txt');
const sbEl=$('standby'),sbName=$('sb-name');
const readyEl=$('ready'),readyTxt=$('ready-txt');
const mismatchEl=$('mismatch'),mismatchSub=$('mismatch-sub');
const scoreEl=$('score'),historyListEl=$('history-list');
const history=[];

function flash(el,ms){
  el.style.display='flex';
  clearTimeout(el._t);
  el._t=setTimeout(()=>{el.style.display='none';},ms||4000);
}
function fsm(s){
  fsmEl.textContent=s;
  fsmEl.className='badge '+(s==='STANDBY'?'standby':'idle');
}
function pad2(n){return String(n).padStart(2,'0');}
function nowHMS(){
  const d=new Date();
  return pad2(d.getHours())+':'+pad2(d.getMinutes())+':'+pad2(d.getSeconds());
}
function pushHistory(label){
  history.unshift({label:label,time:nowHMS()});
  history.length=Math.min(history.length,6);
  historyListEl.innerHTML=history.map(h=>
    '<div class="h-item"><span>'+h.label+'</span><span class="h-time">'+h.time+'</span></div>'
  ).join('');
}
function handle(ev){
  if(ev.type==='state'){
    fsm(ev.state);
    if(ev.state==='STANDBY'){sbEl.style.display='flex';holdEl.style.display='none';}
    else{sbEl.style.display='none';if(ev.state==='IDLE'){holdEl.style.display='none';cardEl.textContent='\xe2\x80\x94';}}
  }else if(ev.type==='card_detected'){
    cardEl.textContent=ev.label;sbName.textContent=ev.label;
    pushHistory(ev.label);
  }else if(ev.type==='fps'){
    fpsEl.textContent=ev.value.toFixed(1)+' fps';
  }else if(ev.type==='score'){
    if(ev.card_id){
      scoreEl.textContent=ev.card_id.replace('plate_','')+': '+ev.score.toFixed(3);
      scoreEl.className='hit';
    }else if(ev.score>0){
      scoreEl.textContent='score: '+ev.score.toFixed(3);
      scoreEl.className='';
    }else{
      scoreEl.textContent='score: \xe2\x80\x94';
      scoreEl.className='';
    }
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
  ws.onopen=()=>{wsEl.textContent='\xe2\x97\x8f connect\xc3\xa9';wsEl.className='ok';};
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
