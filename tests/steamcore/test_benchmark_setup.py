from __future__ import annotations

import pytest

from steamcore.benchmark_setup import BenchmarkSetupWorkflow, SetupStage


def test_benchmark_setup_workflow_is_ordered_and_serializable():
    workflow = BenchmarkSetupWorkflow("run-1")
    assert workflow.status()["stage"] == "welcome"
    next_stage = workflow.complete_stage(SetupStage.WELCOME, {"brand": "Sterenna"})
    assert next_stage == SetupStage.CAMERA_CHECK
    assert workflow.status()["diagnostics"]["welcome"]["brand"] == "Sterenna"
    with pytest.raises(ValueError):
        workflow.complete_stage(SetupStage.AUTOFOCUS)
    workflow.fail("camera unavailable")
    assert workflow.status()["error"] == "camera unavailable"
