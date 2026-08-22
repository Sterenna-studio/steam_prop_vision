"""Profils versionnables avec fallback explicite sur la configuration actuelle."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class VisionProfile:
    name: str
    backend: str
    rules: str
    objects: dict = field(default_factory=dict)
    recognition: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    benchmark_reference: str | None = None
    legacy_fallback: bool = False


class ProfileManager:
    def __init__(
        self, root: str | Path = "profiles", config_dir: str | Path = "config"
    ):
        self.root = Path(root)
        self.config_dir = Path(config_dir)

    def list_profiles(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            directory.name
            for directory in self.root.iterdir()
            if directory.is_dir()
            and not directory.name.startswith("_")
            and (directory / "profile.yaml").is_file()
        )

    def active_name(self) -> str | None:
        pointer = self.root / "active.yaml"
        if not pointer.exists():
            return None
        values = yaml.safe_load(pointer.read_text(encoding="utf-8")) or {}
        if not isinstance(values, dict):
            raise ValueError("profiles/active.yaml doit contenir un mapping")
        active = values.get("active")
        return str(active) if active else None

    def load(self, name: str | None = None) -> VisionProfile:
        selected = name or self.active_name()
        if selected is None:
            return self.legacy_profile()
        path = self._profile_path(selected) / "profile.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Profil introuvable: {selected}")
        values = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(values, dict):
            raise ValueError(f"Profil invalide: {path}")
        return VisionProfile(
            name=str(values.get("name", selected)),
            backend=str(values.get("backend", "image_match")),
            rules=str(values.get("rules", "config/rules.yaml")),
            objects=values.get("objects", {}) or {},
            recognition=values.get("recognition", {}) or {},
            camera=values.get("camera", {}) or {},
            benchmark_reference=values.get("benchmark_reference"),
        )

    def legacy_profile(self) -> VisionProfile:
        return VisionProfile(
            name="legacy",
            backend="image_match",
            rules=str(self.config_dir / "rules.yaml"),
            legacy_fallback=True,
        )

    def _profile_path(self, name: str) -> Path:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"Nom de profil invalide: {name!r}")
        return self.root / name
