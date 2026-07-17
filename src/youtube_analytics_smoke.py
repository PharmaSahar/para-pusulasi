"""Read-only YouTube Analytics smoke wrapper.

This module performs a single explicitly invoked, read-only Analytics API query
for one configured channel. It never refreshes credentials, never writes token
files, and never mutates scheduler state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .channel_manager import get_channel


SCHEMA_VERSION = "v1"
MODE = "READ_ONLY_SMOKE"
DEFAULT_OUTPUT_PATH = Path("artifacts/local/youtube_analytics_smoke.json")
DEFAULT_TIMEOUT_SECONDS = 15
MAX_SMOKE_WINDOW_DAYS = 7
ALLOWED_DIMENSIONS = ("day",)
ALLOWED_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "impressions",
    "impressionClickThroughRate",
    "subscribersGained",
    "subscribersLost",
)

TOKEN_SOURCE_ANALYTICS_PRIMARY = "ANALYTICS_TOKEN_PRIMARY"
TOKEN_SOURCE_NONE = "NONE"


@dataclass(frozen=True, slots=True)
class SmokeContext:
    channel_slug: str
    channel_id: str
    primary_token_path: Path
    selected_token_path: Path | None
    selected_token_source: str
    secrets_path: Path
    token_source_present: bool
    credential_source_present: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_error(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""

    replacements = [
        (r"(?i)(access_token\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(refresh_token\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(client_secret\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(client_id\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(token\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(secret\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)

    text = re.sub(r"ya29\.[0-9A-Za-z\-_.]+", "[REDACTED]", text)
    text = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", text)
    text = re.sub(r"gh[pousr]_[0-9A-Za-z]{20,}", "[REDACTED]", text)
    text = re.sub(r"sk-[0-9A-Za-z]{20,}", "[REDACTED]", text)
    return text[:500]


def _parse_date(value: str) -> date:
    try:
        return datetime.fromisoformat(str(value).strip()).date()
    except Exception as exc:
        raise ValueError(f"invalid_date:{value}") from exc


def _validate_date_window(start_date: str, end_date: str) -> tuple[str, str]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValueError("invalid_date_window:end_before_start")
    if (end - start).days + 1 > MAX_SMOKE_WINDOW_DAYS:
        raise ValueError("invalid_date_window:window_exceeds_seven_days")
    return start.isoformat(), end.isoformat()


def _resolve_gate_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get("YOUTUBE_ANALYTICS_API_GO", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_channel_context(channel_slug: str) -> SmokeContext:
    try:
        cfg = get_channel(channel_slug)
    except Exception as exc:
        raise ValueError(f"channel_mapping_error:{exc}") from exc
    channel_id = str(getattr(cfg, "youtube_channel_id", "") or "").strip()
    if not channel_id:
        raise ValueError("channel_mapping_error:missing_youtube_channel_id")

    primary_token_path = Path(str(getattr(cfg, "youtube_analytics_token_path", "") or "").strip())
    secrets_path = Path(str(getattr(cfg, "client_secrets_path", "") or "").strip())
    selected_token_path: Path | None = None
    selected_token_source = TOKEN_SOURCE_NONE
    if primary_token_path.exists():
        selected_token_path = primary_token_path
        selected_token_source = TOKEN_SOURCE_ANALYTICS_PRIMARY

    token_source_present = selected_token_path is not None
    credential_source_present = token_source_present or secrets_path.exists()
    return SmokeContext(
        channel_slug=channel_slug,
        channel_id=channel_id,
        primary_token_path=primary_token_path,
        selected_token_path=selected_token_path,
        selected_token_source=selected_token_source,
        secrets_path=secrets_path,
        token_source_present=token_source_present,
        credential_source_present=credential_source_present,
    )


def _load_credentials_read_only(token_path: Path | None) -> object | None:
    if token_path is None or not token_path.exists():
        return None
    try:
        with token_path.open("rb") as handle:
            return pickle.load(handle)
    except Exception:
        return None


def _credentials_scope_ok(credentials: object) -> bool:
    if credentials is None:
        return False
    scopes = [
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]
    try:
        has_scopes = getattr(credentials, "has_scopes", None)
        if callable(has_scopes):
            return bool(has_scopes(scopes))
    except Exception:
        return False
    credential_scopes = set(str(scope) for scope in (getattr(credentials, "scopes", None) or []))
    return any(scope in credential_scopes for scope in scopes)


def _classify_http_error(err: HttpError) -> str:
    status = int(getattr(getattr(err, "resp", None), "status", 0) or 0)
    content = getattr(err, "content", b"")
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="ignore").lower()
    else:
        text = str(content).lower()

    if status in {401}:
        return "AUTHENTICATION_BLOCKED"
    if status in {402, 429}:
        return "QUOTA_BLOCKED"
    if status == 403:
        if "quota" in text or "rate limit" in text or "ratelimit" in text:
            return "QUOTA_BLOCKED"
        if "insufficient" in text or "scope" in text or "permission" in text:
            return "API_SCOPE_INSUFFICIENT"
        if "not enabled" in text or "accessnotconfigured" in text or "api not enabled" in text:
            return "API_NOT_ENABLED"
        return "AUTHENTICATION_BLOCKED"
    if 500 <= status <= 599:
        return "API_REQUEST_FAILED"
    return "API_REQUEST_FAILED"


def _build_service(credentials: object, *, timeout_seconds: int):
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=timeout_seconds))
    return build("youtubeAnalytics", "v2", http=http, cache_discovery=False, static_discovery=False)


def _normalize_row(row: list[Any], columns: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for index, column in enumerate(columns):
        value = row[index] if index < len(row) else None
        if column == "day" and value is not None:
            payload[column] = str(value)
            continue
        if isinstance(value, str):
            text = value.strip()
            if not text:
                payload[column] = None
                continue
            try:
                if "." in text:
                    payload[column] = float(text)
                else:
                    payload[column] = int(text)
                continue
            except Exception:
                payload[column] = text
                continue
        payload[column] = value
    return payload


def _canonicalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
        return (str(item.get("day") or ""), _stable_json(item))

    return sorted(rows, key=_sort_key)


def run_read_only_smoke(
    *,
    channel_slugs: list[str],
    start_date: str,
    end_date: str,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    generated_at = _now_iso()
    output_path = Path(output_path)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": MODE,
        "channel_slug": None,
        "channel_id_hash": None,
        "start_date": None,
        "end_date": None,
        "requested_metrics": list(ALLOWED_METRICS),
        "returned_columns": [],
        "row_count": 0,
        "normalized_rows": [],
        "result_state": "SUCCESS",
        "error_class": None,
        "redacted_error": None,
        "credential_source_present": False,
        "token_source_present": False,
        "selected_token_source": TOKEN_SOURCE_NONE,
        "api_call_attempted": False,
        "api_call_succeeded": False,
        "mutation_attempted": False,
    }

    try:
        if len(channel_slugs) != 1:
            raise ValueError("channel_mapping_error:exactly_one_channel_required")

        channel_slug = str(channel_slugs[0] or "").strip()
        if not channel_slug:
            raise ValueError("channel_mapping_error:missing_channel")

        start_iso, end_iso = _validate_date_window(start_date, end_date)
        context = _resolve_channel_context(channel_slug)
        if not context.token_source_present or context.selected_token_path is None:
            report["channel_slug"] = context.channel_slug
            report["channel_id_hash"] = _hash_text(context.channel_id)[:12]
            report["start_date"] = start_iso
            report["end_date"] = end_iso
            report["credential_source_present"] = False
            report["token_source_present"] = False
            report["selected_token_source"] = TOKEN_SOURCE_NONE
            report["result_state"] = "TOKEN_MISSING"
            return report

        credentials = _load_credentials_read_only(context.selected_token_path)

        report["channel_slug"] = context.channel_slug
        report["channel_id_hash"] = _hash_text(context.channel_id)[:12]
        report["start_date"] = start_iso
        report["end_date"] = end_iso
        report["credential_source_present"] = bool(credentials is not None)
        report["token_source_present"] = bool(context.token_source_present)
        report["selected_token_source"] = context.selected_token_source

        if not _resolve_gate_enabled():
            report["result_state"] = "API_NOT_ENABLED"
            return report

        if credentials is None:
            report["result_state"] = "TOKEN_MISSING"
            return report
        if not _credentials_scope_ok(credentials):
            report["result_state"] = "API_SCOPE_INSUFFICIENT"
            return report
        if bool(getattr(credentials, "expired", False)):
            report["result_state"] = "TOKEN_EXPIRED"
            return report
        if not bool(getattr(credentials, "valid", False)):
            report["result_state"] = "AUTHENTICATION_BLOCKED"
            return report

        service = _build_service(credentials, timeout_seconds=timeout_seconds)
        report["api_call_attempted"] = True
        query = service.reports().query(
            ids="channel==MINE",
            startDate=start_iso,
            endDate=end_iso,
            metrics=",".join(ALLOWED_METRICS),
            dimensions=",".join(ALLOWED_DIMENSIONS),
            maxResults=50,
        )
        response = query.execute(num_retries=0)
        report["api_call_succeeded"] = True

        headers = response.get("columnHeaders") or []
        columns = [str(header.get("name") or "").strip() for header in headers if str(header.get("name") or "").strip()]
        report["returned_columns"] = columns

        if columns and columns[0] != "day":
            report["result_state"] = "UNSUPPORTED_METRIC"
            report["error_class"] = "unsupported_dimension"
            report["redacted_error"] = _redact_error("unexpected_dimension")
            return report

        for column in columns[1:]:
            if column not in ALLOWED_METRICS:
                report["result_state"] = "UNSUPPORTED_METRIC"
                report["error_class"] = "unsupported_metric"
                report["redacted_error"] = _redact_error(column)
                return report

        rows = response.get("rows") or []
        normalized_rows = [_normalize_row(row, columns) for row in rows if isinstance(row, list)]
        normalized_rows = _canonicalize_rows(normalized_rows)
        report["normalized_rows"] = normalized_rows
        report["row_count"] = len(normalized_rows)

        if not normalized_rows:
            report["result_state"] = "EMPTY_RESPONSE"
        else:
            report["result_state"] = "SUCCESS"
        return report

    except ValueError as exc:
        message = str(exc)
        report["error_class"] = message.split(":", 1)[0]
        report["redacted_error"] = _redact_error(message)
        if message.startswith("invalid_date_window"):
            report["result_state"] = "INVALID_DATE_WINDOW"
        elif message.startswith("channel_mapping_error"):
            report["result_state"] = "CHANNEL_MAPPING_ERROR"
        elif message.startswith("invalid_date"):
            report["result_state"] = "INVALID_DATE_WINDOW"
        else:
            report["result_state"] = "CHANNEL_MAPPING_ERROR"
        return report
    except HttpError as exc:
        report["result_state"] = _classify_http_error(exc)
        report["error_class"] = report["result_state"]
        report["redacted_error"] = _redact_error(exc)
        return report
    except (OSError, pickle.PickleError):
        report["result_state"] = "CREDENTIAL_MISSING"
        report["error_class"] = "credential_error"
        report["redacted_error"] = _redact_error("credential load failed")
        return report
    except Exception as exc:
        message = str(exc)
        if "channel_mapping_error" in message:
            report["result_state"] = "CHANNEL_MAPPING_ERROR"
        elif "token" in message.lower() and "missing" in message.lower():
            report["result_state"] = "TOKEN_MISSING"
        elif "expired" in message.lower():
            report["result_state"] = "TOKEN_EXPIRED"
        else:
            report["result_state"] = "API_REQUEST_FAILED"
        report["error_class"] = report["result_state"]
        report["redacted_error"] = _redact_error(message)
        return report


def _finalize_report(report: dict[str, Any], output_path: Path | str) -> dict[str, Any]:
    payload = dict(report)
    payload["output_hash"] = None
    payload["output_hash"] = _hash_text(_stable_json(payload))

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def run_read_only_smoke_and_write(
    *,
    channel_slugs: list[str],
    start_date: str,
    end_date: str,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    report = run_read_only_smoke(
        channel_slugs=channel_slugs,
        start_date=start_date,
        end_date=end_date,
        output_path=output_path,
        timeout_seconds=timeout_seconds,
    )
    try:
        return _finalize_report(report, output_path)
    except Exception as exc:
        failed = dict(report)
        failed["result_state"] = "OUTPUT_WRITE_FAILED"
        failed["error_class"] = "OUTPUT_WRITE_FAILED"
        failed["redacted_error"] = _redact_error(exc)
        return failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a read-only YouTube Analytics smoke query.")
    parser.add_argument("--channel", action="append", required=True, metavar="CHANNEL")
    parser.add_argument("--start-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--output", required=True, metavar="PATH")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, metavar="SECONDS")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = run_read_only_smoke_and_write(
        channel_slugs=list(args.channel),
        start_date=args.start_date,
        end_date=args.end_date,
        output_path=args.output,
        timeout_seconds=int(args.timeout_seconds),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("result_state") == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())