"""
apps/rpi/snapshot_view.py
Page /snapshots : galerie des snapshots écrits par SnapshotWriter.

Logique pure (pas de caméra, pas de serveur) : le handler HTTP de view.py
n'a qu'à déléguer ici. Lecture seule : aucune route ne modifie ni ne supprime
quoi que ce soit, et seuls des noms de fichiers conformes au format produit
par SnapshotWriter sont servis (pas de traversée de répertoire possible).
"""

from __future__ import annotations
import html
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

KINDS = ("ok", "L1", "L2", "L3")
_NAME = re.compile(
    r"^(?P<d>\d{8})_(?P<t>\d{6})_(?P<ms>\d{3})_(?P<kind>ok|L1|L2|L3)_"
    r"(?P<card>[A-Za-z0-9_-]+)_(?P<score>\d+\.\d{2})\.jpg$"
)
_KIND_LABEL = {
    "ok": "validée",
    "L1": "L1 · aucun contour",
    "L2": "L2 · contour sans carte",
    "L3": "L3 · score sous le seuil",
}

_directory: Path | None = None


def set_directory(path: str | Path | None) -> None:
    global _directory
    _directory = Path(path) if path else None


def list_snapshots(directory: Path | None, kind: str | None = None) -> list[dict]:
    """Snapshots les plus récents d'abord. Noms non conformes ignorés."""
    if directory is None or not directory.is_dir():
        return []
    items = []
    for p in directory.glob("*.jpg"):
        m = _NAME.match(p.name)
        if not m or (kind and m["kind"] != kind):
            continue
        items.append(
            {
                "name": p.name,
                "kind": m["kind"],
                "card": m["card"],
                "score": float(m["score"]),
                "time": f"{m['d'][:4]}-{m['d'][4:6]}-{m['d'][6:]} "
                f"{m['t'][:2]}:{m['t'][2:4]}:{m['t'][4:]}",
            }
        )
    items.sort(key=lambda i: i["name"], reverse=True)
    return items


def read_snapshot(directory: Path | None, name: str) -> bytes | None:
    if directory is None or not _NAME.match(name):
        return None
    try:
        return (directory / name).read_bytes()
    except OSError:
        return None


def render_gallery(items: list[dict], kind: str | None, directory: str) -> str:
    counts = {k: 0 for k in KINDS}
    for i in list_snapshots(_directory):
        counts[i["kind"]] += 1
    chips = [
        f'<a class="chip{" on" if not kind else ""}" href="/snapshots">'
        f"tous ({sum(counts.values())})</a>"
    ]
    for k in KINDS:
        on = " on" if kind == k else ""
        chips.append(
            f'<a class="chip k-{k}{on}" href="/snapshots?kind={k}">'
            f"{html.escape(_KIND_LABEL[k])} ({counts[k]})</a>"
        )
    cards = []
    for i in items:
        url = "/snapshots/" + i["name"]
        cards.append(
            f'<a class="card" href="{url}" target="_blank">'
            f'<img loading="lazy" src="{url}" alt="">'
            f'<div class="meta"><span class="badge k-{i["kind"]}">{i["kind"]}</span> '
            f"{html.escape(i['card'])} · <b>{i['score']:.2f}</b>"
            f'<br><span class="t">{i["time"]}</span></div></a>'
        )
    empty = (
        '<p class="empty">Aucun snapshot. Vérifie <code>enable_snapshots</code> '
        "dans features.yaml ; le dossier est vidé au reboot s'il est en RAM.</p>"
        if not cards
        else ""
    )
    return _PAGE.format(
        chips="".join(chips),
        cards="".join(cards),
        empty=empty,
        directory=html.escape(directory),
        now=time.strftime("%H:%M:%S"),
    )


def handle(path: str) -> tuple[int, str, bytes] | None:
    """(status, content-type, body) si `path` est une route snapshots,
    sinon None (le handler appelant continue son routage)."""
    parts = urlsplit(path)
    route = unquote(parts.path)
    if route == "/snapshots":
        kind = (parse_qs(parts.query).get("kind") or [None])[0]
        kind = kind if kind in KINDS else None
        body = render_gallery(
            list_snapshots(_directory, kind), kind, str(_directory or "—")
        )
        return 200, "text/html; charset=utf-8", body.encode()
    if route == "/api/snapshots":
        body = json.dumps(list_snapshots(_directory)).encode()
        return 200, "application/json", body
    if route.startswith("/snapshots/"):
        data = read_snapshot(_directory, route[len("/snapshots/") :])
        if data is None:
            return 404, "text/plain", b"not found"
        return 200, "image/jpeg", data
    return None


_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Snapshots · STEAM Vision</title>
<style>
:root{{--bg:#0f1115;--fg:#e8eaed;--mut:#8b93a1;--card:#181b22;--bd:#2a2f3a;
--ok:#2ea043;--L1:#8b93a1;--L2:#d29922;--L3:#db6d28}}
@media (prefers-color-scheme:light){{:root{{--bg:#f5f6f8;--fg:#1c1f26;
--mut:#5b6472;--card:#fff;--bd:#d8dce3}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:14px system-ui,sans-serif}}
header{{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline}}
h1{{font-size:18px;margin:0}}
.sub{{color:var(--mut);font-size:12px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.chip{{padding:4px 10px;border:1px solid var(--bd);border-radius:999px;
color:var(--fg);text-decoration:none;font-size:13px}}
.chip.on{{background:var(--fg);color:var(--bg)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:8px;
overflow:hidden;color:inherit;text-decoration:none}}
.card img{{width:100%;aspect-ratio:9/16;object-fit:cover;display:block;
background:#000;max-height:420px}}
.meta{{padding:8px 10px;font-size:13px}}
.t{{color:var(--mut);font-size:12px}}
.badge{{display:inline-block;padding:0 6px;border-radius:4px;color:#fff;
font-size:11px;font-weight:600}}
.badge.k-ok{{background:var(--ok)}}.badge.k-L1{{background:var(--L1)}}
.badge.k-L2{{background:var(--L2)}}.badge.k-L3{{background:var(--L3)}}
.empty{{color:var(--mut)}}
a:focus-visible{{outline:2px solid #4c8dff;outline-offset:2px}}
</style></head><body>
<header><h1>Snapshots</h1>
<span class="sub">{directory} · rafraîchi à {now} ·
<a href="/view" style="color:inherit">/view</a></span></header>
<nav class="chips">{chips}</nav>
{empty}<main class="grid">{cards}</main>
<script>setTimeout(()=>location.reload(),15000)</script>
</body></html>
"""
