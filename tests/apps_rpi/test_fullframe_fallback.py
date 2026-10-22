import numpy as np

from apps.rpi.fullframe_fallback import FullFrameFallback
from apps.rpi.motion_gate import MotionGate


def test_disabled_by_default():
    assert FullFrameFallback.from_config({}) is None
    assert FullFrameFallback.from_config({"enable_fullframe_fallback": True})


def test_waits_for_consecutive_l1_misses():
    f = FullFrameFallback(min_l1_misses=3, interval_s=0.0)
    assert not f.should_try(1.0)
    assert not f.should_try(1.1)
    assert f.should_try(1.2)


def test_l1_hit_resets_the_miss_counter():
    f = FullFrameFallback(min_l1_misses=3, interval_s=0.0)
    f.should_try(1.0)
    f.should_try(1.1)
    f.note_l1_hit()
    assert not f.should_try(1.2)
    assert not f.should_try(1.3)
    assert f.should_try(1.4)


def test_attempts_are_rate_limited():
    f = FullFrameFallback(min_l1_misses=1, interval_s=0.7)
    assert f.should_try(10.0)
    assert not f.should_try(10.3)
    assert not f.should_try(10.6)
    assert f.should_try(10.8)
    assert f.attempts == 2


def test_no_attempt_when_scene_is_static():
    f = FullFrameFallback(min_l1_misses=1, interval_s=0.0)
    assert not f.should_try(10.0, motion_ok=False)
    assert f.attempts == 0
    assert f.should_try(10.1, motion_ok=True)


def test_stricter_threshold_for_fallback_results():
    f = FullFrameFallback(score_margin=0.05)
    assert not f.accepts(0.22, 0.20)
    assert f.accepts(0.26, 0.20)


def test_motion_gate_recently_moved_window():
    g = MotionGate()
    still = np.full((72, 128, 3), 90, dtype=np.uint8)
    moved = still.copy()
    moved[10:50, 20:90] = 230
    g.should_process(still, 0.0)
    assert not g.recently_moved(0.1, 5.0)
    g.should_process(moved, 1.0)
    assert g.recently_moved(3.0, 5.0)
    assert not g.recently_moved(7.0, 5.0)


def test_between_attempts_covers_two_intervals_then_expires():
    f = FullFrameFallback(min_l1_misses=1, interval_s=0.7)
    assert not f.between_attempts(5.0)  # jamais tenté
    assert f.should_try(10.0)
    assert f.between_attempts(10.5)
    assert f.between_attempts(11.3)
    assert not f.between_attempts(11.5)  # périmé : les frames recomptent comme ratés
