"""
tests/apps_rpi/test_qr_flux.py
Tests unitaires pour apps.rpi.qr_flux.QRFluxChecker. Le décodage QR est
monkeypatché — aucune dépendance à pyzbar/libzbar0 ou à une image réelle,
donc robuste en CI même sans le paquet système libzbar0.
"""

from __future__ import annotations

import pytest

from apps.rpi import qr_flux
from apps.rpi.qr_flux import QR_CHECK_EVERY, QR_REPEAT_COOLDOWN, QRFluxChecker


@pytest.fixture
def checker():
    return QRFluxChecker(mission_id="flux_1")


def _decode(monkeypatch, payload):
    monkeypatch.setattr(qr_flux, "_decode_qr", lambda frame, det: payload)


def test_skips_frames_not_on_check_interval(monkeypatch, checker):
    _decode(monkeypatch, "STEAM_FLUX:flux_1")
    for fc in range(1, QR_CHECK_EVERY):
        assert checker.check(frame=None, frame_count=fc, now=0.0) is None


def test_matching_flux_returns_system_ready(monkeypatch, checker):
    _decode(monkeypatch, "STEAM_FLUX:flux_1")
    event = checker.check(frame=None, frame_count=QR_CHECK_EVERY, now=100.0)
    assert event == {
        "type": "system_ready",
        "label": "STEAM VISION READY — FLUX_1",
    }


def test_mismatched_flux_returns_flux_mismatch(monkeypatch, checker):
    _decode(monkeypatch, "STEAM_FLUX:flux_2")
    event = checker.check(frame=None, frame_count=QR_CHECK_EVERY, now=100.0)
    assert event == {
        "type": "flux_mismatch",
        "expected": "flux_1",
        "scanned": "flux_2",
    }


def test_no_qr_or_non_flux_payload_returns_none(monkeypatch, checker):
    _decode(monkeypatch, None)
    assert checker.check(frame=None, frame_count=QR_CHECK_EVERY, now=100.0) is None

    _decode(monkeypatch, "SOME_OTHER_PAYLOAD")
    assert checker.check(frame=None, frame_count=2 * QR_CHECK_EVERY, now=101.0) is None


def test_repeat_within_cooldown_is_suppressed(monkeypatch, checker):
    _decode(monkeypatch, "STEAM_FLUX:flux_1")
    first = checker.check(frame=None, frame_count=QR_CHECK_EVERY, now=100.0)
    assert first is not None

    second = checker.check(
        frame=None,
        frame_count=2 * QR_CHECK_EVERY,
        now=100.0 + QR_REPEAT_COOLDOWN - 0.1,
    )
    assert second is None


def test_repeat_after_cooldown_fires_again(monkeypatch, checker):
    _decode(monkeypatch, "STEAM_FLUX:flux_1")
    first = checker.check(frame=None, frame_count=QR_CHECK_EVERY, now=100.0)
    assert first is not None

    third = checker.check(
        frame=None,
        frame_count=2 * QR_CHECK_EVERY,
        now=100.0 + QR_REPEAT_COOLDOWN + 0.1,
    )
    assert third is not None
