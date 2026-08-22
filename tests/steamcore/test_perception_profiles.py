from __future__ import annotations

import numpy as np
import pytest

from steamcore.perception import PerceptionResult
from steamcore.profiles import ProfileManager


def test_perception_result_optional_geometry():
    result = PerceptionResult("plate_x", 0.8, "image_match")
    assert result.corners is None
    assert result.bbox is None
    result = PerceptionResult(
        "marker_1", 1.0, "aruco", corners=np.zeros((4, 2), dtype=np.float32)
    )
    assert result.corners.shape == (4, 2)


def test_perception_result_rejects_invalid_confidence():
    with pytest.raises(ValueError):
        PerceptionResult("x", 1.1, "test")


def test_profiles_fallback_and_load(tmp_path):
    manager = ProfileManager(tmp_path / "profiles", tmp_path / "config")
    legacy = manager.load()
    assert legacy.legacy_fallback is True
    assert legacy.rules.endswith("rules.yaml")
    profile_dir = tmp_path / "profiles" / "benchmark"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.yaml").write_text(
        "name: benchmark\nbackend: aruco\nrules: rules/demo.yaml\n",
        encoding="utf-8",
    )
    assert manager.list_profiles() == ["benchmark"]
    assert manager.load("benchmark").backend == "aruco"
    with pytest.raises(ValueError):
        manager.load("../escape")
