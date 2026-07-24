from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping, Protocol

from .analytics_snapshot_foundation import (
    AnalyticsSnapshotRecord,
    AnalyticsSnapshotStoreError,
    AnalyticsSnapshotValidationError,
    build_snapshot_id,
    canonicalize_snapshot_payload,
)


class FileOperations(Protocol):
    def mkdir(self, path: Path) -> None:
        ...

    def exists(self, path: Path) -> bool:
        ...

    def read_text(self, path: Path) -> str:
        ...

    def write_text(self, path: Path, content: str) -> None:
        ...

    def replace(self, source: Path, destination: Path) -> None:
        ...

    def unlink(self, path: Path) -> None:
        ...


class LocalFileOperations:
    def mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def exists(self, path: Path) -> bool:
        return path.exists()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def unlink(self, path: Path) -> None:
        path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class SnapshotWriteResult:
    channel_id: str
    persisted_count: int
    duplicate_count: int
    total_requested: int
    snapshot_ids: tuple[str, ...]
    ledger_path: str

    def __post_init__(self) -> None:
        if not str(self.channel_id or "").strip():
            raise ValueError("channel_id is required")
        if int(self.persisted_count) < 0:
            raise ValueError("persisted_count must be nonnegative")
        if int(self.duplicate_count) < 0:
            raise ValueError("duplicate_count must be nonnegative")
        if int(self.total_requested) < 0:
            raise ValueError("total_requested must be nonnegative")
        if int(self.persisted_count) + int(self.duplicate_count) != int(self.total_requested):
            raise ValueError("persisted_count + duplicate_count must equal total_requested")
        object.__setattr__(self, "snapshot_ids", tuple(self.snapshot_ids))


class SnapshotValidator:
    """Validates and canonicalizes snapshot payloads using the B1 contract."""

    def validate(self, payload: Mapping[str, Any]) -> AnalyticsSnapshotRecord:
        provided_snapshot_date = str(payload.get("snapshot_date") or "").strip()
        canonical = canonicalize_snapshot_payload(dict(payload))

        provided_id = str(payload.get("snapshot_id") or "").strip()
        derived_id = build_snapshot_id(canonical)
        if provided_id and provided_id != derived_id:
            raise AnalyticsSnapshotValidationError("snapshot_id mismatch")

        expected_snapshot_date = canonical["snapshot_timestamp"][:10]
        if provided_snapshot_date and provided_snapshot_date != expected_snapshot_date:
            raise AnalyticsSnapshotValidationError("snapshot_date does not match snapshot_timestamp")

        if canonical["snapshot_date"] != expected_snapshot_date:
            raise AnalyticsSnapshotValidationError("snapshot_date does not match snapshot_timestamp")

        normalized_payload = self._record_payload(canonical)
        return AnalyticsSnapshotRecord(**normalized_payload)

    def _record_payload(self, canonical: Mapping[str, Any]) -> dict[str, Any]:
        record_data: dict[str, Any] = {}
        for field in fields(AnalyticsSnapshotRecord):
            if field.name == "missing_fields":
                record_data[field.name] = list(canonical.get(field.name) or [])
            else:
                record_data[field.name] = canonical.get(field.name)
        return record_data


class AnalyticsSnapshotWriter:
    """Atomic, idempotent writer for analytics snapshot records."""

    def __init__(
        self,
        *,
        root: str | os.PathLike[str] | Path,
        validator: SnapshotValidator | None = None,
        file_ops: FileOperations | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._validator = validator or SnapshotValidator()
        self._file_ops = file_ops or LocalFileOperations()

    def write_channel_snapshots(
        self,
        *,
        channel_id: str,
        snapshots: tuple[Mapping[str, Any], ...],
    ) -> SnapshotWriteResult:
        normalized_channel_id = str(channel_id or "").strip()
        if not normalized_channel_id:
            raise AnalyticsSnapshotValidationError("channel_id is required")

        channel_dir = self._root / normalized_channel_id
        ledger_path = channel_dir / "snapshots.jsonl"
        temp_path = channel_dir / "snapshots.jsonl.tmp"

        records = [self._validator.validate(payload) for payload in snapshots]
        self._ensure_channel_consistency(normalized_channel_id, records)

        self._file_ops.mkdir(channel_dir)
        existing_rows = self._load_rows(ledger_path)
        existing_by_id = {str(row.get("snapshot_id")): row for row in existing_rows}

        pending_rows: dict[str, dict[str, Any]] = {}
        duplicate_count = 0

        for record in records:
            row = record.to_payload()
            snapshot_id = row["snapshot_id"]

            existing = existing_by_id.get(snapshot_id)
            if existing is not None:
                if existing != row:
                    raise AnalyticsSnapshotStoreError("conflicting snapshot already exists")
                duplicate_count += 1
                continue

            staged = pending_rows.get(snapshot_id)
            if staged is not None:
                if staged != row:
                    raise AnalyticsSnapshotStoreError("conflicting duplicate snapshot in request")
                duplicate_count += 1
                continue

            pending_rows[snapshot_id] = row

        appended_rows = [pending_rows[key] for key in sorted(pending_rows.keys())]
        final_rows = list(existing_rows) + appended_rows

        self._atomic_write(ledger_path=ledger_path, temp_path=temp_path, rows=final_rows)

        return SnapshotWriteResult(
            channel_id=normalized_channel_id,
            persisted_count=len(appended_rows),
            duplicate_count=duplicate_count,
            total_requested=len(records),
            snapshot_ids=tuple(item["snapshot_id"] for item in appended_rows),
            ledger_path=str(ledger_path),
        )

    def _ensure_channel_consistency(self, channel_id: str, records: list[AnalyticsSnapshotRecord]) -> None:
        for record in records:
            if record.channel_id != channel_id:
                raise AnalyticsSnapshotValidationError("channel mismatch")

    def _load_rows(self, ledger_path: Path) -> list[dict[str, Any]]:
        if not self._file_ops.exists(ledger_path):
            return []

        rows: list[dict[str, Any]] = []
        content = self._file_ops.read_text(ledger_path)
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AnalyticsSnapshotStoreError("malformed ledger content") from exc
            if not isinstance(parsed, dict):
                raise AnalyticsSnapshotStoreError("malformed ledger content")
            validated = self._validator.validate(parsed)
            rows.append(validated.to_payload())
        return rows

    def _atomic_write(self, *, ledger_path: Path, temp_path: Path, rows: list[dict[str, Any]]) -> None:
        serialized = "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows
        )
        if serialized:
            serialized += "\n"

        try:
            self._file_ops.write_text(temp_path, serialized)
            self._file_ops.replace(temp_path, ledger_path)
        except Exception:
            self._file_ops.unlink(temp_path)
            raise


__all__ = [
    "AnalyticsSnapshotWriter",
    "FileOperations",
    "LocalFileOperations",
    "SnapshotValidator",
    "SnapshotWriteResult",
]
