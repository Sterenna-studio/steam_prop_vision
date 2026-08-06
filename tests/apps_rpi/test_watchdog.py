"""
tests/apps_rpi/test_watchdog.py
Tests unitaires pour apps.rpi.watchdog.Watchdog. La logique de staleness est
testée par injection de `now` — pas de vrai sleep() ni de thread réel.
"""

from __future__ import annotations

from apps.rpi.watchdog import Watchdog


def test_fresh_touch_is_not_stale():
    wd = Watchdog(timeout_s=20.0)
    assert wd.is_stale(now=wd._last_alive + 5.0) is False


def test_elapsed_beyond_timeout_is_stale():
    wd = Watchdog(timeout_s=20.0)
    assert wd.is_stale(now=wd._last_alive + 21.0) is True


def test_touch_resets_staleness():
    wd = Watchdog(timeout_s=20.0)
    later = wd._last_alive + 30.0
    assert wd.is_stale(now=later) is True

    wd.touch()
    assert wd.is_stale(now=wd._last_alive + 5.0) is False


def test_is_stale_defaults_to_current_time():
    wd = Watchdog(timeout_s=20.0)
    assert wd.is_stale() is False
