from __future__ import annotations

from itertools import product

import pytest

from steamcore.recognition.temporal import (
    TemporalCardValidator,
    TemporalStatus,
)


def test_temporal_validator_matches_default_runtime_sequence():
    validator = TemporalCardValidator(
        hold_ms=1000, consecutive_frames=1, miss_grace_frames=5
    )
    first = validator.register_detection("plate_x", 0.0)
    started = validator.register_detection("plate_x", 0.5)
    holding = validator.register_detection("plate_x", 1.0)
    triggered = validator.register_detection("plate_x", 1.5)

    assert first.status == TemporalStatus.NEW_CANDIDATE
    assert started.status == TemporalStatus.HOLD_STARTED
    assert started.hold_started is True
    assert started.held_ms == 0
    assert holding.status == TemporalStatus.HOLDING
    assert holding.held_ms == 500
    assert triggered.status == TemporalStatus.TRIGGERED
    assert triggered.held_ms == 1000


def test_consecutive_requirement_is_counted_before_hold():
    validator = TemporalCardValidator(
        hold_ms=500, consecutive_frames=3, miss_grace_frames=0
    )
    assert (
        validator.register_detection("plate_x", 0.0).status
        == TemporalStatus.NEW_CANDIDATE
    )
    second = validator.register_detection("plate_x", 0.1)
    third = validator.register_detection("plate_x", 0.2)
    assert second.status == TemporalStatus.ACCUMULATING
    assert second.consecutive_count == 2
    assert third.status == TemporalStatus.HOLD_STARTED
    assert third.consecutive_count == 3


def test_tolerated_misses_preserve_wall_clock_progress():
    validator = TemporalCardValidator(
        hold_ms=1000, consecutive_frames=1, miss_grace_frames=2
    )
    validator.register_detection("plate_x", 0.0)
    validator.register_detection("plate_x", 0.5)
    assert validator.register_miss().status == TemporalStatus.MISS_TOLERATED
    assert validator.register_miss().status == TemporalStatus.MISS_TOLERATED
    decision = validator.register_detection("plate_x", 1.5)
    assert decision.status == TemporalStatus.TRIGGERED
    assert decision.held_ms == 1000


def test_miss_beyond_grace_resets_candidate_and_hold():
    validator = TemporalCardValidator(
        hold_ms=1000, consecutive_frames=1, miss_grace_frames=1
    )
    validator.register_detection("plate_x", 0.0)
    validator.register_detection("plate_x", 0.5)
    assert validator.register_miss().status == TemporalStatus.MISS_TOLERATED
    reset = validator.register_miss()
    assert reset.status == TemporalStatus.RESET_AFTER_MISS
    assert reset.miss_count == 2
    assert validator.consecutive_card_id is None
    assert (
        validator.register_detection("plate_x", 2.0).status
        == TemporalStatus.NEW_CANDIDATE
    )


def test_different_card_resets_immediately():
    validator = TemporalCardValidator(
        hold_ms=1000, consecutive_frames=1, miss_grace_frames=5
    )
    validator.register_detection("plate_x", 0.0)
    validator.register_detection("plate_x", 0.5)
    changed = validator.register_detection("plate_y", 1.0)
    assert changed.status == TemporalStatus.NEW_CANDIDATE
    assert changed.card_id == "plate_y"
    assert validator.hold_card_id is None
    assert validator.consecutive_count == 1


def test_zero_hold_triggers_on_second_detection_and_starts_hold():
    validator = TemporalCardValidator(
        hold_ms=0, consecutive_frames=1, miss_grace_frames=0
    )
    validator.register_detection("plate_x", 0.0)
    decision = validator.register_detection("plate_x", 0.1)
    assert decision.status == TemporalStatus.TRIGGERED
    assert decision.triggered is True
    assert decision.hold_started is True


@pytest.mark.parametrize(
    "values",
    [(-1, 1, 0), (0, 0, 0), (0, 1, -1)],
)
def test_temporal_configuration_validation(values):
    with pytest.raises(ValueError):
        TemporalCardValidator(*values)


def _reference_runtime_triggers(sequence, hold_ms, consecutive_frames, grace):
    candidate = None
    count = 0
    hold_card = None
    hold_start = 0.0
    misses = 0
    triggers = []

    def reset():
        nonlocal candidate, count, hold_card, hold_start, misses
        candidate = None
        count = 0
        hold_card = None
        hold_start = 0.0
        misses = 0

    for index, detected in enumerate(sequence):
        now = index * 0.25
        if detected is None:
            if candidate is not None:
                misses += 1
                if misses > grace:
                    reset()
            continue
        if detected != candidate:
            candidate = detected
            count = 1
            hold_card = None
            hold_start = 0.0
            misses = 0
            continue
        misses = 0
        count += 1
        if count < consecutive_frames:
            continue
        if hold_card is None:
            hold_card = detected
            hold_start = now
        held_ms = (now - hold_start) * 1000
        if held_ms < hold_ms:
            continue
        triggers.append((index, detected))
        reset()
    return triggers


def test_shared_validator_matches_previous_runtime_over_many_traces():
    symbols = (None, "plate_x", "plate_y")
    configurations = (
        (0, 1, 0),
        (500, 1, 0),
        (500, 1, 2),
        (500, 3, 1),
        (1000, 1, 2),
    )
    for sequence in product(symbols, repeat=5):
        for hold_ms, consecutive_frames, grace in configurations:
            expected = _reference_runtime_triggers(
                sequence, hold_ms, consecutive_frames, grace
            )
            validator = TemporalCardValidator(hold_ms, consecutive_frames, grace)
            actual = []
            for index, detected in enumerate(sequence):
                if detected is None:
                    validator.register_miss()
                    continue
                decision = validator.register_detection(detected, index * 0.25)
                if decision.triggered:
                    actual.append((index, detected))
                    validator.reset()
            assert actual == expected
