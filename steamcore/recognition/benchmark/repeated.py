"""Campagnes répétées pour distinguer performances et effets d'ordre/cache."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import random
import subprocess
import time
from typing import Callable

import cv2
import numpy as np

from ..thresholds import RecognitionThresholds
from .runner import BenchmarkOptions, VisionBenchmarkRunner
from .variants import BenchmarkVariant


@dataclass(frozen=True)
class RepeatedBenchmarkOptions:
    runs: int = 5
    warmup_frames: int = 10
    seed: int = 9

    def __post_init__(self) -> None:
        if self.runs < 1:
            raise ValueError("runs doit être supérieur ou égal à 1")
        if self.warmup_frames < 0:
            raise ValueError("warmup_frames doit être positif ou nul")


@dataclass(frozen=True)
class RepeatedReportContext:
    corpus: str
    templates: str
    roi_mode: str
    variants: list[str]
    homographies: list[str]
    runs: int
    warmup_frames: int
    seed: int
    top_k: int
    top2_margin: float
    camera_rotation: int = 0
    hardware: str | None = None


class RepeatedBenchmarkRunner:
    def __init__(
        self,
        variants: list[BenchmarkVariant],
        homographies: list[str],
        benchmark_options: BenchmarkOptions,
        thresholds: RecognitionThresholds,
        repeated_options: RepeatedBenchmarkOptions,
        runner_factory: Callable | None = None,
    ):
        self.variants = variants
        self.homographies = homographies
        self.benchmark_options = benchmark_options
        self.thresholds = thresholds
        self.repeated_options = repeated_options
        self.runner_factory = runner_factory or self._default_runner_factory
        self.run_rows: list[dict] = []
        self.execution_orders: list[list[str]] = []

    def run(
        self,
        *,
        on_progress: Callable[[dict], None] | None = None,
        on_checkpoint: Callable[[RepeatedBenchmarkRunner], None] | None = None,
    ) -> list[dict]:
        configurations = [
            (variant, homography)
            for variant in self.variants
            for homography in self.homographies
        ]
        self.execution_orders = self._build_execution_orders(configurations)
        completed = {
            (row["run_index"], row["variant"], row["homography_requested"])
            for row in self.run_rows
        }
        total = len(configurations) * self.repeated_options.runs
        if self.repeated_options.warmup_frames and not completed:
            warmup_options = replace(
                self.benchmark_options,
                limit=self.repeated_options.warmup_frames,
                verbose=False,
                save_failures=None,
            )
            for variant, homography in configurations:
                self.runner_factory(
                    variant, homography, warmup_options, self.thresholds
                ).run()

        for run_index, ordered_names in enumerate(self.execution_orders, start=1):
            by_name = {
                f"{variant.code}/{homography}": (variant, homography)
                for variant, homography in configurations
            }
            ordered = [by_name[name] for name in ordered_names]
            for order_index, (variant, homography) in enumerate(ordered, start=1):
                key = (run_index, variant.code, homography)
                if key in completed:
                    continue
                position = len(self.run_rows) + 1
                if on_progress:
                    on_progress(
                        {
                            "status": "starting",
                            "completed": position - 1,
                            "total": total,
                            "run_index": run_index,
                            "order_index": order_index,
                            "variant": variant.code,
                            "homography": homography,
                        }
                    )
                started = time.perf_counter()
                metrics = self.runner_factory(
                    variant,
                    homography,
                    self.benchmark_options,
                    self.thresholds,
                ).run()
                summaries = metrics.grouped_summary()
                if len(summaries) != 1:
                    raise RuntimeError(
                        "Une exécution répétée doit produire une configuration"
                    )
                row = {
                    "run_index": run_index,
                    "order_index": order_index,
                    "variant": variant.code,
                    "backend": variant.l2_backend,
                    "homography_requested": homography,
                    "wall_time_s": time.perf_counter() - started,
                    **summaries[0],
                }
                self.run_rows.append(row)
                if on_checkpoint:
                    on_checkpoint(self)
                if on_progress:
                    on_progress(
                        {
                            "status": "completed",
                            "completed": len(self.run_rows),
                            "total": total,
                            "run_index": run_index,
                            "order_index": order_index,
                            "variant": variant.code,
                            "homography": homography,
                            "wall_time_s": row["wall_time_s"],
                        }
                    )
        return self.run_rows

    def restore(self, rows: list[dict]) -> None:
        """Restaure uniquement des résultats compatibles et aux positions prévues."""
        configurations = [
            (variant, homography)
            for variant in self.variants
            for homography in self.homographies
        ]
        orders = self._build_execution_orders(configurations)
        valid_positions = {
            (run_index, order_index): name
            for run_index, order in enumerate(orders, start=1)
            for order_index, name in enumerate(order, start=1)
        }
        seen = set()
        restored = []
        for row in rows:
            position = (int(row["run_index"]), int(row["order_index"]))
            expected = valid_positions.get(position)
            actual = f"{row['variant']}/{row['homography_requested']}"
            if expected != actual:
                raise ValueError(
                    f"Checkpoint incompatible à la position {position}: "
                    f"{actual}, attendu {expected}"
                )
            key = (position[0], row["variant"], row["homography_requested"])
            if key in seen:
                raise ValueError(f"Résultat dupliqué dans le checkpoint: {key}")
            seen.add(key)
            restored.append(dict(row))
        restored.sort(key=lambda row: (row["run_index"], row["order_index"]))
        self.run_rows = restored
        self.execution_orders = orders

    def aggregate(self) -> list[dict]:
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for row in self.run_rows:
            key = (row["variant"], row["backend"], row["homography_requested"])
            groups.setdefault(key, []).append(row)
        scalar_metrics = (
            "recall",
            "precision",
            "false_positive_rate",
            "false_negative_rate",
            "l1_hit_rate",
            "l2_success_rate",
            "l3_success_rate",
            "latency_ms_p50",
            "latency_ms_p95",
            "cpu_percent_mean",
            "fps_mean",
            "wall_time_s",
        )
        result = []
        for key, rows in sorted(groups.items()):
            aggregate = {
                "variant": key[0],
                "backend": key[1],
                "homography_requested": key[2],
                "runs": len(rows),
            }
            for metric in scalar_metrics:
                values = [
                    float(row[metric]) for row in rows if row.get(metric) is not None
                ]
                aggregate[metric] = _distribution(values)
            result.append(aggregate)
        return result

    def _default_runner_factory(
        self,
        variant: BenchmarkVariant,
        homography: str,
        options: BenchmarkOptions,
        thresholds: RecognitionThresholds,
    ) -> VisionBenchmarkRunner:
        return VisionBenchmarkRunner([variant], [homography], options, thresholds)

    def _build_execution_orders(self, configurations) -> list[list[str]]:
        orders = []
        for run_index in range(1, self.repeated_options.runs + 1):
            ordered = configurations.copy()
            random.Random(self.repeated_options.seed + run_index).shuffle(ordered)
            orders.append(
                [f"{variant.code}/{homography}" for variant, homography in ordered]
            )
        return orders


def build_repeated_report(
    runner: RepeatedBenchmarkRunner, context: RepeatedReportContext
) -> dict:
    return {
        "report_type": "vision_repeated_benchmark",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "opencv_version": cv2.__version__,
        "platform": platform.platform(),
        "hardware": context.hardware,
        "configuration": asdict(context),
        "execution_orders": runner.execution_orders,
        "aggregate": runner.aggregate(),
        "runs": runner.run_rows,
    }


def build_repeated_checkpoint(
    runner: RepeatedBenchmarkRunner,
    context: RepeatedReportContext,
    *,
    status: str = "running",
) -> dict:
    if status not in {"running", "complete"}:
        raise ValueError("Statut checkpoint invalide")
    return {
        "checkpoint_version": 1,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": asdict(context),
        "execution_orders": runner.execution_orders,
        "completed": len(runner.run_rows),
        "total": len(context.variants) * len(context.homographies) * context.runs,
        "runs": runner.run_rows,
    }


def restore_repeated_checkpoint(
    runner: RepeatedBenchmarkRunner,
    checkpoint: dict,
    context: RepeatedReportContext,
) -> None:
    if checkpoint.get("checkpoint_version") != 1:
        raise ValueError("Version de checkpoint non supportée")
    if checkpoint.get("configuration") != asdict(context):
        raise ValueError("Checkpoint incompatible avec la configuration demandée")
    rows = checkpoint.get("runs")
    if not isinstance(rows, list):
        raise ValueError("Checkpoint invalide: liste runs absente")
    runner.restore(rows)


def write_repeated_checkpoint(checkpoint: dict, path: str | Path) -> Path:
    """Écriture atomique : un arrêt ne peut pas laisser un JSON partiel."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(target)
    return target


def write_repeated_reports(
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
    _write_csv(report["runs"], paths["csv"])
    paths["markdown"].write_text(render_repeated_markdown(report), encoding="utf-8")
    return paths


def render_repeated_markdown(report: dict) -> str:
    config = report["configuration"]
    lines = [
        "# Campagne benchmark vision répétée",
        "",
        f"- Date UTC : {report['generated_at']}",
        f"- Commit Git : {report['git_commit'] or 'N/A'}",
        f"- OpenCV : {report['opencv_version']}",
        f"- Matériel : {report['hardware'] or 'N/A — non renseigné'}",
        f"- Corpus : `{config['corpus']}`",
        f"- ROI : `{config['roi_mode']}`",
        f"- Répétitions : `{config['runs']}` ; warm-up : "
        f"`{config['warmup_frames']}` frames/configuration ; seed : `{config['seed']}`",
        f"- Orientation ajoutée : `{config['camera_rotation']}°`",
        "",
        "> Chaque passe reçoit le même corpus. L'ordre des configurations est",
        "> mélangé de façon déterministe afin de limiter les biais d'ordre.",
        "",
        "## Agrégats inter-runs",
        "",
        "| Variante | Homographie | Runs | Recall moyen [min–max] | Precision moyenne | FPR moyen | Latence p50 moyenne [min–max] ms | Latence p95 moyenne [min–max] ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["aggregate"]:
        lines.append(
            "| {variant} | {homography} | {runs} | {recall} | {precision} | "
            "{fpr} | {p50} | {p95} |".format(
                variant=row["variant"],
                homography=row["homography_requested"],
                runs=row["runs"],
                recall=_range(row["recall"], percent=True),
                precision=_value(row["precision"]["mean"], percent=True),
                fpr=_value(row["false_positive_rate"]["mean"], percent=True),
                p50=_range(row["latency_ms_p50"]),
                p95=_range(row["latency_ms_p95"]),
            )
        )
    lines.extend(["", "## Ordre d'exécution", ""])
    for index, order in enumerate(report["execution_orders"], start=1):
        lines.append(f"- Passe {index} : `{' → '.join(order)}`")
    lines.extend(
        [
            "",
            "## Résultats par passe",
            "",
            "| Passe | Ordre | Variante | Homographie | Recall | Precision | FPR | Latence p50/p95 ms | Temps mural s |",
            "|---:|---:|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report["runs"]:
        lines.append(
            f"| {row['run_index']} | {row['order_index']} | {row['variant']} | "
            f"{row['homography_requested']} | {_value(row['recall'], percent=True)} | "
            f"{_value(row['precision'], percent=True)} | "
            f"{_value(row['false_positive_rate'], percent=True)} | "
            f"{_value(row['latency_ms_p50'])} / {_value(row['latency_ms_p95'])} | "
            f"{_value(row['wall_time_s'])} |"
        )
    lines.extend(
        [
            "",
            "Les distributions inter-runs ne remplacent pas une campagne terrain",
            "diversifiée. Aucun résultat n'est appliqué automatiquement en production.",
            "",
        ]
    )
    return "\n".join(lines)


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None, "p50": None}
    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "min": min(values),
        "max": max(values),
        "p50": float(np.percentile(values, 50)),
    }


def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    scalar_rows = []
    for row in rows:
        scalar_rows.append(
            {
                key: value
                for key, value in row.items()
                if value is None or isinstance(value, (str, int, float, bool))
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(scalar_rows[0]))
        writer.writeheader()
        writer.writerows(scalar_rows)


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


def _range(distribution: dict, *, percent: bool = False) -> str:
    if distribution["mean"] is None:
        return "N/A"
    return (
        f"{_value(distribution['mean'], percent=percent)} "
        f"[{_value(distribution['min'], percent=percent)}–"
        f"{_value(distribution['max'], percent=percent)}]"
    )


def _value(value: float | None, *, percent: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    if percent:
        return f"{value * 100:.2f} %"
    return f"{value:.2f}"
