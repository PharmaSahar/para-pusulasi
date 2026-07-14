from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.thumbnail_metadata_lineage import verify_thumbnail_metadata_lineage_integrity  # noqa: E402


def main() -> None:
    summary = verify_thumbnail_metadata_lineage_integrity()
    output_dir = PROJECT_ROOT / "artifacts/latest/project002_sprint1e_phase5_thumbnail_metadata_lineage"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "integrity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()