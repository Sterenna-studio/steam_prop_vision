"""Assistant CLI de capture de hard negatives depuis le flux STYX."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from steamcore.recognition.benchmark.hard_negatives import (  # noqa: E402
    DEFAULT_HARD_NEGATIVES,
    run_guided_hard_negative_capture,
    select_hard_negative_scenarios,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture guidée de scènes négatives difficiles via /stream."
    )
    parser.add_argument("--scenarios", default="all")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--countdown", type=float, default=3.0)
    parser.add_argument("--stream", default="http://127.0.0.1:5050/stream")
    parser.add_argument("--corpus", default=".runtime/benchmark-corpus")
    parser.add_argument("--list", action="store_true", dest="list_scenarios")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_scenarios:
        for scenario in DEFAULT_HARD_NEGATIVES:
            print(f"{scenario.condition}: {scenario.prompt}")
        return 0
    scenarios = select_hard_negative_scenarios(args.scenarios)
    print(
        "IMPORTANT: aucune plaque connue de PLATEST ne doit être visible dans "
        "une capture négative. Utiliser s pour passer un objet indisponible."
    )
    try:
        results = run_guided_hard_negative_capture(
            scenarios,
            corpus=args.corpus,
            stream_url=args.stream,
            duration_s=args.duration,
            fps=args.fps,
            countdown_s=args.countdown,
            repetitions=args.repetitions,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 1
    print(
        f"Terminé: {sum(result.frames_saved for result in results)} frame(s), "
        f"{len(results)} séquence(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
