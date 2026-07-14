from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cqga_real_world_revalidation import run_cqga_real_world_revalidation  # noqa: E402


def main() -> None:
    summary = run_cqga_real_world_revalidation(repository_root=PROJECT_ROOT)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
