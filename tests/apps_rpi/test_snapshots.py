import time

import numpy as np

from apps.rpi.snapshots import SnapshotWriter

FRAME = np.zeros((20, 30, 3), dtype=np.uint8)


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_disabled_by_default():
    assert SnapshotWriter.from_config({}) is None
    assert SnapshotWriter.from_config({"enable_snapshots": False}) is None


def test_from_config_reads_values(tmp_path):
    w = SnapshotWriter.from_config(
        {
            "enable_snapshots": True,
            "snapshot_dir": str(tmp_path),
            "snapshot_max_files": 7,
            "snapshot_min_interval_s": 2,
        }
    )
    assert w.directory == tmp_path and w.max_files == 7 and w.min_interval_s == 2


def test_min_interval_rate_limits(tmp_path):
    w = SnapshotWriter(str(tmp_path), min_interval_s=5, queue_size=5)
    assert w.submit(FRAME, "a", 0.5, now=100.0)
    assert not w.submit(FRAME, "a", 0.5, now=102.0)
    assert w.submit(FRAME, "a", 0.5, now=106.0)


def test_full_queue_drops_without_blocking(tmp_path):
    w = SnapshotWriter(str(tmp_path), min_interval_s=0, queue_size=1)
    assert w.submit(FRAME, "a", 0.5, now=1.0)
    assert not w.submit(FRAME, "a", 0.5, now=2.0)  # thread non démarré
    assert w.dropped == 1


def test_writes_jpeg_in_thread(tmp_path):
    w = SnapshotWriter(str(tmp_path / "snaps"), min_interval_s=0)
    w.start()
    try:
        assert w.submit(FRAME, "plate/bois", 0.42)
        assert _wait(lambda: w.written == 1)
    finally:
        w.stop()
    files = list((tmp_path / "snaps").glob("*.jpg"))
    assert len(files) == 1
    assert "plate_bois" in files[0].name and "0.42" in files[0].name
    assert not list((tmp_path / "snaps").glob("*.tmp"))


def test_rotation_keeps_newest(tmp_path):
    w = SnapshotWriter(str(tmp_path), max_files=3, min_interval_s=0)
    for i in range(6):
        w._write(FRAME, "c", 0.5, 1_700_000_000 + i)
    names = sorted(p.name for p in tmp_path.glob("*.jpg"))
    assert len(names) == 3
    newest = time.strftime("%Y%m%d_%H%M%S", time.localtime(1_700_000_005))
    assert names[-1].startswith(newest)


def test_submit_copies_frame(tmp_path):
    w = SnapshotWriter(str(tmp_path), min_interval_s=0)
    f = FRAME.copy()
    w.submit(f, "c", 0.5, now=1.0)
    f[:] = 255
    queued = w._queue.get_nowait()[0]
    assert queued.max() == 0


def test_l1_disabled_by_default_and_samples_when_enabled(tmp_path):
    w = SnapshotWriter(str(tmp_path), queue_size=5)
    assert not w.submit(FRAME, "none", 0.0, now=1.0, kind="L1")
    w = SnapshotWriter(str(tmp_path), queue_size=5, l1_interval_s=30)
    assert w.submit(FRAME, "none", 0.0, now=1.0, kind="L1")
    assert not w.submit(FRAME, "none", 0.0, now=10.0, kind="L1")
    assert w.submit(FRAME, "none", 0.0, now=40.0, kind="L1")


def test_kinds_have_independent_rate_limits(tmp_path):
    w = SnapshotWriter(str(tmp_path), min_interval_s=5, queue_size=5)
    assert w.submit(FRAME, "a", 0.5, now=1.0, kind="ok")
    assert w.submit(FRAME, "a", 0.1, now=1.5, kind="L3")
    assert not w.submit(FRAME, "a", 0.1, now=2.0, kind="L3")


def test_reject_burst_never_evicts_validated(tmp_path):
    w = SnapshotWriter(str(tmp_path), max_files=2, reject_max_files=2)
    w._write(FRAME, "v", 0.9, 1_700_000_000, kind="ok")
    for i in range(5):
        w._write(FRAME, "v", 0.1, 1_700_000_010 + i, kind="L3")
    assert len(list(tmp_path.glob("*_ok_*.jpg"))) == 1
    assert len(list(tmp_path.glob("*_L3_*.jpg"))) == 2
