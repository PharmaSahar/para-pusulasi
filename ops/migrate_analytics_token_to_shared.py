#!/usr/bin/env python3
"""Idempotent migration utility for analytics tokens.

Copies a verified analytics token into the canonical shared token root using an
atomic replace. It never deletes the source token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics_token_policy import CANONICAL_ANALYTICS_TOKEN_ROOT, canonical_analytics_token_path  # noqa: E402

RESULT_PASS = "PASS"
RESULT_SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
RESULT_DESTINATION_CONFLICT = "DESTINATION_CONFLICT"
RESULT_SOURCE_INVALID = "SOURCE_INVALID"
RESULT_INVALID_TARGET = "INVALID_TARGET"
RESULT_DRY_RUN = "DRY_RUN"


@dataclass(frozen=True, slots=True)
class MigrationReport:
    channel_slug: str
    source: str
    destination: str
    source_sha256: str | None
    destination_sha256: str | None
    status: str
    detail: str
    applied: bool


@dataclass(frozen=True, slots=True)
class _StatInfo:
    mode: int
    uid: int
    gid: int
    dev: int
    ino: int



def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



def _is_regular_file(path: Path) -> bool:
    return path.exists() and path.is_file() and not path.is_symlink()


def _stat_info(path: Path, *, stat_fn: Callable[[str], os.stat_result] = os.stat) -> _StatInfo:
    st = stat_fn(str(path))
    return _StatInfo(
        mode=int(st.st_mode),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
        dev=int(st.st_dev),
        ino=int(st.st_ino),
    )


def _validate_root_owned_600(path: Path, *, stat_fn: Callable[[str], os.stat_result] = os.stat) -> None:
    info = _stat_info(path, stat_fn=stat_fn)
    if info.uid != 0 or info.gid != 0:
        raise PermissionError(f"invalid_owner:{path}")
    if stat.S_IMODE(info.mode) != 0o600:
        raise PermissionError(f"invalid_permissions:{path}")



def _ensure_dir_mode(path: Path, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)



def _ensure_file_mode(path: Path, mode: int = 0o600) -> None:
    os.chmod(path, mode)



def _validate_destination(path: Path, expected_hash: str) -> tuple[str | None, str]:
    if not path.exists():
        return None, "missing_destination"
    if not _is_regular_file(path):
        return None, "destination_not_regular_file"
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        return actual_hash, RESULT_DESTINATION_CONFLICT
    return actual_hash, RESULT_PASS



def migrate_analytics_token_to_shared(
    *,
    channel_slug: str,
    source: str,
    expected_sha256: str,
    dry_run: bool = False,
    apply: bool = False,
    copy_fn: Callable[[str, str], Any] = shutil.copy2,
    chmod_fn: Callable[[str, int], Any] = os.chmod,
    chown_fn: Callable[[str, int, int], Any] = os.chown,
    stat_fn: Callable[[str], os.stat_result] = os.stat,
) -> MigrationReport:
    if not apply and not dry_run:
        raise ValueError("either_dry_run_or_apply_required")

    source_path = Path(source)
    destination_path = canonical_analytics_token_path(channel_slug)

    if not _is_regular_file(source_path):
        return MigrationReport(channel_slug, str(source_path), str(destination_path), None, None, RESULT_SOURCE_INVALID, "source_not_regular_file", False)

    source_sha256 = _sha256(source_path)
    if source_sha256 != expected_sha256:
        return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, None, RESULT_SOURCE_HASH_MISMATCH, "source_hash_mismatch", False)

    if dry_run and not apply:
        return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, None, RESULT_DRY_RUN, "no_files_written", False)

    _ensure_dir_mode(destination_path.parent, 0o700)

    destination_sha256, destination_status = _validate_destination(destination_path, expected_sha256)
    if destination_status == RESULT_DESTINATION_CONFLICT:
        return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, destination_sha256, RESULT_DESTINATION_CONFLICT, "destination_hash_mismatch", False)
    if destination_status == RESULT_PASS:
        return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, destination_sha256, RESULT_PASS, "destination_already_matches", False)

    if dry_run and apply:
        return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, None, RESULT_DRY_RUN, "apply_not_executed", False)

    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{channel_slug}.", suffix=".tmp", dir=str(destination_path.parent))
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        copy_fn(str(source_path), str(tmp_path))
        try:
            chown_fn(str(tmp_path), 0, 0)
        except PermissionError:
            pass
        _ensure_file_mode(tmp_path, 0o600)
        _validate_root_owned_600(tmp_path, stat_fn=stat_fn)
        tmp_hash = _sha256(tmp_path)
        if tmp_hash != expected_sha256:
            return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, tmp_hash, RESULT_SOURCE_HASH_MISMATCH, "temporary_copy_hash_mismatch", False)
        os.replace(tmp_path, destination_path)
        final_hash = _sha256(destination_path)
        if final_hash != expected_sha256:
            return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, final_hash, RESULT_SOURCE_HASH_MISMATCH, "destination_hash_mismatch_after_replace", False)
        _ensure_file_mode(destination_path, 0o600)
        try:
            chown_fn(str(destination_path), 0, 0)
        except PermissionError:
            pass
        _validate_root_owned_600(destination_path, stat_fn=stat_fn)
        return MigrationReport(channel_slug, str(source_path), str(destination_path), source_sha256, final_hash, RESULT_PASS, "migrated", True)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate an analytics token into the canonical shared path")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    report = migrate_analytics_token_to_shared(
        channel_slug=args.channel,
        source=args.source,
        expected_sha256=args.expected_sha256,
        dry_run=bool(args.dry_run),
        apply=bool(args.apply),
    )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.status in {RESULT_PASS, RESULT_DRY_RUN} else 1


if __name__ == "__main__":
    raise SystemExit(main())
