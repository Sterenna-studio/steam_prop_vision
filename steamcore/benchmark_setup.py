"""État pur du futur parcours admin d'initialisation/benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import time


class SetupStage(str, Enum):
    WELCOME = "welcome"
    CAMERA_CHECK = "camera_check"
    AUTOFOCUS = "autofocus"
    EXPOSURE_COLOR = "exposure_color_stabilization"
    IMAGE_QUALITY = "image_quality_check"
    CAPTURE_CORPUS = "capture_corpus"
    TEST_ALGORITHMS = "test_algorithms"
    THRESHOLD_CALIBRATION = "threshold_calibration"
    RELIABILITY_REPORT = "reliability_report"
    SAVE_PROFILE = "save_setup_profile"
    COMPLETE = "complete"


_STAGES = list(SetupStage)


@dataclass
class BenchmarkSetupState:
    run_id: str
    stage: SetupStage = SetupStage.WELCOME
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_stages: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        values = asdict(self)
        values["stage"] = self.stage.value
        return values


class BenchmarkSetupWorkflow:
    """Machine à états sérialisable; aucune action caméra/service implicite."""

    def __init__(self, run_id: str):
        self.state = BenchmarkSetupState(run_id=run_id)

    def complete_stage(
        self, stage: SetupStage, diagnostics: dict | None = None
    ) -> SetupStage:
        if self.state.stage != stage:
            raise ValueError(
                f"Étape attendue: {self.state.stage.value}, reçue: {stage.value}"
            )
        if diagnostics:
            self.state.diagnostics[stage.value] = diagnostics
        self.state.completed_stages.append(stage.value)
        index = _STAGES.index(stage)
        self.state.stage = _STAGES[min(index + 1, len(_STAGES) - 1)]
        self.state.updated_at = time.time()
        self.state.error = None
        return self.state.stage

    def fail(self, message: str) -> None:
        self.state.error = message
        self.state.updated_at = time.time()

    def status(self) -> dict:
        return self.state.to_dict()
