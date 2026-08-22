"""
monitor/rule_api.py
Serveur FastAPI sur :8890
  GET  /           → GUI rule editor (HTML)
  GET  /rules      → retourne config/rules.yaml en JSON
  POST /rules      → sauvegarde les règles + reload auto
  POST /reload     → force reload du RuleEngine en cours
  GET  /status     → état courant du pipeline
  GET  /assets     → liste des fichiers assets (audio/img/video)
  GET  /plates     → templates actifs + état de chargement runtime
  POST/DELETE      → ajout ou archivage réversible de templates
  GET  /logs/files → historique local rotatif consultable
  POST /test_card  → injecte un event card_detected sur le WS
  POST /test_udp   → envoie un paquet UDP de test
  POST /control/x  → stop, retour au scan ou reset runtime

Lancer: python monitor/rule_api.py
Accéder depuis le réseau: http://<ip_pi>:8890
"""

from __future__ import annotations
import base64
import re
import sys
import time
import threading
from pathlib import Path

_HERE = Path(__file__).parent
_ROOT = _HERE.parent
RULES_PATH = _ROOT / "config" / "rules.yaml"
ASSETS_PATH = _ROOT / "assets"
PLATES_PATH = _ROOT / "PLATEST"
PLATE_TRASH_PATH = _ROOT / ".runtime" / "plate_trash"
LOGS_PATH = _ROOT / "logs"

# Lancé via `python monitor/rule_api.py` (ou importé depuis apps/rpi/main.py,
# déjà sur le path dans ce cas) : sans cette ligne, "from steamcore..." plus
# bas échoue en ModuleNotFoundError si le module est démarré seul.
sys.path.insert(0, str(_ROOT))

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    import yaml

    _OK = True
except ImportError:
    _OK = False
    print("[rule_api] WARN: pip install fastapi uvicorn pyyaml")

_engine_ref = None  # injecté depuis main.py
_controls_ref = None  # injecté depuis main.py
_plate_lock = threading.Lock()

from apps.rpi.plates import PlateConflictError, PlateError, PlateStore  # noqa: E402
from apps.rpi.runtime_status import runtime_status  # noqa: E402

_plate_store = PlateStore(PLATES_PATH, PLATE_TRASH_PATH)

app = FastAPI(title="S.T.E.A.M Rule Editor") if _OK else None

if _OK:
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    # ── UI ────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def gui():
        html_path = _HERE / "rule_editor" / "index.html"
        return html_path.read_text(encoding="utf-8")

    @app.get("/monitor", response_class=HTMLResponse)
    def monitor_dashboard():
        """Dashboard admin WebSocket — accessible sur http://<ip>:8890/monitor"""
        html_path = _HERE / "index.html"
        return html_path.read_text(encoding="utf-8")

    @app.get("/plates-ui", response_class=HTMLResponse)
    def plates_dashboard():
        return (_HERE / "plates.html").read_text(encoding="utf-8")

    @app.get("/logs-ui", response_class=HTMLResponse)
    def logs_dashboard():
        return (_HERE / "logs.html").read_text(encoding="utf-8")

    # ── Rules CRUD ────────────────────────────────────────────────────
    @app.get("/rules")
    def get_rules():
        if not RULES_PATH.exists():
            return JSONResponse({"error": "rules.yaml introuvable"}, status_code=404)
        with open(RULES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return JSONResponse(data)

    @app.post("/rules")
    async def save_rules(request: Request):
        from steamcore.rules import RulesSchemaError, validate_rules_schema

        body = await request.json()
        try:
            validate_rules_schema(body)
        except RulesSchemaError as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=400
            )
        with open(RULES_PATH, "w", encoding="utf-8") as f:
            yaml.dump(body, f, allow_unicode=True, default_flow_style=False)
        if _engine_ref:
            _engine_ref.reload()
        return JSONResponse({"status": "ok"})

    @app.post("/reload")
    def reload_rules():
        if _engine_ref:
            _engine_ref.reload()
            return JSONResponse(
                {"status": "reloaded", "rules": len(_engine_ref._rules)}
            )
        return JSONResponse({"status": "no engine attached"})

    # ── Status ────────────────────────────────────────────────────────
    @app.get("/status")
    def get_status():
        rules_count = len(_engine_ref._rules) if _engine_ref else None
        return JSONResponse(
            {
                "status": "running",
                "engine_attached": _engine_ref is not None,
                "controls_attached": _controls_ref is not None,
                "rules": rules_count,
                "runtime": runtime_status.snapshot(),
                "timestamp": time.time(),
            }
        )

    # ── Assets ───────────────────────────────────────────────────────
    @app.get("/assets")
    def list_assets():
        result = {}
        for cat in ("audio", "img", "video"):
            folder = ASSETS_PATH / cat
            result[cat] = (
                [
                    str(p.relative_to(ASSETS_PATH / cat))
                    for p in folder.rglob("*")
                    if p.is_file() and not p.name.startswith(".")
                ]
                if folder.exists()
                else []
            )
        return JSONResponse(result)

    # ── Logs ────────────────────────────────────────────────────────
    @app.get("/logs/files")
    def list_log_files():
        files = []
        if LOGS_PATH.exists():
            for path in LOGS_PATH.glob("steam_vision.log*"):
                if path.is_file() and re.fullmatch(
                    r"steam_vision\.log(?:\.\d+)?", path.name
                ):
                    stat = path.stat()
                    files.append(
                        {
                            "name": path.name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        }
                    )
        files.sort(key=lambda item: item["modified"], reverse=True)
        return JSONResponse({"files": files, "retention": "4 fichiers × 2 Mio"})

    @app.get("/logs/file/{filename}")
    def read_log_file(filename: str, limit: int = 1000):
        if not re.fullmatch(r"steam_vision\.log(?:\.\d+)?", filename):
            return JSONResponse({"error": "nom de log invalide"}, status_code=400)
        path = (LOGS_PATH / filename).resolve()
        if path.parent != LOGS_PATH.resolve() or not path.is_file():
            return JSONResponse({"error": "log introuvable"}, status_code=404)
        limit = min(max(limit, 50), 5000)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return JSONResponse({"name": filename, "lines": lines[-limit:]})

    # ── Plates ──────────────────────────────────────────────────────
    def _request_template_reload() -> bool:
        if _controls_ref is None:
            return False
        _controls_ref.execute("reload_templates")
        return True

    @app.get("/plates")
    def list_plates():
        selected = set(runtime_status.snapshot()["template_ids"])
        plates = _plate_store.list_active()
        for plate in plates:
            plate_id = plate["plate_id"]
            rule = _engine_ref._rules.get(plate_id) if _engine_ref else None
            plate["selected"] = plate_id in selected
            plate["rule_configured"] = rule is not None
            plate["rule_enabled"] = bool(rule and rule.enabled)
            plate["action_count"] = len(rule.actions) if rule else 0
        return JSONResponse(
            {
                "plates": plates,
                "archived": _plate_store.list_archived(),
                "runtime_count": len(selected),
            }
        )

    @app.get("/plates/{plate_id}/images/{filename}")
    def plate_image(plate_id: str, filename: str):
        try:
            return FileResponse(_plate_store.image_path(plate_id, filename))
        except PlateError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/plates/{plate_id}/images")
    async def add_plate_images(plate_id: str, request: Request):
        try:
            body = await request.json()
            encoded_files = body.get("files", [])
            if not isinstance(encoded_files, list) or not all(
                isinstance(item, dict) for item in encoded_files
            ):
                raise PlateError("liste de fichiers invalide")
            files = [
                (
                    item.get("name", ""),
                    base64.b64decode(item.get("data", ""), validate=True),
                )
                for item in encoded_files
            ]
            with _plate_lock:
                result = _plate_store.add_images(plate_id, files)
                result["reload_requested"] = _request_template_reload()
            return JSONResponse({"status": "ok", **result})
        except PlateConflictError as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=409
            )
        except (PlateError, ValueError, TypeError) as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=400
            )

    @app.delete("/plates/{plate_id}")
    def archive_plate(plate_id: str):
        try:
            with _plate_lock:
                result = _plate_store.archive(plate_id)
                result["reload_requested"] = _request_template_reload()
            return JSONResponse({"status": "archived", **result})
        except PlateError as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=400
            )

    @app.post("/plates/trash/{archive_id}/restore")
    def restore_plate(archive_id: str):
        try:
            with _plate_lock:
                result = _plate_store.restore(archive_id)
                result["reload_requested"] = _request_template_reload()
            return JSONResponse({"status": "restored", **result})
        except PlateConflictError as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=409
            )
        except PlateError as exc:
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=400
            )

    # ── Test triggers ────────────────────────────────────────────────
    @app.post("/test_card")
    async def test_card(request: Request):
        """Injecte une fausse détection de carte sur le WebSocket monitor."""
        body = await request.json()
        card_id = body.get("card_id", "plate_vampire")
        label = card_id.replace("plate_", "").replace("_", " ").capitalize()
        from monitor.ws_bridge import push_event

        push_event(
            {
                "type": "card_detected",
                "card_id": card_id,
                "label": label,
                "score": 0.99,
            }
        )
        return JSONResponse({"status": "injected", "card_id": card_id})

    @app.post("/test_udp")
    async def test_udp(request: Request):
        """Envoie un paquet UDP de test vers Loxone (ou toute cible)."""
        body = await request.json()
        msg = body.get("msg", "STEAM_TEST")
        ip = body.get("ip", "192.168.1.50")
        port = body.get("port", 7777)
        try:
            from steamcore.udp import send_event

            send_event(msg, ip, port)
            return JSONResponse({"status": "sent", "msg": msg, "ip": ip, "port": port})
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    # ── Runtime controls ─────────────────────────────────────────────
    @app.post("/control/{command}")
    def admin_control(command: str):
        """Exécute une commande réelle sur le pipeline attaché."""
        if _controls_ref is None:
            return JSONResponse(
                {"status": "error", "detail": "contrôles runtime non attachés"},
                status_code=503,
            )
        try:
            return JSONResponse(_controls_ref.execute(command))
        except Exception as exc:
            from apps.rpi.admin_controls import (
                VALID_ADMIN_COMMANDS,
                UnknownAdminCommand,
            )

            if isinstance(exc, UnknownAdminCommand):
                return JSONResponse(
                    {
                        "status": "error",
                        "detail": str(exc),
                        "commands": list(VALID_ADMIN_COMMANDS),
                    },
                    status_code=400,
                )
            return JSONResponse(
                {"status": "error", "detail": str(exc)}, status_code=500
            )


def start_in_thread(
    port: int = 8890, engine=None, controls=None
) -> threading.Thread | None:
    global _engine_ref, _controls_ref
    _engine_ref = engine
    _controls_ref = controls
    if not _OK:
        print("[rule_api] GUI désactivé (dépendances manquantes)")
        return None

    def run():
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

    t = threading.Thread(target=run, daemon=True, name="rule-api")
    t.start()
    print(f"[rule_api] Dashboard    →  http://0.0.0.0:{port}/monitor")
    print(f"[rule_api] Rule editor  →  http://0.0.0.0:{port}/")
    return t


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8890, reload=False)
