from __future__ import annotations

import json

import pytest

from steamcore.recognition.benchmark.repeated import (
    RepeatedBenchmarkOptions,
    RepeatedBenchmarkRunner,
    RepeatedReportContext,
    build_repeated_report,
    render_repeated_markdown,
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

    rows = runner.run()

    assert len(rows) == 12
    assert len(calls) == 16
    assert all(limit == 4 for _, _, limit in calls[:4])
    assert len(runner.execution_orders) == 3
    assert all(len(set(order)) == 4 for order in runner.execution_orders)
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
