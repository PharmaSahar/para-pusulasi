#!/usr/bin/env python3
"""Read-only fleet analytics credential preflight.

This script checks the active analytics token contract for each active channel.
It never writes credentials, never triggers OAuth, and never prints token content.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics_token_policy import (  # noqa: E402
    CANONICAL_ANALYTICS_TOKEN_ROOT,
    NONCANONICAL_ANALYTICS_TOKEN_PATH,
    canonical_analytics_token_path,
    resolve_analytics_token_path,
)
from src.channel_manager import get_channel, load_registry  # noqa: E402

ANALYTICS_SCOPES = (
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
)

RESULT_PASS = "PASS"
RESULT_TOKEN_MISSING = "TOKEN_MISSING"
RESULT_NONCANONICAL_PATH = "NONCANONICAL_PATH"
RESULT_INVALID_PERMISSIONS = "INVALID_PERMISSIONS"
RESULT_INVALID_OWNER = "INVALID_OWNER"
RESULT_SYMLINK_FORBIDDEN = "SYMLINK_FORBIDDEN"
RESULT_TOKEN_INVALID = "TOKEN_INVALID"
RESULT_SCOPE_INSUFFICIENT = "SCOPE_INSUFFICIENT"
RESULT_UPLOADER_TOKEN_REUSE = "UPLOADER_TOKEN_REUSE"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    channel_slug: str
    youtube_channel_id: str
    status: str
    token_path: str
    uploader_token_path: str
    detail: str


@dataclass(frozen=True, slots=True)
class _StatInfo:
    mode: int
    uid: int
    gid: int
    dev: int
    ino: int



def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}



def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}



def _active_channel_slugs() -> list[str]:
    registry = load_registry()
    channels = dict(registry.get("channels") or {})
    out: list[str] = []
    for channel_slug, payload in channels.items():
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "").strip().lower() != "active":
            continue
        if not str(payload.get("youtube_channel_id") or "").strip():
            continue
        out.append(str(channel_slug))
    return sorted(out)



def _stat_info(path: Path, *, stat_fn: Callable[[Path], os.stat_result] = os.stat) -> _StatInfo:
    st = stat_fn(path)
    return _StatInfo(
        mode=int(st.st_mode),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
        dev=int(st.st_dev),
        ino=int(st.st_ino),
    )



def _same_inode(left: _StatInfo, right: _StatInfo) -> bool:
    return left.dev == right.dev and left.ino == right.ino



def _credentials_scope_ok(credentials: object) -> bool:
    if credentials is None:
        return False
    try:
        has_scopes = getattr(credentials, "has_scopes", None)
        if callable(has_scopes):
            return bool(has_scopes(ANALYTICS_SCOPES))
    except Exception:
        return False
    credential_scopes = {str(scope) for scope in (getattr(credentials, "scopes", None) or [])}
    return any(scope in credential_scopes for scope in ANALYTICS_SCOPES)



def _describe_result(result: PreflightResult) -> str:
    return (
        f"{result.channel_slug:24} | {result.status:24} | "
        f"token={result.token_path} | uploader={result.uploader_token_path} | {result.detail}"
    )



def inspect_channel(
    channel_slug: str,
    *,
    stat_fn: Callable[[Path], os.stat_result] = os.stat,
    load_credentials_fn: Callable[[Any], object] = pickle.load,
    open_fn: Callable[..., Any] = open,
    channel_resolver=get_channel,
) -> PreflightResult:
    cfg = channel_resolver(channel_slug)
    youtube_channel_id = str(getattr(cfg, "youtube_channel_id", "") or "").strip()
    if not youtube_channel_id:
        return PreflightResult(channel_slug, "", RESULT_TOKEN_INVALID, "", "", "missing_youtube_channel_id")

    try:
        token_path = resolve_analytics_token_path(
            channel_slug=channel_slug,
            configured_path=str(getattr(cfg, "youtube_analytics_token_path", "") or "").strip() or None,
        )
    except RuntimeError as exc:
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_NONCANONICAL_PATH, "", "", str(exc))

    uploader_token_path = Path(str(getattr(cfg, "token_path", "") or "").strip())
    if not token_path.exists():
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_TOKEN_MISSING, str(token_path), str(uploader_token_path), "missing_canonical_token")
    if token_path.is_symlink():
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_SYMLINK_FORBIDDEN, str(token_path), str(uploader_token_path), "token_path_is_symlink")
    if not token_path.is_file():
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_TOKEN_INVALID, str(token_path), str(uploader_token_path), "token_path_not_regular_file")
    if not str(token_path.resolve()).startswith(str(CANONICAL_ANALYTICS_TOKEN_ROOT.resolve())):
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_NONCANONICAL_PATH, str(token_path), str(uploader_token_path), "token_path_outside_canonical_root")

    try:
        info = _stat_info(token_path, stat_fn=stat_fn)
    except Exception as exc:
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_TOKEN_INVALID, str(token_path), str(uploader_token_path), f"stat_failed:{exc}")

    if info.uid != 0 or info.gid != 0:
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_INVALID_OWNER, str(token_path), str(uploader_token_path), f"uid={info.uid} gid={info.gid}")
    if stat.S_IMODE(info.mode) != 0o600:
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_INVALID_PERMISSIONS, str(token_path), str(uploader_token_path), f"mode={oct(stat.S_IMODE(info.mode))}")

    try:
        with open_fn(token_path, "rb") as handle:
            credentials = load_credentials_fn(handle)
    except Exception as exc:
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_TOKEN_INVALID, str(token_path), str(uploader_token_path), f"pickle_load_failed:{exc}")

    if not getattr(credentials, "refresh_token", None):
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_TOKEN_INVALID, str(token_path), str(uploader_token_path), "missing_refresh_token")
    if not _credentials_scope_ok(credentials):
        return PreflightResult(channel_slug, youtube_channel_id, RESULT_SCOPE_INSUFFICIENT, str(token_path), str(uploader_token_path), "missing_analytics_scope")

    if uploader_token_path.exists():
        try:
            uploader_info = _stat_info(uploader_token_path, stat_fn=stat_fn)
            if token_path.resolve() == uploader_token_path.resolve() or _same_inode(info, uploader_info):
                return PreflightResult(channel_slug, youtube_channel_id, RESULT_UPLOADER_TOKEN_REUSE, str(token_path), str(uploader_token_path), "shares_inode_or_path_with_uploader_token")
        except Exception:
            pass

    return PreflightResult(channel_slug, youtube_channel_id, RESULT_PASS, str(token_path), str(uploader_token_path), "ok")



def run_preflight(
    *,
    stat_fn: Callable[[Path], os.stat_result] = os.stat,
    load_credentials_fn: Callable[[Any], object] = pickle.load,
    open_fn: Callable[..., Any] = open,
    channel_resolver=get_channel,
) -> dict[str, Any]:
    results: list[PreflightResult] = []
    for channel_slug in _active_channel_slugs():
        try:
            results.append(
                inspect_channel(
                    channel_slug,
                    stat_fn=stat_fn,
                    load_credentials_fn=load_credentials_fn,
                    open_fn=open_fn,
                    channel_resolver=channel_resolver,
                )
            )
        except Exception as exc:
            results.append(
                PreflightResult(
                    channel_slug=channel_slug,
                    youtube_channel_id="",
                    status=RESULT_TOKEN_INVALID,
                    token_path="",
                    uploader_token_path="",
                    detail=f"inspection_failed:{exc}",
                )
            )

    failing = [result for result in results if result.status != RESULT_PASS]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_analytics_token_root": str(CANONICAL_ANALYTICS_TOKEN_ROOT),
        "active_channel_count": len(results),
        "pass_count": sum(1 for result in results if result.status == RESULT_PASS),
        "fail_count": len(failing),
        "results": [asdict(result) for result in results],
        "overall_status": RESULT_PASS if not failing else "FAIL",
    }
    return report



def _print_table(results: list[dict[str, Any]]) -> None:
    print("CHANNEL                   | STATUS                   | TOKEN | UPLOADER | DETAIL")
    print("-" * 92)
    for row in results:
        print(
            f"{str(row.get('channel_slug') or ''):24} | "
            f"{str(row.get('status') or ''):24} | "
            f"{str(row.get('token_path') or '')} | "
            f"{str(row.get('uploader_token_path') or '')} | "
            f"{str(row.get('detail') or '')}"
        )



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only analytics credential preflight")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(argv)

    report = run_preflight()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_table(report["results"])
        print(json.dumps({"overall_status": report["overall_status"], "pass_count": report["pass_count"], "fail_count": report["fail_count"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == RESULT_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
