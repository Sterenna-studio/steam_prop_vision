"""CLI de campagnes benchmark répétées, randomisées et avec warm-up."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from steamcore.recognition.benchmark.repeated import (  # noqa: E402
    RepeatedBenchmarkOptions,
    RepeatedBenchmarkRunner,
    RepeatedReportContext,
    build_repeated_checkpoint,
    build_repeated_report,
    restore_repeated_checkpoint,
    write_repeated_checkpoint,
    write_repeated_reports,
)
from steamcore.recognition.benchmark.runner import BenchmarkOptions  # noqa: E402
from steamcore.recognition.benchmark.variants import get_variants  # noqa: E402
from steamcore.recognition.thresholds import RecognitionThresholds  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Répète les configurations vision dans un ordre reproductible."
    )
    parser.add_argument("--corpus", default="benchmark/corpus")
    parser.add_argument("--templates", default="PLATEST")
    parser.add_argument("--variant", "--variants", default="A")
    parser.add_argument("--homography", default="all")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup-frames", type=int, default=10)
    parser.add_argument("--seed", type=int, default=9)
    parser.add_argument(
        "--roi-mode", choices=("l1", "full", "hybrid"), default="hybrid"
    )
    parser.add_argument(
        "--camera-rotation", type=int, choices=(0, 90, 180, 270), default=0
    )
    parser.add_argument("--object", dest="object_id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-k", type=int, choices=(1, 2), default=2)
    parser.add_argument("--top2-margin", type=float, default=0.10)
    parser.add_argument("--config", default="config/features.yaml")
    parser.add_argument("--hardware")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--output", default="benchmark/reports")
    parser.add_argument(
        "--checkpoint",
        help="Fichier checkpoint JSON ; un nom horodaté est créé par défaut",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reprendre le fichier fourni par --checkpoint",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    variants = get_variants(args.variant)
    homographies = _homographies(args.homography)
    config = _load_mapping(args.config)
    thresholds = RecognitionThresholds.from_config(config, legacy_default=0.20)
    benchmark_options = BenchmarkOptions(
        corpus=args.corpus,
        templates=args.templates,
        roi_mode=args.roi_mode,
        top_k=args.top_k,
        top2_margin=args.top2_margin,
        limit=args.limit,
        object_id=args.object_id,
        orb_threshold=thresholds.default_threshold,
        l3_min_matches=int(config.get("card_min_matches", 12)),
        fast_min_area=int(config.get("card_min_area", 4000)),
        camera_rotation=args.camera_rotation,
    )
    repeated_options = RepeatedBenchmarkOptions(
        runs=args.runs, warmup_frames=args.warmup_frames, seed=args.seed
    )
    context = RepeatedReportContext(
        corpus=str(Path(args.corpus).resolve()),
        templates=str(Path(args.templates).resolve()),
        roi_mode=args.roi_mode,
        variants=[variant.code for variant in variants],
        homographies=homographies,
        runs=args.runs,
        warmup_frames=args.warmup_frames,
        seed=args.seed,
        top_k=args.top_k,
        top2_margin=args.top2_margin,
        camera_rotation=args.camera_rotation,
        hardware=args.hardware,
    )
    runner = RepeatedBenchmarkRunner(
        variants,
        homographies,
        benchmark_options,
        thresholds,
        repeated_options,
    )
    started_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.resume and not args.checkpoint:
        raise ValueError("--resume exige --checkpoint")
    checkpoint_path = (
        Path(args.checkpoint)
        if args.checkpoint
        else Path(args.output) / f"vision-repeated-{started_at}.checkpoint.json"
    )
    if args.resume:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        restore_repeated_checkpoint(runner, checkpoint, context)
        print(
            f"[resume] {len(runner.run_rows)}/"
            f"{args.runs * len(variants) * len(homographies)} résultats restaurés",
            flush=True,
        )
    print(f"[checkpoint] fichier: {checkpoint_path}", flush=True)

    def save_checkpoint(current_runner):
        write_repeated_checkpoint(
            build_repeated_checkpoint(current_runner, context), checkpoint_path
        )

    try:
        runner.run(on_progress=_print_progress, on_checkpoint=save_checkpoint)
    except KeyboardInterrupt:
        save_checkpoint(runner)
        print(f"\n[checkpoint] campagne interrompue: {checkpoint_path}", flush=True)
        return 130

    write_repeated_checkpoint(
        build_repeated_checkpoint(runner, context, status="complete"),
        checkpoint_path,
    )
    report = build_repeated_report(runner, context)
    print(json.dumps(report["aggregate"], indent=2, ensure_ascii=False))
    if args.report:
        stem = f"vision-repeated-{started_at}"
        for kind, path in write_repeated_reports(report, args.output, stem).items():
            print(f"[report] {kind}: {path}")
    print(f"[checkpoint] complete: {checkpoint_path}")
    return 0


def _print_progress(event: dict) -> None:
    label = f"{event['variant']}/{event['homography']}"
    if event["status"] == "starting":
        print(
            f"[progress] {event['completed']}/{event['total']} — "
            f"démarrage passe {event['run_index']} ordre {event['order_index']} "
            f"{label}",
            flush=True,
        )
        return
    print(
        f"[progress] {event['completed']}/{event['total']} — {label} terminé "
        f"en {event['wall_time_s']:.2f}s",
        flush=True,
    )


def _homographies(selection: str) -> list[str]:
    values = [part.strip().lower() for part in selection.split(",")]
    if values == ["all"]:
        return ["ransac", "magsac"]
    allowed = {"ransac", "magsac", "usac_magsac"}
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise ValueError(f"Homographies inconnues: {', '.join(unknown)}")
    return values


def _load_mapping(path: str) -> dict:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Configuration introuvable: {source}")
    loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration invalide (mapping attendu): {source}")
    return loaded


if __name__ == "__main__":
    raise SystemExit(main())
