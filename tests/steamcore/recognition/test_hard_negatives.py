from __future__ import annotations

from pathlib import Path

import pytest

from steamcore.recognition.benchmark.capture import CaptureResult
from steamcore.recognition.benchmark.hard_negatives import (
    DEFAULT_HARD_NEGATIVES,
    run_guided_hard_negative_capture,
    select_hard_negative_scenarios,
)


def test_select_hard_negative_scenarios():
    selected = select_hard_negative_scenarios("telephone,quadrilatere_parasite")
    assert [scenario.condition for scenario in selected] == [
        "telephone",
        "quadrilatere_parasite",
    ]
    assert len(select_hard_negative_scenarios("all")) == len(DEFAULT_HARD_NEGATIVES)
    with pytest.raises(ValueError, match="inconnus"):
        select_hard_negative_scenarios("plaque_connue")


def test_guided_capture_can_skip_and_quit_without_camera(tmp_path):
    answers = iter(["s", "q"])
    captures = []
    output = []
    results = run_guided_hard_negative_capture(
        list(DEFAULT_HARD_NEGATIVES[:3]),
        corpus=tmp_path,
        stream_url="http://stream",
        duration_s=10,
        fps=2,
        countdown_s=0,
        input_fn=lambda _prompt: next(answers),
        capture_fn=captures.append,
        output_fn=output.append,
    )
    assert results == []
    assert captures == []
    assert output == [
        "[skip] aucune_plaque",
        "Capture guidée interrompue proprement.",
    ]


def test_guided_capture_writes_negative_ground_truth(tmp_path):
    captured_options = []

    def capture(options):
        captured_options.append(options)
        return CaptureResult(
            directory=Path(tmp_path / options.condition),
            sequence_id=f"sequence-{len(captured_options)}",
            frames_saved=20,
            elapsed_s=10.0,
        )

    results = run_guided_hard_negative_capture(
        list(DEFAULT_HARD_NEGATIVES[:1]),
        corpus=tmp_path,
        stream_url="http://stream",
        duration_s=10,
        fps=2,
        countdown_s=3,
        repetitions=2,
        input_fn=lambda _prompt: "",
        capture_fn=capture,
        output_fn=lambda _message: None,
    )
    assert len(results) == 2
    assert all(options.object_id is None for options in captured_options)
    assert all(
        options.source_orientation == "runtime-corrected"
        for options in captured_options
    )
    assert captured_options[0].condition == "aucune_plaque"
    assert "répétition 2" in captured_options[1].notes
