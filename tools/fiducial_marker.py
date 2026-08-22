"""Génère un marqueur ArUco/AprilTag OpenCV en PNG et/ou SVG."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from steamcore.recognition.fiducials import OpenCVFiducialBackend  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default="DICT_4X4_50")
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--backend", choices=("aruco", "apriltag"), default="aruco")
    parser.add_argument("--png")
    parser.add_argument("--svg")
    parser.add_argument("--pixels", type=int, default=1024)
    parser.add_argument("--size-mm", type=float, default=80.0)
    parser.add_argument("--margin-mm", type=float, default=8.0)
    args = parser.parse_args(argv)
    if not args.png and not args.svg:
        parser.error("au moins --png ou --svg est requis")
    backend = OpenCVFiducialBackend(family=args.family, backend_name=args.backend)
    if args.png:
        print(backend.export_png(args.id, args.png, args.pixels))
    if args.svg:
        print(
            backend.export_svg(
                args.id, args.svg, size_mm=args.size_mm, margin_mm=args.margin_mm
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
