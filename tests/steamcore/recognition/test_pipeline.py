"""
tests/steamcore/recognition/test_pipeline.py
Squelette de tests unitaires pour RecognitionPipeline.
"""

import time
from types import SimpleNamespace

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dummy_frame():
    """Frame noire 480x640 RGB."""
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def pipeline(tmp_path):
    """Pipeline avec répertoire PLATEST vide (pas de cartes chargées)."""
    platest = tmp_path / "PLATEST"
    platest.mkdir()
    from steamcore.recognition.pipeline import RecognitionPipeline

    pipe = RecognitionPipeline(platest_dir=str(platest))
    pipe.start()
    yield pipe
    pipe.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineLifecycle:
    def test_start_stop(self, pipeline):
        """Le pipeline démarre et s'arrête sans exception."""
        assert pipeline._running is True  # start() a été appelé par la fixture
        pipeline.stop()
        assert pipeline._running is False

    def test_process_frame_no_cards_returns_none(self, pipeline, dummy_frame):
        """Sans cartes enregistrées, process_frame retourne None."""
        pipeline._running = True  # re-démarrage manuel pour le test
        result = pipeline.process_frame(dummy_frame)
        pipeline._running = False
        assert result is None

    def test_result_expires_after_ttl(self, pipeline):
        """Un résultat injecté manuellement expire après result_ttl."""
        from steamcore.recognition.pipeline import PipelineResult
        from steamcore.recognition.fast_detector import QuadROI
        import numpy as np

        fake_quad = QuadROI(
            corners=np.array(
                [[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.float32
            ),
            x=0,
            y=0,
            w=100,
            h=100,
            confidence=1.0,
        )
        fake_result = PipelineResult(
            card_id="test_card",
            label="Test",
            score=0.99,
            matches=10,
            roi=fake_quad,
            timestamp=time.time() - 999,  # déjà expiré
        )
        with pipeline._result_lock:
            pipeline._result = fake_result

        # process_frame doit purger le résultat expiré
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        result = pipeline.process_frame(dummy)
        assert result is None


class TestPipelineConcurrency:
    def test_thread_safe_result_access(self, pipeline, dummy_frame):
        """Accès concurrent à _result sans deadlock."""
        import threading

        errors = []

        def reader():
            for _ in range(50):
                try:
                    pipeline.process_frame(dummy_frame)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"Erreurs concurrentes : {errors}"


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _fake_quad():
    from steamcore.recognition.fast_detector import QuadROI

    return QuadROI(
        x=5,
        y=7,
        w=20,
        h=18,
        corners=np.float32([[5, 7], [25, 7], [25, 25], [5, 25]]),
        confidence=0.9,
    )


def test_background_pipeline_propagates_l2_hint_and_l1_roi(tmp_path):
    from steamcore.recognition.pipeline import RecognitionPipeline

    platest = tmp_path / "PLATEST"
    platest.mkdir()
    pipe = RecognitionPipeline(
        platest_dir=str(platest), bg_interval=0.0, result_ttl=10.0
    )
    quad = _fake_quad()
    observed = {}

    pipe._fast.detect = lambda _frame: quad

    def detect(roi):
        observed["roi_shape"] = roi.shape
        return SimpleNamespace(warped=roi, card_id="plate_x")

    def recognize(warped, hint_id=None):
        observed["hint_id"] = hint_id
        observed["warped_shape"] = warped.shape
        return SimpleNamespace(card_id="plate_x", label="X", score=0.8, matches=17)

    pipe._detector.detect = detect
    pipe._recognizer.recognize = recognize
    pipe.start()
    try:
        frame = np.full((60, 80, 3), 127, dtype=np.uint8)
        assert pipe.process_frame(frame) is None
        assert _wait_until(lambda: pipe.last_result is not None)
        result = pipe.process_frame(frame)
        assert result is not None
        assert result.card_id == "plate_x"
        assert result.roi is quad
        assert observed == {
            "roi_shape": (18, 20, 3),
            "hint_id": "plate_x",
            "warped_shape": (18, 20, 3),
        }
    finally:
        pipe.stop()


def test_background_pipeline_survives_one_detector_error(tmp_path):
    from steamcore.recognition.pipeline import RecognitionPipeline

    platest = tmp_path / "PLATEST"
    platest.mkdir()
    pipe = RecognitionPipeline(platest_dir=str(platest), bg_interval=0.0)
    quad = _fake_quad()
    calls = {"count": 0}
    pipe._fast.detect = lambda _frame: quad

    def detect(roi):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("échec synthétique")
        return SimpleNamespace(warped=roi, card_id="plate_x")

    pipe._detector.detect = detect
    pipe._recognizer.recognize = lambda _warped, hint_id=None: SimpleNamespace(
        card_id=hint_id, label="X", score=0.7, matches=12
    )
    pipe.start()
    try:
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        pipe.process_frame(frame)
        assert _wait_until(lambda: calls["count"] == 1)
        pipe.process_frame(frame)
        assert _wait_until(lambda: pipe.last_result is not None)
        assert pipe.last_result.card_id == "plate_x"
        assert pipe._thread.is_alive()
    finally:
        pipe.stop()


def test_process_frame_never_blocks_when_background_queue_is_full(tmp_path):
    from steamcore.recognition.pipeline import RecognitionPipeline

    platest = tmp_path / "PLATEST"
    platest.mkdir()
    pipe = RecognitionPipeline(platest_dir=str(platest))
    pipe._fast.detect = lambda _frame: _fake_quad()
    frame = np.zeros((60, 80, 3), dtype=np.uint8)

    for _ in range(10):
        assert pipe.process_frame(frame) is None

    assert pipe._queue.qsize() == 2
