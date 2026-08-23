"""Capture guidée du corpus benchmark via le flux MJPEG de STYX."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steamcore.recognition.benchmark.capture import (  # noqa: E402
    CaptureOptions,
    capture_mjpeg_session,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture des images terrain sans prendre le contrôle de Picamera2."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--object", dest="object_id", help="Ex: plate_cellule")
    target.add_argument(
        "--negative",
        action="store_true",
        help="Capture sans objet attendu pour mesurer les faux positifs",
    )
    parser.add_argument("--condition", required=True, help="Ex: frontal, occlusion")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--countdown", type=float, default=3.0)
    parser.add_argument("--severity")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--stream", default="http://127.0.0.1:5050/stream", dest="stream_url"
    )
    parser.add_argument("--corpus", default=".runtime/benchmark-corpus")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    object_id = None if args.negative else args.object_id
    label = object_id or "NEGATIF"
    print(
        f"Capture {label}/{args.condition} dans {args.countdown:g} s "
        f"pendant {args.duration:g} s...",
        flush=True,
    )
    try:
        result = capture_mjpeg_session(
            CaptureOptions(
                corpus=Path(args.corpus),
                object_id=object_id,
                condition=args.condition,
                duration_s=args.duration,
                fps=args.fps,
                stream_url=args.stream_url,
                countdown_s=args.countdown,
                severity=args.severity,
                notes=args.notes,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 1

    print(
        f"OK: {result.frames_saved} images en {result.elapsed_s:.1f} s -> "
        f"{result.directory}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
