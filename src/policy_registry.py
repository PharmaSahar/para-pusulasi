from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .policy_registry_projection import build_policy_registry_projection_from_rows


POLICY_REGISTRY_SCHEMA_VERSION = "v1"
DEFAULT_POLICY_REGISTRY_PATH = Path("logs/policy_registry.jsonl")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PolicyRegistryRecord:
    schema_version: str
    policy_record_id: str
    policy_event_id: str
    policy_id: str
    policy_version: str
    policy_hash: str
    governing_rules: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    blocked_actions: tuple[str, ...]
    deprecated: bool
    previous_policy_hash: str | None
    created_at: str
    created_by: str
    source_module: str
    source_version: str
    previous_record_hash: str | None = None
    record_hash: str = ""

    def __post_init__(self) -> None:
        validate_policy_registry_row(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return validate_policy_registry_row(asdict(self))


@dataclass(frozen=True, slots=True)
class PolicyRegistryAppendResult:
    appended: bool
    duplicate: bool
    conflict: bool
    policy_record_id: str
    policy_event_id: str
    record_hash: str
    reason: str


@dataclass(frozen=True, slots=True)
class PolicyRegistryReplayDiagnostics:
    malformed_rows: int
    partial_trailing_rows: int
    duplicate_rows: int
    unsupported_schema_rows: int
    broken_hash_links: int
    replay_errors: list[str]


class PolicyRegistryError(RuntimeError):
    pass


class PolicyRegistryCorruptionError(PolicyRegistryError):
    pass


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _safe_text(value)
    return text or None


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _parse_iso(name: str, value: Any) -> str:
    text = _safe_text(value)
    if not text:
        raise ValueError(f"missing_field:{name}")
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def _normalize_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid_field:{name}")


def _normalize_string_list(name: str, value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"invalid_field:{name}")
    items = sorted({_safe_text(item) for item in value if _safe_text(item)})
    if len(items) != len(list(value)):
        raise ValueError(f"invalid_field:{name}")
    return tuple(items)


def _normalize_hex64(name: str, value: Any, *, allow_none: bool = False) -> str | None:
    text = _safe_text(value).lower()
    if not text and allow_none:
        return None
    if not _HEX64_RE.fullmatch(text):
        raise ValueError(f"invalid_field:{name}")
    return text


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": POLICY_REGISTRY_SCHEMA_VERSION,
        "policy_record_id": "",
        "policy_event_id": "",
        "policy_id": "",
        "policy_version": "",
        "policy_hash": "",
        "governing_rules": (),
        "allowed_actions": (),
        "blocked_actions": (),
        "deprecated": False,
        "previous_policy_hash": None,
        "created_at": "",
        "created_by": "",
        "source_module": "",
        "source_version": "",
        "previous_record_hash": None,
        "record_hash": "",
    }


def compute_policy_record_id(record: dict[str, Any]) -> str:
    payload = {
        "policy_id": _safe_text(record.get("policy_id")),
        "policy_version": _safe_text(record.get("policy_version")),
        "policy_hash": _safe_text(record.get("policy_hash")).lower(),
    }
    return "plr_" + _sha(_stable_json(payload))[:24]


def compute_policy_record_hash(record: dict[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    payload.pop("policy_event_id", None)
    payload.pop("created_at", None)
    payload.pop("previous_record_hash", None)
    return "plh_" + _sha(_stable_json(payload))[:24]


def compute_policy_event_id(record: dict[str, Any]) -> str:
    payload = {"policy_record_id": _safe_text(record.get("policy_record_id")), "record_hash": _safe_text(record.get("record_hash")), "deprecated": bool(record.get("deprecated", False))}
    return "ple_" + _sha(_stable_json(payload))[:24]


def validate_policy_registry_row(row: dict[str, Any], original_row: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(row))
    source = dict(original_row or row)
    if _safe_text(merged.get("schema_version")) != POLICY_REGISTRY_SCHEMA_VERSION:
        raise ValueError("invalid_field:schema_version")
    for key in ("policy_id", "policy_version", "created_by", "source_module", "source_version"):
        merged[key] = _safe_text(merged.get(key))
        if not merged[key]:
            raise ValueError(f"missing_field:{key}")
    merged["policy_hash"] = _normalize_hex64("policy_hash", merged.get("policy_hash"))
    merged["previous_policy_hash"] = _normalize_hex64("previous_policy_hash", merged.get("previous_policy_hash"), allow_none=True)
    merged["governing_rules"] = _normalize_string_list("governing_rules", merged.get("governing_rules"))
    merged["allowed_actions"] = _normalize_string_list("allowed_actions", merged.get("allowed_actions"))
    merged["blocked_actions"] = _normalize_string_list("blocked_actions", merged.get("blocked_actions"))
    if set(merged["allowed_actions"]) & set(merged["blocked_actions"]):
        raise ValueError("invalid_field:action_overlap")
    merged["deprecated"] = _normalize_bool("deprecated", merged.get("deprecated"))
    merged["created_at"] = _parse_iso("created_at", merged.get("created_at"))
    merged["previous_record_hash"] = _optional_text(merged.get("previous_record_hash"))
    expected_record_id = compute_policy_record_id(merged)
    supplied_record_id = _safe_text(source.get("policy_record_id"))
    if supplied_record_id and supplied_record_id != expected_record_id:
        raise ValueError("invalid_field:policy_record_id")
    merged["policy_record_id"] = expected_record_id
    expected_hash = compute_policy_record_hash(merged)
    supplied_hash = _safe_text(source.get("record_hash"))
    if supplied_hash and supplied_hash != expected_hash:
        raise ValueError("invalid_field:record_hash")
    merged["record_hash"] = expected_hash
    expected_event_id = compute_policy_event_id(merged)
    supplied_event_id = _safe_text(source.get("policy_event_id"))
    if supplied_event_id and supplied_event_id != expected_event_id:
        raise ValueError("invalid_field:policy_event_id")
    merged["policy_event_id"] = expected_event_id
    return merged


def build_policy_registry_record(payload: dict[str, Any], *, created_by: str, source_module: str, source_version: str, created_at: str | None = None, previous_record_hash: str | None = None) -> dict[str, Any]:
    merged = _defaults()
    merged.update(dict(payload))
    merged["created_by"] = created_by
    merged["source_module"] = source_module
    merged["source_version"] = source_version
    merged["created_at"] = created_at or datetime.now(timezone.utc).isoformat()
    merged["previous_record_hash"] = previous_record_hash
    return validate_policy_registry_row(merged, original_row=payload)


def _dedupe_signature(record: dict[str, Any]) -> str:
    def _strip(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if key in {"record_hash", "policy_event_id", "created_at", "previous_record_hash"}:
                    continue
                out[key] = _strip(item)
            return out
        if isinstance(value, (list, tuple)):
            return [_strip(item) for item in value]
        return value
    return _stable_json(_strip(dict(record)))


def _verify_hash_chain(rows: list[dict[str, Any]]) -> tuple[bool, list[str], str | None]:
    issues: list[str] = []
    previous_hash: str | None = None
    for index, row in enumerate(rows, start=1):
        row_previous = _optional_text(row.get("previous_record_hash"))
        if row_previous != previous_hash:
            issues.append(f"chain_break_at={index}")
        expected = build_policy_registry_record(dict(row), created_by=_safe_text(row.get("created_by")), source_module=_safe_text(row.get("source_module")), source_version=_safe_text(row.get("source_version")), created_at=_safe_text(row.get("created_at")), previous_record_hash=row_previous)
        if _safe_text(expected.get("record_hash")) != _safe_text(row.get("record_hash")):
            issues.append(f"record_hash_mismatch_at={index}")
        previous_hash = _safe_text(row.get("record_hash")) or None
    return len(issues) == 0, issues, previous_hash


def _load_raw_rows(path: Path) -> tuple[list[dict[str, Any]], PolicyRegistryReplayDiagnostics]:
    if not path.exists():
        return [], PolicyRegistryReplayDiagnostics(0, 0, 0, 0, 0, [])
    rows: list[dict[str, Any]] = []
    malformed = partial = duplicate = unsupported = broken = 0
    errors: list[str] = []
    seen: set[str] = set()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    ends_with_newline = text.endswith("\n")
    for index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
            validated = validate_policy_registry_row(decoded)
            signature = _dedupe_signature(validated)
            if signature in seen:
                duplicate += 1
            else:
                seen.add(signature)
            rows.append(validated)
        except Exception as exc:
            malformed += 1
            if "schema_version" in str(exc):
                unsupported += 1
            if index == len(lines) and not ends_with_newline:
                partial += 1
            errors.append(f"line={index}:{exc}")
    if rows:
        ok, issues, _last = _verify_hash_chain(rows)
        if not ok:
            broken = len(issues)
    return rows, PolicyRegistryReplayDiagnostics(malformed, partial, duplicate, unsupported, broken, errors)


class PolicyRegistryStore:
    def __init__(self, *, registry_path: Path | str = DEFAULT_POLICY_REGISTRY_PATH):
        self.registry_path = Path(registry_path)
        self._cache_rows: list[dict[str, Any]] | None = None
        self._cache_diagnostics: PolicyRegistryReplayDiagnostics | None = None

    def _load(self) -> tuple[list[dict[str, Any]], PolicyRegistryReplayDiagnostics]:
        if self._cache_rows is not None and self._cache_diagnostics is not None:
            return self._cache_rows, self._cache_diagnostics
        rows, diagnostics = _load_raw_rows(self.registry_path)
        self._cache_rows = rows
        self._cache_diagnostics = diagnostics
        return rows, diagnostics

    def _require_clean_history(self) -> list[dict[str, Any]]:
        rows, diagnostics = self._load()
        if diagnostics.malformed_rows or diagnostics.partial_trailing_rows or diagnostics.duplicate_rows or diagnostics.unsupported_schema_rows or diagnostics.broken_hash_links:
            raise PolicyRegistryCorruptionError(
                "corrupt_policy_registry: "
                f"malformed_rows={diagnostics.malformed_rows} "
                f"partial_trailing_rows={diagnostics.partial_trailing_rows} "
                f"duplicate_rows={diagnostics.duplicate_rows} "
                f"unsupported_schema_rows={diagnostics.unsupported_schema_rows} "
                f"broken_hash_links={diagnostics.broken_hash_links}"
            )
        return rows

    def _append_row(self, row: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        blob = _stable_json(row) + "\n"
        fd = os.open(self.registry_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, blob.encode("utf-8"))
        finally:
            os.close(fd)
        self._cache_rows = None
        self._cache_diagnostics = None

    def append_record(self, payload: dict[str, Any], *, created_by: str, source_module: str, source_version: str, created_at: str | None = None) -> PolicyRegistryAppendResult:
        rows = self._require_clean_history()
        previous_record_hash = rows[-1]["record_hash"] if rows else None
        candidate = build_policy_registry_record(payload, created_by=created_by, source_module=source_module, source_version=source_version, created_at=created_at, previous_record_hash=previous_record_hash)
        signature = _dedupe_signature(candidate)
        for existing in rows:
            existing_signature = _dedupe_signature(existing)
            if existing_signature == signature:
                return PolicyRegistryAppendResult(False, True, False, _safe_text(existing.get("policy_record_id")), _safe_text(existing.get("policy_event_id")), _safe_text(existing.get("record_hash")), "exact_duplicate")
            if _safe_text(existing.get("policy_record_id")) == _safe_text(candidate.get("policy_record_id")) or _safe_text(existing.get("policy_event_id")) == _safe_text(candidate.get("policy_event_id")):
                return PolicyRegistryAppendResult(False, False, True, _safe_text(candidate.get("policy_record_id")), _safe_text(candidate.get("policy_event_id")), _safe_text(candidate.get("record_hash")), "conflicting_duplicate")
        self._append_row(candidate)
        return PolicyRegistryAppendResult(True, False, False, _safe_text(candidate.get("policy_record_id")), _safe_text(candidate.get("policy_event_id")), _safe_text(candidate.get("record_hash")), "appended")

    def get_rows(self) -> list[dict[str, Any]]:
        return list(self._require_clean_history())

    def replay(self) -> tuple[dict[str, Any], PolicyRegistryReplayDiagnostics]:
        rows = self.get_rows()
        return build_policy_registry_projection_from_rows(rows), self._load()[1]

    def verify_hash_chain(self) -> dict[str, Any]:
        rows = self.get_rows()
        valid, issues, last_hash = _verify_hash_chain(rows)
        return {"schema_version": POLICY_REGISTRY_SCHEMA_VERSION, "valid": valid, "row_count": len(rows), "issues": issues, "last_record_hash": last_hash}


def build_policy_registry_audit_summary(*, store: PolicyRegistryStore) -> dict[str, Any]:
    projection, diagnostics = store.replay()
    hash_chain = store.verify_hash_chain()
    return {
        "schema_version": POLICY_REGISTRY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(store.get_rows()),
        "malformed_rows": diagnostics.malformed_rows,
        "partial_trailing_rows": diagnostics.partial_trailing_rows,
        "duplicate_rows": diagnostics.duplicate_rows,
        "replay_errors": list(diagnostics.replay_errors),
        "hash_chain": hash_chain,
        "active_count": projection["active_count"],
        "deprecated_count": projection["deprecated_count"],
        "allowed_action_count": projection["allowed_action_count"],
        "blocked_action_count": projection["blocked_action_count"],
        "lineage_break_count": projection["lineage_break_count"],
        "projection_identity": projection["projection_identity"],
        "projection_hash": projection["projection_hash"],
        "advisory_only": True,
        "pipeline_output_changed": False,
    }