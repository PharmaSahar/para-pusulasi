"""CLI-safe one-shot runner for failed fact-check log auditing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .fact_check_audit import build_failed_fact_check_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize failed fact-check events from scheduler logs.")
    parser.add_argument(
        "--log-path",
        default="logs/production_scheduler.out",
        help="Scheduler log file to audit.",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=10,
        help="Maximum number of example failed events to include.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    summary = build_failed_fact_check_audit(Path(args.log_path), max_examples=args.max_examples)
    if args.pretty:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())