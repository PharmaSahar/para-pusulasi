"""CLI-safe one-shot runner for research replay engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .research_replay import replay_research_events_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay research JSONL events once.")
    parser.add_argument("--research-root", default="research", help="Research event store root path.")
    parser.add_argument("--source", default=None, help="Optional source filter.")
    parser.add_argument("--schema-version", type=int, default=None, help="Optional schema version filter.")
    parser.add_argument("--observed-at-from", default=None, help="Optional observed_at lower bound (ISO).")
    parser.add_argument("--observed-at-to", default=None, help="Optional observed_at upper bound (ISO).")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    summary = replay_research_events_once(
        research_root=Path(args.research_root),
        source=args.source,
        schema_version=args.schema_version,
        observed_at_from=args.observed_at_from,
        observed_at_to=args.observed_at_to,
    )

    if args.pretty:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
