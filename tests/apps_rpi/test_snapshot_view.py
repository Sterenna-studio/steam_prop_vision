import json

import numpy as np

from apps.rpi import snapshot_view as sv
from apps.rpi.snapshots import SnapshotWriter

FRAME = np.zeros((10, 10, 3), dtype=np.uint8)


def _fill(tmp_path):
    w = SnapshotWriter(str(tmp_path))
    w._write(FRAME, "plate_vampire", 0.25, 1_700_000_000, kind="ok")
    w._write(FRAME, "none", 0.0, 1_700_000_010, kind="L1")
    w._write(FRAME, "plate_bois", 0.14, 1_700_000_020, kind="L3")
    (tmp_path / "intrus.jpg").write_bytes(b"x")
    sv.set_directory(tmp_path)


def test_list_newest_first_and_ignores_foreign_files(tmp_path):
    _fill(tmp_path)
    items = sv.list_snapshots(tmp_path)
    assert [i["kind"] for i in items] == ["L3", "L1", "ok"]
    assert items[0]["card"] == "plate_bois" and items[0]["score"] == 0.14


def test_filter_by_kind(tmp_path):
    _fill(tmp_path)
    assert [i["kind"] for i in sv.list_snapshots(tmp_path, "ok")] == ["ok"]


def test_missing_directory_is_empty(tmp_path):
    assert sv.list_snapshots(tmp_path / "nope") == []
    assert sv.list_snapshots(None) == []


def test_routes(tmp_path):
    _fill(tmp_path)
    status, ctype, body = sv.handle("/snapshots?kind=L3")
    assert status == 200 and "html" in ctype and b"plate_bois" in body
    assert b"plate_vampire" not in body.split(b'<main class="grid">')[1]
    status, _, body = sv.handle("/api/snapshots")
    assert status == 200 and len(json.loads(body)) == 3
    name = sv.list_snapshots(tmp_path, "ok")[0]["name"]
    status, ctype, body = sv.handle("/snapshots/" + name)
    assert (status, ctype) == (200, "image/jpeg") and body[:2] == b"\xff\xd8"
    assert sv.handle("/view") is None


def test_no_path_traversal(tmp_path):
    _fill(tmp_path)
    (tmp_path.parent / "secret.jpg").write_bytes(b"s")
    for bad in ("../secret.jpg", "..%2Fsecret.jpg", "intrus.jpg", "a/b.jpg"):
        assert sv.handle("/snapshots/" + bad)[0] == 404


def test_unknown_kind_falls_back_to_all(tmp_path):
    _fill(tmp_path)
    _, _, body = sv.handle("/snapshots?kind=<script>")
    assert b"<script>alert" not in body and b"plate_vampire" in body
