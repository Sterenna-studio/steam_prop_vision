"""CLI du benchmark L1 v2, sans effet sur le runtime STYX."""

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

from steamcore.recognition.benchmark.l1 import (  # noqa: E402
    L1_STRATEGIES,
    NormalizedROI,
)
from steamcore.recognition.benchmark.l1_report import (  # noqa: E402
    L1ReportContext,
    build_l1_report,
    write_l1_reports,
)
from steamcore.recognition.benchmark.l1_runner import (  # noqa: E402
    L1BenchmarkOptions,
    L1BenchmarkRunner,
)
from steamcore.recognition.benchmark.variants import get_variants  # noqa: E402
from steamcore.recognition.thresholds import RecognitionThresholds  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare les stratégies L1 v2 sur un corpus commun."
    )
    parser.add_argument("--corpus", default="benchmark/corpus")
    parser.add_argument("--templates", default="PLATEST")
    parser.add_argument("--strategy", default="all")
    parser.add_argument("--variant", choices=("A", "B", "C"), default="A")
    parser.add_argument(
        "--homography", choices=("ransac", "magsac", "usac_magsac"), default="magsac"
    )
    parser.add_argument("--calibrated-roi", default="auto", metavar="auto|x,y,w,h")
    parser.add_argument("--calibration-condition", default="frontal")
    parser.add_argument("--calibration-margin", type=float, default=0.04)
    parser.add_argument("--quality-threshold", type=float, default=0.55)
    parser.add_argument("--tracking-threshold", type=float, default=0.35)
    parser.add_argument("--object", dest="object_id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-k", type=int, choices=(1, 2), default=2)
    parser.add_argument("--top2-margin", type=float, default=0.10)
    parser.add_argument("--hold-ms", type=int)
    parser.add_argument("--consec-frames", type=int)
    parser.add_argument("--miss-grace", type=int)
    parser.add_argument(
        "--camera-rotation", type=int, choices=(0, 90, 180, 270), default=0
    )
    parser.add_argument("--config", default="config/features.yaml")
    parser.add_argument("--hardware")
    parser.add_argument("--camera-parameters")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--output", default="benchmark/reports")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = _load_mapping(args.config)
    thresholds = RecognitionThresholds.from_config(config, legacy_default=0.20)
    strategies = _strategies(args.strategy)
    calibrated_roi = (
        None
        if args.calibrated_roi.lower() == "auto"
        else NormalizedROI.parse(args.calibrated_roi)
    )
    options = L1BenchmarkOptions(
        corpus=args.corpus,
        templates=args.templates,
        strategies=tuple(strategies),
        top_k=args.top_k,
        top2_margin=args.top2_margin,
        limit=args.limit,
        object_id=args.object_id,
        verbose=args.verbose,
        l3_min_matches=int(config.get("card_min_matches", 12)),
        fast_min_area=int(config.get("card_min_area", 4000)),
        camera_rotation=args.camera_rotation,
        calibrated_roi=calibrated_roi,
        auto_calibrate_roi=calibrated_roi is None,
        calibration_condition=args.calibration_condition,
        calibration_margin=args.calibration_margin,
        quality_threshold=args.quality_threshold,
        tracking_threshold=args.tracking_threshold,
        hold_ms=args.hold_ms
        if args.hold_ms is not None
        else int(config.get("card_hold_ms", 1000)),
        consecutive_frames=args.consec_frames
        if args.consec_frames is not None
        else int(config.get("card_consec_frames", 1)),
        miss_grace_frames=args.miss_grace
        if args.miss_grace is not None
        else int(config.get("card_miss_grace_frames", 5)),
    )
    runner = L1BenchmarkRunner(
        get_variants(args.variant)[0], args.homography, options, thresholds
    )
    metrics = runner.run()
    calibration = runner.calibration
    resolved_roi = calibrated_roi or (calibration.roi if calibration else None)
    report = build_l1_report(
        metrics,
        L1ReportContext(
            corpus=str(Path(args.corpus).resolve()),
            templates=str(Path(args.templates).resolve()),
            recognition_variant=args.variant,
            homography=args.homography,
            strategies=strategies,
            calibrated_roi=resolved_roi.to_dict() if resolved_roi else None,
            calibration_samples_seen=calibration.samples_seen if calibration else None,
            calibration_detections_used=(
                calibration.detections_used if calibration else None
            ),
            quality_threshold=args.quality_threshold,
            tracking_threshold=args.tracking_threshold,
            hold_ms=options.hold_ms,
            consecutive_frames=options.consecutive_frames,
            miss_grace_frames=options.miss_grace_frames,
            top_k=args.top_k,
            top2_margin=args.top2_margin,
            camera_rotation=args.camera_rotation,
            hardware=args.hardware,
            camera_parameters=(
                _load_mapping(args.camera_parameters)
                if args.camera_parameters
                else None
            ),
        ),
    )
    print(json.dumps(report["strategies"], indent=2, ensure_ascii=False))
    if args.report:
        stem = datetime.now(timezone.utc).strftime("vision-l1-v2-%Y%m%dT%H%M%SZ")
        for kind, path in write_l1_reports(report, args.output, stem).items():
            print(f"[report] {kind}: {path}")
    if not metrics.rows:
        print("N/A — corpus terrain requis (aucun échantillon trouvé).")
    return 0


def _strategies(selection: str) -> list[str]:
    values = [part.strip().lower() for part in selection.split(",")]
    if values == ["all"]:
        return list(L1_STRATEGIES)
    unknown = [value for value in values if value not in L1_STRATEGIES]
    if unknown:
        raise ValueError(f"Stratégies L1 inconnues: {', '.join(unknown)}")
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
