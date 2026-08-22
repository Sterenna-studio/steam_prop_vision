"""Génération déterministe des rapports JSON, CSV et Markdown."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

import cv2

from .metrics import VisionMetricsAccumulator


@dataclass
class ReportContext:
    corpus: str
    templates: str
    roi_mode: str
    top_k: int
    top2_margin: float
    camera_rotation: int = 0
    hardware: str | None = None
    camera_parameters: dict | None = None


def build_report(metrics: VisionMetricsAccumulator, context: ReportContext) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "opencv_version": cv2.__version__,
        "platform": platform.platform(),
        "hardware": context.hardware,
        "camera_parameters": context.camera_parameters,
        "configuration": asdict(context),
        "summary": metrics.summary(),
        "variants": metrics.grouped_summary(),
        "threshold_recommendations": _threshold_recommendations(metrics),
        "samples": [row.to_dict() for row in metrics.rows],
    }


def write_reports(report: dict, output_dir: str | Path, stem: str) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": directory / f"{stem}.json",
        "csv": directory / f"{stem}.csv",
        "markdown": directory / f"{stem}.md",
    }
    paths["json"].write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_csv(report["samples"], paths["csv"])
    paths["markdown"].write_text(render_markdown(report), encoding="utf-8")
    return paths


def render_markdown(report: dict) -> str:
    configuration = report["configuration"]
    lines = [
        "# Rapport benchmark vision",
        "",
        f"- Date UTC : {report['generated_at']}",
        f"- Commit Git : {report['git_commit'] or 'N/A'}",
        f"- OpenCV : {report['opencv_version']}",
        f"- Matériel : {report['hardware'] or 'N/A — non renseigné'}",
        "- Paramètres caméra : "
        + (
            f"`{json.dumps(report['camera_parameters'], ensure_ascii=False)}`"
            if report["camera_parameters"]
            else "N/A — non renseignés"
        ),
        f"- Corpus : `{configuration['corpus']}`",
        f"- Templates runtime : `{configuration['templates']}`",
        f"- ROI : `{configuration['roi_mode']}`",
        "",
        "> Critère produit : un setup S.T.E.A.M Vision n'est pas considéré fiable",
        "> si son recall sur le corpus de référence est inférieur à 98 %. La",
        "> precision et les taux de faux positifs/négatifs restent évalués séparément.",
        "",
        "## Comparaison A–E",
        "",
        "| Variante | L2 | Homographie demandée | N | Recall | Precision | FP | FN | FPR | FNR | Latence p50/p95 (ms) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    variants = report["variants"]
    if variants:
        for variant in variants:
            latency = (
                f"{_fmt(variant['latency_ms_p50'])} / {_fmt(variant['latency_ms_p95'])}"
            )
            lines.append(
                "| {variant} | {backend} | {homography} | {samples} | {recall} | "
                "{precision} | {fp} | {fn} | {fpr} | {fnr} | {latency} |".format(
                    variant=variant["variant"],
                    backend=variant["backend"],
                    homography=variant["homography_requested"],
                    samples=variant["samples"],
                    recall=_fmt_percent(variant["recall"]),
                    precision=_fmt_percent(variant["precision"]),
                    fp=variant["false_positives"],
                    fn=variant["false_negatives"],
                    fpr=_fmt_percent(variant["false_positive_rate"]),
                    fnr=_fmt_percent(variant["false_negative_rate"]),
                    latency=latency,
                )
            )
    else:
        lines.append("| N/A | N/A | N/A | 0 | N/A | N/A | 0 | 0 | N/A | N/A | N/A |")

    lines.extend(["", "## Temps et ressources", ""])
    if variants:
        lines.extend(
            [
                "| Variante | Homographie | TTD p50/p95 (s) | Longest miss | CPU moyen | RAM pic (MB) | FPS moyen |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for variant in variants:
            detection = (
                f"{_fmt(variant['time_to_first_detection_p50'])} / "
                f"{_fmt(variant['time_to_first_detection_p95'])}"
            )
            lines.append(
                "| {variant} | {homography} | {detection} | {miss} | {cpu} | "
                "{ram} | {fps} |".format(
                    variant=variant["variant"],
                    homography=variant["homography_requested"],
                    detection=detection,
                    miss=variant["longest_miss_streak"],
                    cpu=_fmt_percent_ratio(variant["cpu_percent_mean"]),
                    ram=_fmt(variant["ram_mb_peak"]),
                    fps=_fmt(variant["fps_mean"]),
                )
            )
    else:
        lines.append("N/A — corpus terrain STYX requis.")

    lines.extend(["", "## Recall par objet", ""])
    object_rows = _object_rows(variants)
    if object_rows:
        lines.extend(
            [
                "| Variante | Homographie | Objet | N | Recall |",
                "|---|---|---|---:|---:|",
            ]
        )
        for row in object_rows:
            lines.append(
                f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {_fmt_percent(row[4])} |"
            )
    else:
        lines.append("N/A — corpus terrain STYX requis.")

    lines.extend(["", "## Matrice de confusion", ""])
    if variants:
        for variant in variants:
            lines.append(
                f"### {variant['variant']} / {variant['homography_requested']}"
            )
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(variant["confusion"], indent=2, ensure_ascii=False))
            lines.extend(["```", ""])
    else:
        lines.append("N/A — aucun échantillon mesuré.")

    lines.extend(["", "## Recommandations de seuil", ""])
    recommendations = report["threshold_recommendations"]
    if recommendations:
        lines.append("```json")
        lines.append(json.dumps(recommendations, indent=2, ensure_ascii=False))
        lines.append("```")
    else:
        lines.append("N/A — données positives et négatives insuffisantes.")

    lines.extend(
        [
            "",
            "## Données non disponibles",
            "",
            "`time_to_trigger` exige une simulation explicite du hold runtime et n'est",
            "pas déduit artificiellement. CPU/RAM restent N/A sur les plateformes qui",
            "ne permettent pas leur mesure sans dépendance supplémentaire.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _threshold_recommendations(metrics: VisionMetricsAccumulator) -> dict:
    recommendations = {}
    object_ids = sorted(
        {row.object_expected for row in metrics.rows if row.object_expected is not None}
    )
    for object_id in object_ids:
        positive_scores = [
            row.score
            for row in metrics.rows
            if row.object_expected == object_id and row.object_detected == object_id
        ]
        negative_scores = [
            row.score
            for row in metrics.rows
            if row.object_expected != object_id and row.l3_best_candidate == object_id
        ]
        if not positive_scores or not negative_scores:
            continue
        positive_floor = min(positive_scores)
        negative_ceiling = max(negative_scores)
        if negative_ceiling < positive_floor:
            recommendations[object_id] = {
                "suggested_threshold": round(
                    (positive_floor + negative_ceiling) / 2.0, 4
                ),
                "method": "midpoint_between_observed_classes",
                "apply_automatically": False,
            }
    return recommendations


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _object_rows(variants: list[dict]) -> list[tuple]:
    rows = []
    for variant in variants:
        for object_id, values in variant["recall_by_object"].items():
            rows.append(
                (
                    variant["variant"],
                    variant["homography_requested"],
                    object_id,
                    values["samples"],
                    values["recall"],
                )
            )
    return rows


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _fmt_percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f} %"


def _fmt_percent_ratio(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f} %"
