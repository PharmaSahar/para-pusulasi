#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.production_quality_platform import export_runtime_dashboard_to_docs


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicitly export runtime dashboard markdown into docs")
    parser.add_argument("--source", default="", help="Optional runtime markdown source path")
    parser.add_argument("--target", default="", help="Optional docs target path")
    args = parser.parse_args()

    source_path = Path(args.source).resolve() if args.source else None
    target_path = Path(args.target).resolve() if args.target else None

    result = export_runtime_dashboard_to_docs(source_path=source_path, docs_path=target_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
