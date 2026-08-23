"""CLI reproductible de benchmark multi-backends S.T.E.A.M Vision."""

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

from steamcore.recognition.benchmark.report import (  # noqa: E402
    ReportContext,
    build_report,
    write_reports,
)
from steamcore.recognition.benchmark.runner import (  # noqa: E402
    BenchmarkOptions,
    VisionBenchmarkRunner,
)
from steamcore.recognition.benchmark.variants import get_variants  # noqa: E402
from steamcore.recognition.thresholds import RecognitionThresholds  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rejoue un même corpus sur les variantes vision A à E."
    )
    parser.add_argument("--corpus", default="benchmark/corpus")
    parser.add_argument("--templates", default="PLATEST")
    parser.add_argument("--variant", "--variants", default="all")
    parser.add_argument("--homography", default="all")
    parser.add_argument("--object", dest="object_id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-k", type=int, choices=(1, 2), default=2)
    parser.add_argument("--top2-margin", type=float, default=0.10)
    parser.add_argument("--roi-mode", choices=("l1", "full", "hybrid"), default="l1")
    parser.add_argument(
        "--camera-rotation",
        type=int,
        choices=(0, 90, 180, 270),
        default=0,
        help="Rotation à appliquer au corpus brut ; 0 rejoue les fichiers tels quels",
    )
    parser.add_argument("--config", default="config/features.yaml")
    parser.add_argument("--appearance-threshold", type=float, default=0.55)
    parser.add_argument("--hardware")
    parser.add_argument("--camera-parameters")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--output", default="benchmark/reports")
    parser.add_argument("--save-failures", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    variants = get_variants(args.variant)
    homographies = _homographies(args.homography)
    config = _load_mapping(args.config)
    thresholds = RecognitionThresholds.from_config(config, legacy_default=0.20)
    camera_rotation = args.camera_rotation
    failure_dir = str(Path(args.output) / "failures") if args.save_failures else None
    options = BenchmarkOptions(
        corpus=args.corpus,
        templates=args.templates,
        roi_mode=args.roi_mode,
        top_k=args.top_k,
        top2_margin=args.top2_margin,
        limit=args.limit,
        object_id=args.object_id,
        verbose=args.verbose,
        save_failures=failure_dir,
        appearance_threshold=args.appearance_threshold,
        orb_threshold=thresholds.default_threshold,
        l3_min_matches=int(config.get("card_min_matches", 12)),
        fast_min_area=int(config.get("card_min_area", 4000)),
        camera_rotation=camera_rotation,
    )
    runner = VisionBenchmarkRunner(variants, homographies, options, thresholds)
    metrics = runner.run()
    report = build_report(
        metrics,
        ReportContext(
            corpus=str(Path(args.corpus).resolve()),
            templates=str(Path(args.templates).resolve()),
            roi_mode=args.roi_mode,
            top_k=args.top_k,
            top2_margin=args.top2_margin,
            camera_rotation=camera_rotation,
            hardware=args.hardware,
            camera_parameters=_load_mapping(args.camera_parameters)
            if args.camera_parameters
            else None,
        ),
    )
    print(json.dumps(report["variants"], indent=2, ensure_ascii=False))
    if args.report:
        stem = datetime.now(timezone.utc).strftime("vision-benchmark-%Y%m%dT%H%M%SZ")
        paths = write_reports(report, args.output, stem)
        for kind, path in paths.items():
            print(f"[report] {kind}: {path}")
    if not metrics.rows:
        print("N/A — corpus terrain requis (aucun échantillon trouvé).")
    return 0


def _homographies(selection: str) -> list[str]:
    values = [part.strip().lower() for part in selection.split(",")]
    if values == ["all"]:
        return ["ransac", "magsac"]
    allowed = {"ransac", "magsac", "usac_magsac"}
    unknown = [value for value in values if value not in allowed]
    if unknown:
        raise ValueError(f"Homographies inconnues: {', '.join(unknown)}")
    return values


def _load_mapping(path: str | None) -> dict:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Configuration introuvable: {source}")
    loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration invalide (mapping attendu): {source}")
    return loaded


if __name__ == "__main__":
    raise SystemExit(main())
