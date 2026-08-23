from __future__ import annotations

import json

import pytest

from steamcore.recognition.benchmark.repeated import (
    RepeatedBenchmarkOptions,
    RepeatedBenchmarkRunner,
    RepeatedReportContext,
    build_repeated_checkpoint,
    build_repeated_report,
    render_repeated_markdown,
    restore_repeated_checkpoint,
    write_repeated_checkpoint,
    write_repeated_reports,
)
from steamcore.recognition.benchmark.runner import BenchmarkOptions
from steamcore.recognition.benchmark.variants import get_variants
from steamcore.recognition.thresholds import RecognitionThresholds


class _FakeMetrics:
    def __init__(self, variant, homography, value):
        self.variant = variant
        self.homography = homography
        self.value = value

    def grouped_summary(self):
        return [
            {
                "variant": self.variant.code,
                "backend": self.variant.l2_backend,
                "homography_requested": self.homography,
                "samples": 10,
                "recall": self.value,
                "precision": 1.0,
                "false_positive_rate": 0.0,
                "false_negative_rate": 1.0 - self.value,
                "l1_hit_rate": 0.5,
                "l2_success_rate": 0.5,
                "l3_success_rate": self.value,
                "latency_ms_p50": 10.0 + self.value,
                "latency_ms_p95": 20.0 + self.value,
                "cpu_percent_mean": 50.0,
                "fps_mean": 30.0,
                "recall_by_object": {},
                "metrics_by_condition": {},
                "confusion": {},
            }
        ]


class _FakeRunner:
    def __init__(self, metrics):
        self.metrics = metrics

    def run(self):
        return self.metrics


def test_repeated_runner_warms_up_and_replays_every_configuration():
    calls = []
    progress = []
    checkpoints = []

    def factory(variant, homography, options, _thresholds):
        calls.append((variant.code, homography, options.limit))
        value = 0.7 if homography == "magsac" else 0.6
        return _FakeRunner(_FakeMetrics(variant, homography, value))

    runner = RepeatedBenchmarkRunner(
        get_variants("A,B"),
        ["ransac", "magsac"],
        BenchmarkOptions(corpus="corpus", limit=None),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=3, warmup_frames=4, seed=42),
        runner_factory=factory,
    )

    rows = runner.run(
        on_progress=progress.append,
        on_checkpoint=lambda current: checkpoints.append(len(current.run_rows)),
    )

    assert len(rows) == 12
    assert len(calls) == 16
    assert all(limit == 4 for _, _, limit in calls[:4])
    assert len(runner.execution_orders) == 3
    assert all(len(set(order)) == 4 for order in runner.execution_orders)
    assert len(progress) == 24
    assert progress[0]["status"] == "starting"
    assert progress[-1]["completed"] == 12
    assert checkpoints == list(range(1, 13))
    aggregate = runner.aggregate()
    assert len(aggregate) == 4
    magsac = next(
        row
        for row in aggregate
        if row["variant"] == "A" and row["homography_requested"] == "magsac"
    )
    assert magsac["runs"] == 3
    assert magsac["recall"]["mean"] == pytest.approx(0.7)
    assert magsac["recall"]["min"] == magsac["recall"]["max"]


def test_repeated_report_generation(tmp_path):
    def factory(variant, homography, _options, _thresholds):
        return _FakeRunner(_FakeMetrics(variant, homography, 0.75))

    runner = RepeatedBenchmarkRunner(
        get_variants("A"),
        ["ransac"],
        BenchmarkOptions(corpus="corpus"),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=2, warmup_frames=0),
        runner_factory=factory,
    )
    runner.run()
    report = build_repeated_report(
        runner,
        RepeatedReportContext(
            corpus="corpus",
            templates="PLATEST",
            roi_mode="hybrid",
            variants=["A"],
            homographies=["ransac"],
            runs=2,
            warmup_frames=0,
            seed=9,
            top_k=2,
            top2_margin=0.1,
        ),
    )

    markdown = render_repeated_markdown(report)
    assert "ordre des configurations" in markdown
    assert "75.00 %" in markdown
    paths = write_repeated_reports(report, tmp_path, "repeated")
    loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert len(loaded["runs"]) == 2
    assert paths["csv"].read_text(encoding="utf-8").count("\n") == 3


def _context(**overrides):
    values = {
        "corpus": "corpus",
        "templates": "PLATEST",
        "roi_mode": "hybrid",
        "variants": ["A", "B"],
        "homographies": ["ransac", "magsac"],
        "runs": 3,
        "warmup_frames": 4,
        "seed": 42,
        "top_k": 2,
        "top2_margin": 0.1,
    }
    values.update(overrides)
    return RepeatedReportContext(**values)


def test_repeated_runner_resumes_only_missing_configurations():
    def factory(variant, homography, _options, _thresholds):
        return _FakeRunner(_FakeMetrics(variant, homography, 0.7))

    original = RepeatedBenchmarkRunner(
        get_variants("A,B"),
        ["ransac", "magsac"],
        BenchmarkOptions(corpus="corpus"),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=3, warmup_frames=4, seed=42),
        runner_factory=factory,
    )
    original.run()
    partial_rows = original.run_rows[:2]
    calls = []

    def resumed_factory(variant, homography, options, _thresholds):
        calls.append((variant.code, homography, options.limit))
        return _FakeRunner(_FakeMetrics(variant, homography, 0.7))

    resumed = RepeatedBenchmarkRunner(
        get_variants("A,B"),
        ["ransac", "magsac"],
        BenchmarkOptions(corpus="corpus"),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=3, warmup_frames=4, seed=42),
        runner_factory=resumed_factory,
    )
    resumed.restore(partial_rows)
    resumed.run()

    assert len(resumed.run_rows) == 12
    assert len(calls) == 10
    assert all(limit is None for _, _, limit in calls)


def test_checkpoint_is_atomic_and_rejects_incompatible_context(tmp_path):
    runner = RepeatedBenchmarkRunner(
        get_variants("A,B"),
        ["ransac", "magsac"],
        BenchmarkOptions(corpus="corpus"),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=3, warmup_frames=4, seed=42),
        runner_factory=lambda variant, homography, _options, _thresholds: _FakeRunner(
            _FakeMetrics(variant, homography, 0.7)
        ),
    )
    runner.run()
    checkpoint = build_repeated_checkpoint(runner, _context(), status="complete")
    path = write_repeated_checkpoint(checkpoint, tmp_path / "campaign.json")

    assert path.exists()
    assert not (tmp_path / "campaign.json.tmp").exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    restored = RepeatedBenchmarkRunner(
        get_variants("A,B"),
        ["ransac", "magsac"],
        BenchmarkOptions(corpus="corpus"),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=3, warmup_frames=4, seed=42),
        runner_factory=lambda *_args: None,
    )
    restore_repeated_checkpoint(restored, loaded, _context())
    assert len(restored.run_rows) == 12
    with pytest.raises(ValueError, match="incompatible"):
        restore_repeated_checkpoint(restored, loaded, _context(seed=99))


def test_restore_rejects_result_at_wrong_order_position():
    runner = RepeatedBenchmarkRunner(
        get_variants("A,B"),
        ["ransac", "magsac"],
        BenchmarkOptions(corpus="corpus"),
        RecognitionThresholds(default_threshold=0.2),
        RepeatedBenchmarkOptions(runs=1, warmup_frames=0, seed=42),
    )
    wrong = {
        "run_index": 1,
        "order_index": 1,
        "variant": "unknown",
        "homography_requested": "ransac",
    }
    with pytest.raises(ValueError, match="Checkpoint incompatible"):
        runner.restore([wrong])
