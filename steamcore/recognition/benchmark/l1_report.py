"""Rapports JSON, CSV et Markdown du benchmark L1 v2."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

import cv2

from .l1_metrics import L1MetricsAccumulator


@dataclass
class L1ReportContext:
    corpus: str
    templates: str
    recognition_variant: str
    homography: str
    strategies: list[str]
    calibrated_roi: dict | None
    calibration_samples_seen: int | None
    calibration_detections_used: int | None
    quality_threshold: float
    tracking_threshold: float
    hold_ms: int
    consecutive_frames: int
    miss_grace_frames: int
    top_k: int
    top2_margin: float
    camera_rotation: int = 0
    hardware: str | None = None
    camera_parameters: dict | None = None


def build_l1_report(metrics: L1MetricsAccumulator, context: L1ReportContext) -> dict:
    return {
        "report_type": "vision_l1_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "opencv_version": cv2.__version__,
        "platform": platform.platform(),
        "hardware": context.hardware,
        "camera_parameters": context.camera_parameters,
        "configuration": asdict(context),
        "strategies": metrics.grouped_summary(),
        "samples": [row.to_dict() for row in metrics.rows],
    }


def write_l1_reports(
    report: dict, output_dir: str | Path, stem: str
) -> dict[str, Path]:
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
    paths["markdown"].write_text(render_l1_markdown(report), encoding="utf-8")
    return paths


def render_l1_markdown(report: dict) -> str:
    config = report["configuration"]
    lines = [
        "# Rapport Benchmark L1 v2",
        "",
        f"- Date UTC : {report['generated_at']}",
        f"- Commit Git : {report['git_commit'] or 'N/A'}",
        f"- OpenCV : {report['opencv_version']}",
        f"- Matériel : {report['hardware'] or 'N/A — non renseigné'}",
        f"- Corpus : `{config['corpus']}`",
        f"- Orientation ajoutée au replay : `{config['camera_rotation']}°`",
        f"- Reconnaissance constante : variante `{config['recognition_variant']}` / "
        f"`{config['homography']}`",
        f"- ROI calibrée : `{json.dumps(config['calibrated_roi'])}`",
        f"- Hold simulé : `{config['hold_ms']} ms`, "
        f"`{config['consecutive_frames']}` frame(s), grâce "
        f"`{config['miss_grace_frames']}` misses",
        "",
        "> Ce rapport compare uniquement les politiques L1. Il n'active aucune",
        "> stratégie dans le pipeline de production.",
        "",
        "> Critère produit : recall du corpus de référence >= 98 %, avec precision,",
        "> faux positifs et faux négatifs affichés séparément.",
        "",
        "## Comparaison principale",
        "",
        "| Stratégie | N | Recall frame | Precision | FPR | Fallback | Présentations détectées | Triggers corrects | Triggers erronés | Triggers négatifs | Latence p50/p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    strategies = report["strategies"]
    if not strategies:
        lines.append(
            "| N/A | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        )
    for row in strategies:
        lines.append(
            "| {strategy} | {samples} | {recall} | {precision} | {fpr} | "
            "{fallback} | {presentation} | {trigger} | {wrong} | {negative} | "
            "{p50} / {p95} |".format(
                strategy=row["strategy"],
                samples=row["samples"],
                recall=_percent(row["recall"]),
                precision=_percent(row["precision"]),
                fpr=_percent(row["false_positive_rate"]),
                fallback=_percent(row["fallback_rate"]),
                presentation=_percent(row["presentation_detection_rate"]),
                trigger=_percent(row["trigger_success_rate"]),
                wrong=_percent(row["wrong_trigger_rate"]),
                negative=_percent(row["negative_trigger_rate"]),
                p50=_number(row["latency_ms_p50"]),
                p95=_number(row["latency_ms_p95"]),
            )
        )
    lines.extend(
        [
            "",
            "## Temporalité",
            "",
            "| Stratégie | TTFD p50/p95 s | Trigger p50/p95 s | Longest miss streak | Contour hit |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in strategies:
        lines.append(
            "| {strategy} | {d50} / {d95} | {t50} / {t95} | {miss} | {contour} |".format(
                strategy=row["strategy"],
                d50=_number(row["time_to_first_detection_p50"]),
                d95=_number(row["time_to_first_detection_p95"]),
                t50=_number(row["time_to_trigger_p50"]),
                t95=_number(row["time_to_trigger_p95"]),
                miss=row["longest_miss_streak"],
                contour=_percent(row["contour_hit_rate"]),
            )
        )
    lines.extend(["", "## Par condition", ""])
    lines.extend(
        [
            "| Stratégie | Condition | N | Recall | Contour hit | Fallback |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in strategies:
        for condition, values in row["metrics_by_condition"].items():
            lines.append(
                f"| {row['strategy']} | {condition} | {values['samples']} | "
                f"{_percent(values['recall'])} | "
                f"{_percent(values['contour_hit_rate'])} | "
                f"{_percent(values['fallback_rate'])} |"
            )
    lines.extend(["", "## Par objet", ""])
    lines.extend(
        [
            "| Stratégie | Objet | N | Recall frame | Présentations détectées | Triggers corrects |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in strategies:
        for object_id, values in row["recall_by_object"].items():
            lines.append(
                f"| {row['strategy']} | {object_id} | {values['samples']} | "
                f"{_percent(values['recall'])} | "
                f"{_percent(values['presentation_detection_rate'])} | "
                f"{_percent(values['trigger_success_rate'])} |"
            )
    lines.extend(
        [
            "",
            "## Interprétation",
            "",
            "Aucune stratégie n'est recommandée automatiquement. Une décision de",
            "production exige un corpus plus large, des négatifs difficiles et une",
            "validation physique sur STYX.",
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


def _number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f} %"
