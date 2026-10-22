import numpy as np

from apps.rpi.motion_gate import MotionGate


def _still():
    return np.full((720, 1280, 3), 90, dtype=np.uint8)


def _moved():
    f = _still()
    f[200:500, 400:800] = 220  # grosse zone qui change (carte / main)
    return f


def test_disabled_by_default():
    assert MotionGate.from_config({}) is None
    assert MotionGate.from_config({"enable_motion_gate": True}) is not None


def test_first_frame_is_always_processed():
    g = MotionGate()
    assert g.should_process(_still(), now=100.0)


def test_static_scene_is_skipped_after_linger_with_idle_checks():
    g = MotionGate(linger_s=2.0, idle_interval_s=1.0)
    t = 100.0
    assert g.should_process(_still(), t)
    results = []
    # 10 s de scène figée à 10 fps
    for i in range(1, 101):
        results.append(g.should_process(_still(), t + i * 0.1))
    # frames de contrôle : environ 1 par seconde, jamais 100 %
    assert 5 <= sum(results) <= 15
    assert g.skip_ratio > 0.8


def test_motion_opens_the_gate_and_lingers():
    g = MotionGate(linger_s=2.0, idle_interval_s=100.0)
    g.should_process(_still(), 0.0)
    for i in range(1, 6):  # scène figée : tout est ignoré
        assert not g.should_process(_still(), 10.0 + i * 0.1)
    assert g.should_process(_moved(), 11.0)  # mouvement -> passe
    assert g.should_process(_moved(), 12.5)  # linger (1,5 s <= 2 s)
    assert not g.should_process(_moved(), 14.0)  # linger expiré, plus de changement


def test_force_bypasses_the_gate():
    g = MotionGate(idle_interval_s=100.0)
    g.should_process(_still(), 0.0)
    assert not g.should_process(_still(), 10.0)
    assert g.should_process(_still(), 10.1, force=True)


def test_small_noise_does_not_count_as_motion():
    g = MotionGate(linger_s=0.0, idle_interval_s=100.0)
    g.should_process(_still(), 0.0)
    noisy = _still() + np.uint8(3)  # bruit capteur, sous pixel_delta
    assert not g.should_process(noisy, 10.0)


def test_grayscale_frames_supported():
    g = MotionGate()
    gray = np.zeros((72, 128), dtype=np.uint8)
    assert g.should_process(gray, 0.0)
