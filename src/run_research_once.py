"""CLI-safe manual runner for passive research scheduler.

This command is intentionally one-shot. It does not schedule itself,
start a daemon, or change production flows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .research_scheduler import run_research_collectors_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run passive research collectors once.")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Seed query for google_trends collector. Repeat for multiple queries.",
    )
    parser.add_argument(
        "--research-root",
        default="research",
        help="Research event-store root directory.",
    )
    parser.add_argument(
        "--observed-at",
        default=None,
        help="Optional ISO timestamp to stamp observations.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print formatted JSON output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    collector_inputs = {
        "google_trends": {
            "queries": args.query,
        }
    }

    try:
        summary = run_research_collectors_once(
            collector_inputs=collector_inputs,
            research_root=Path(args.research_root),
            observed_at_utc=args.observed_at,
        )
    except Exception as exc:
        error_payload = {
            "status": "failed",
            "error": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=False, sort_keys=True))
        return 1

    if args.pretty:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
