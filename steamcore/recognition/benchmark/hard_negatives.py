"""Scénarios guidés de hard negatives, sans accès direct à Picamera2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .capture import CaptureOptions, CaptureResult, capture_mjpeg_session


@dataclass(frozen=True)
class HardNegativeScenario:
    condition: str
    prompt: str
    notes: str
    severity: str = "medium"


DEFAULT_HARD_NEGATIVES = (
    HardNegativeScenario(
        "aucune_plaque",
        "Laisser la scène réelle vide, sans plaque cible.",
        "décor réel sans objet présenté",
        "easy",
    ),
    HardNegativeScenario(
        "main_seule",
        "Présenter une main et des doigts, sans plaque.",
        "main seule proche de la zone de présentation",
    ),
    HardNegativeScenario(
        "telephone",
        "Présenter un téléphone avec un écran illustré ou contrasté.",
        "smartphone non cible, écran visible",
    ),
    HardNegativeScenario(
        "livre_illustration",
        "Présenter une couverture de livre ou une illustration non cible.",
        "illustration riche en détails, non présente dans PLATEST",
    ),
    HardNegativeScenario(
        "carte_imprimee_non_cible",
        "Présenter une carte imprimée qui n'est pas une plaque connue.",
        "carte rectangulaire illustrée non cible",
    ),
    HardNegativeScenario(
        "tissu_texture",
        "Présenter un vêtement ou tissu fortement texturé.",
        "texture répétitive et nombreux points caractéristiques",
    ),
    HardNegativeScenario(
        "quadrilatere_parasite",
        "Présenter un objet carré ou en losange non cible.",
        "quadrilatère contrasté non cible",
        "hard",
    ),
    HardNegativeScenario(
        "objet_reflechissant",
        "Présenter un objet brillant avec des reflets marqués.",
        "reflets et hautes lumières sans plaque cible",
    ),
    HardNegativeScenario(
        "ecran_illustration",
        "Afficher une illustration non cible sur un écran.",
        "écran avec image détaillée non présente dans PLATEST",
        "hard",
    ),
    HardNegativeScenario(
        "deux_objets_non_cibles",
        "Présenter simultanément deux objets illustrés non cibles.",
        "deux candidats visuels concurrents, aucun attendu",
        "hard",
    ),
)


def select_hard_negative_scenarios(selection: str) -> list[HardNegativeScenario]:
    by_name = {scenario.condition: scenario for scenario in DEFAULT_HARD_NEGATIVES}
    values = [part.strip().lower() for part in selection.split(",")]
    if values == ["all"]:
        return list(DEFAULT_HARD_NEGATIVES)
    unknown = [value for value in values if value not in by_name]
    if unknown:
        raise ValueError(f"Scénarios hard negative inconnus: {', '.join(unknown)}")
    return [by_name[value] for value in values]


def run_guided_hard_negative_capture(
    scenarios: list[HardNegativeScenario],
    *,
    corpus: str | Path,
    stream_url: str,
    duration_s: float,
    fps: float,
    countdown_s: float,
    repetitions: int = 1,
    input_fn: Callable[[str], str] = input,
    capture_fn: Callable[[CaptureOptions], CaptureResult] = capture_mjpeg_session,
    output_fn: Callable[[str], None] = print,
) -> list[CaptureResult]:
    if repetitions < 1:
        raise ValueError("repetitions doit être supérieur ou égal à 1")
    results = []
    total = len(scenarios) * repetitions
    position = 0
    for repetition in range(1, repetitions + 1):
        for scenario in scenarios:
            position += 1
            answer = (
                input_fn(
                    f"[{position}/{total}] {scenario.condition} — {scenario.prompt}\n"
                    "Entrée=capturer, s=passer, q=quitter : "
                )
                .strip()
                .lower()
            )
            if answer == "q":
                output_fn("Capture guidée interrompue proprement.")
                return results
            if answer == "s":
                output_fn(f"[skip] {scenario.condition}")
                continue
            result = capture_fn(
                CaptureOptions(
                    corpus=Path(corpus),
                    object_id=None,
                    condition=scenario.condition,
                    duration_s=duration_s,
                    fps=fps,
                    stream_url=stream_url,
                    countdown_s=countdown_s,
                    severity=scenario.severity,
                    notes=f"répétition {repetition}: {scenario.notes}",
                    source_orientation="runtime-corrected",
                )
            )
            results.append(result)
            output_fn(
                f"[ok] {scenario.condition}: {result.frames_saved} frame(s) -> "
                f"{result.directory}"
            )
    return results
