#!/usr/bin/env python3
"""Read-only detector for legacy analytics token drift.

Scans operator, release, and current-root trees for analytics tokens outside the
canonical shared analytics token root. Optional allowlist entries can suppress a
known, time-bounded rollback copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics_token_policy import CANONICAL_ANALYTICS_TOKEN_ROOT, canonical_analytics_token_path  # noqa: E402

LEGACY_ALLOWLIST_PATH = Path("/opt/parapusulasi-shared/state/analytics_token_legacy_allowlist.json")
SCAN_ROOTS = (
    Path("/opt/parapusulasi/channels"),
    Path("/opt/parapusulasi/releases"),
    Path("/opt/parapusulasi-current"),
)
TOKEN_NAMES = {
    "youtube_analytics_token.pickle",
    "token_analytics.json",
}

RESULT_PASS = "PASS"
RESULT_DETECTED = "LEGACY_ANALYTICS_TOKEN_DETECTED"
RESULT_ALLOWLISTED = "ALLOWLISTED"
RESULT_ALLOWLIST_EXPIRED = "ALLOWLIST_EXPIRED"


@dataclass(frozen=True, slots=True)
class DriftFinding:
    channel_slug: str
    legacy_path: str
    sha256: str
    status: str
    reason: str
    expires_at: str | None
    allowlist_reason: str | None



def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



def _load_allowlist() -> list[dict[str, Any]]:
    if not LEGACY_ALLOWLIST_PATH.exists():
        return []
    try:
        payload = json.loads(LEGACY_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if isinstance(payload, dict):
        entries = payload.get("entries")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []



def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)



def _allowlist_match(channel_slug: str, legacy_path: Path, sha256: str) -> tuple[str, str | None]:
    now = datetime.now(timezone.utc)
    for entry in _load_allowlist():
        if str(entry.get("channel_slug") or "").strip() != channel_slug:
            continue
        if str(entry.get("legacy_path") or "").strip() != str(legacy_path):
            continue
        if str(entry.get("sha256") or "").strip() != sha256:
            continue
        expires_at = str(entry.get("expires_at") or "").strip() or None
        if expires_at:
            parsed = _parse_iso(expires_at)
            if parsed is None or parsed < now:
                return RESULT_ALLOWLIST_EXPIRED, expires_at
        return RESULT_ALLOWLISTED, expires_at
    return RESULT_DETECTED, None



def _channel_slug_from_path(path: Path) -> str:
    parts = path.parts
    if "channels" in parts:
        idx = parts.index("channels")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""



def _candidate_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    for name in TOKEN_NAMES:
        candidates.extend([path for path in root.rglob(name) if path.is_file() or path.is_symlink()])
    return sorted({path.resolve() for path in candidates})



def inspect_legacy_tokens() -> dict[str, Any]:
    findings: list[DriftFinding] = []
    canonical_root = CANONICAL_ANALYTICS_TOKEN_ROOT.resolve()
    allowlist_path = str(LEGACY_ALLOWLIST_PATH)

    for scan_root in SCAN_ROOTS:
        for path in _candidate_paths(scan_root):
            try:
                if path.is_relative_to(canonical_root):
                    continue
            except AttributeError:
                if str(path).startswith(str(canonical_root)):
                    continue

            channel_slug = _channel_slug_from_path(path)
            sha256 = _sha256(path)
            status, expires_at = _allowlist_match(channel_slug, path, sha256)
            if status == RESULT_ALLOWLISTED:
                findings.append(
                    DriftFinding(
                        channel_slug=channel_slug,
                        legacy_path=str(path),
                        sha256=sha256,
                        status=status,
                        reason="legacy_path_allowlisted",
                        expires_at=expires_at,
                        allowlist_reason="allowlisted_rollback_copy",
                    )
                )
                continue
            findings.append(
                DriftFinding(
                    channel_slug=channel_slug,
                    legacy_path=str(path),
                    sha256=sha256,
                    status=RESULT_DETECTED if status != RESULT_ALLOWLIST_EXPIRED else RESULT_DETECTED,
                    reason=status if status != RESULT_ALLOWLIST_EXPIRED else "allowlist_expired",
                    expires_at=expires_at,
                    allowlist_reason=None,
                )
            )

    failing = [finding for finding in findings if finding.status != RESULT_ALLOWLISTED]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_analytics_token_root": str(canonical_root),
        "allowlist_path": allowlist_path,
        "scan_roots": [str(root) for root in SCAN_ROOTS],
        "findings": [asdict(finding) for finding in findings],
        "overall_status": RESULT_PASS if not failing else "FAIL",
        "detected_count": len(failing),
    }
    return report



def _print_table(findings: list[dict[str, Any]]) -> None:
    print("CHANNEL                   | STATUS                   | LEGACY PATH | SHA256 | DETAIL")
    print("-" * 120)
    for row in findings:
        print(
            f"{str(row.get('channel_slug') or ''):24} | {str(row.get('status') or ''):24} | "
            f"{str(row.get('legacy_path') or '')} | {str(row.get('sha256') or '')[:12]} | {str(row.get('reason') or '')}"
        )



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect legacy analytics token drift")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(argv)

    report = inspect_legacy_tokens()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_table(report["findings"])
        print(json.dumps({"overall_status": report["overall_status"], "detected_count": report["detected_count"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == RESULT_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
