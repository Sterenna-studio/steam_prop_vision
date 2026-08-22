"""Définition stable des variantes A à E de l'issue #9."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkVariant:
    code: str
    l2_backend: str
    l3_backend: str
    description: str


_VARIANTS = {
    "A": BenchmarkVariant("A", "orb", "orb", "Baseline ORB / ORB"),
    "B": BenchmarkVariant("B", "sift", "orb", "SIFT / ORB"),
    "C": BenchmarkVariant("C", "akaze", "orb", "AKAZE / ORB"),
    "D": BenchmarkVariant("D", "orb", "appearance", "ORB / apparence globale"),
    "E": BenchmarkVariant("E", "akaze", "appearance", "AKAZE / apparence globale"),
}


def get_variants(selection: str | list[str]) -> list[BenchmarkVariant]:
    if isinstance(selection, str):
        values = [part.strip().upper() for part in selection.split(",")]
    else:
        values = [part.strip().upper() for part in selection]
    if values == ["ALL"]:
        values = list(_VARIANTS)
    unknown = [value for value in values if value not in _VARIANTS]
    if unknown:
        raise ValueError(f"Variantes inconnues: {', '.join(unknown)}")
    return [_VARIANTS[value] for value in values]
