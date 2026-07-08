"""
tests/steamcore/recognition/test_pipeline.py
Squelette de tests unitaires pour RecognitionPipeline.
"""
import time
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
        assert pipeline._running is False  # stop() a été appelé par la fixture

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
            corners=np.array([[0,0],[100,0],[100,100],[0,100]], dtype=np.float32),
            x=0, y=0, w=100, h=100
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
