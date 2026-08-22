from __future__ import annotations

import json

import cv2
import numpy as np

from steamcore.recognition.benchmark.corpus import discover_corpus, iter_frames
from steamcore.recognition.benchmark.metrics import (
    VisionMetric,
    VisionMetricsAccumulator,
    classify,
)
from steamcore.recognition.benchmark.report import (
    ReportContext,
    build_report,
    render_markdown,
    write_reports,
)
from steamcore.recognition.benchmark.runner import (
    BenchmarkOptions,
    VisionBenchmarkRunner,
)
from steamcore.recognition.benchmark.variants import get_variants


def _metric(expected="plate_x", detected="plate_x"):
    flags = classify(expected, detected)
    return VisionMetric(
        sample_id="plate_x/frontal/a.png",
        frame_index=0,
        timestamp_s=0.0,
        backend="orb",
        variant="A",
        homography_backend="ransac",
        homography_requested="ransac",
        homography_fallback_used=False,
        object_expected=expected,
        object_detected=detected,
        condition="frontal",
        l1_hit=True,
        l1_miss=False,
        l2_success=True,
        l2_fail=False,
        l2_latency_ms=2.0,
        l3_success=detected is not None,
        l3_fail=detected is None,
        l3_latency_ms=1.0,
        total_latency_ms=3.0,
        **flags,
    )


def test_corpus_metadata_parser_and_negative_inclusion(tmp_path):
    corpus = tmp_path / "corpus"
    positive = corpus / "plate_x" / "occlusion"
    negative = corpus / "negatives" / "aucune_plaque"
    positive.mkdir(parents=True)
    negative.mkdir(parents=True)
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    cv2.imwrite(str(positive / "sample.png"), image)
    cv2.imwrite(str(negative / "empty.png"), image)
    (positive / "sample.yaml").write_text(
        "expected: plate_x\nseverity: medium\nnotes: main gauche\n",
        encoding="utf-8",
    )
    entries = discover_corpus(corpus, object_id="plate_x")
    assert len(entries) == 2
    positive_entry = next(entry for entry in entries if entry.metadata.expected)
    negative_entry = next(entry for entry in entries if entry.metadata.expected is None)
    assert positive_entry.metadata.severity == "medium"
    assert negative_entry.metadata.expected is None
    assert next(iter_frames(positive_entry)).frame_index == 0


def test_metrics_and_report_generation(tmp_path):
    metrics = VisionMetricsAccumulator()
    metrics.add(_metric())
    metrics.add(_metric(expected=None, detected="plate_x"))
    summary = metrics.summary()
    assert summary["recall"] == 1.0
    assert summary["precision"] == 0.5
    assert summary["false_positive_rate"] == 1.0
    report = build_report(
        metrics,
        ReportContext("corpus", "PLATEST", "l1", 2, 0.1, 0),
    )
    markdown = render_markdown(report)
    assert "Recall" in markdown
    assert "98 %" in markdown
    paths = write_reports(report, tmp_path, "report")
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["samples"]
    assert paths["csv"].read_text(encoding="utf-8").startswith("sample_id")
    assert paths["markdown"].exists()


def test_variants_a_to_e():
    variants = get_variants("all")
    assert [variant.code for variant in variants] == ["A", "B", "C", "D", "E"]
    assert variants[0].l2_backend == "orb"
    assert variants[-1].l3_backend == "appearance"


def test_runner_replays_synthetic_corpus(tmp_path):
    templates = tmp_path / "PLATEST" / "plate_x"
    corpus = tmp_path / "corpus" / "plate_x" / "frontal"
    templates.mkdir(parents=True)
    corpus.mkdir(parents=True)
    rng = np.random.default_rng(7)
    template = rng.integers(0, 256, (300, 300), dtype=np.uint8)
    cv2.putText(template, "STEAM", (35, 160), cv2.FONT_HERSHEY_SIMPLEX, 2, 255, 5)
    cv2.imwrite(str(templates / "source.png"), template)
    query = cv2.copyMakeBorder(template, 50, 50, 50, 50, cv2.BORDER_CONSTANT, value=127)
    cv2.imwrite(str(corpus / "sample.png"), query)
    runner = VisionBenchmarkRunner(
        get_variants("A"),
        ["ransac"],
        BenchmarkOptions(
            corpus=str(tmp_path / "corpus"),
            templates=str(tmp_path / "PLATEST"),
            roi_mode="full",
            top_k=1,
            orb_threshold=0.01,
            l3_min_matches=4,
            camera_rotation=0,
        ),
    )
    metrics = runner.run()
    assert len(metrics.rows) == 1
    assert metrics.rows[0].object_expected == "plate_x"
    assert metrics.rows[0].l2_success is True
    assert metrics.rows[0].true_positive is True
