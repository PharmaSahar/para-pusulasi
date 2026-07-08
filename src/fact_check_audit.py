"""Helpers for auditing failed fact-check events from scheduler logs."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

FAILED_FACT_CHECK_PREFIX = "failed_fact_check: "
FAILED_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+"
    r"\[(?P<level>[A-Z]+)\]\s+[^:]+:\s+\[(?P<channel>[^\]]+)\]\s+"
    r"Fatal hata \(retry yok\):\s+"
    r"(?P<reason>failed_fact_check: .+)$"
)
CLAIM_TYPE_RE = re.compile(r"\((?P<claim_type>[^()]+)\)\s*$")


def classify_failed_fact_check(reason: str) -> tuple[str, str | None]:
    """Return a stable failure kind and optional claim type for a reason string."""
    normalized = reason.strip()
    if normalized.startswith(FAILED_FACT_CHECK_PREFIX):
        normalized = normalized[len(FAILED_FACT_CHECK_PREFIX):]

    if normalized.startswith("USD/TRY stale claim:"):
        return "stale_fx_claim", "fx_usd_try"

    if normalized.startswith("fx_source_unavailable:"):
        return "fx_source_unavailable", "fx_usd_try"

    if normalized.startswith("unverifiable_volatile_claim:"):
        match = CLAIM_TYPE_RE.search(normalized)
        return "unverifiable_volatile_claim", match.group("claim_type") if match else None

    if normalized.startswith("missing_freshness_metadata_for_market_data"):
        return "missing_freshness_metadata", None

    return "other_failed_fact_check", None


def parse_failed_fact_check_events(log_text: str) -> list[dict]:
    """Extract failed fact-check events from scheduler log text.

    Only the scheduler's fatal fail-closed lines are counted so a single failure
    does not appear twice via both "Fatal hata" and "Render hatası" log lines.
    """
    events: list[dict] = []

    for line in log_text.splitlines():
        match = FAILED_LINE_RE.match(line.strip())
        if not match:
            continue

        timestamp = match.group("timestamp")
        channel = match.group("channel")
        reason = match.group("reason")

        failure_kind, claim_type = classify_failed_fact_check(reason)
        events.append(
            {
                "timestamp": timestamp,
                "channel": channel,
                "reason": reason,
                "failure_kind": failure_kind,
                "claim_type": claim_type,
            }
        )

    return events


def build_failed_fact_check_audit(log_path: Path, *, max_examples: int = 10) -> dict:
    """Summarize failed fact-check events from a scheduler log file."""
    text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    events = parse_failed_fact_check_events(text)

    by_kind = Counter(event["failure_kind"] for event in events)
    by_claim_type = Counter(event["claim_type"] for event in events if event["claim_type"])
    by_channel = Counter(event["channel"] for event in events)

    return {
        "log_path": str(log_path),
        "total_failed_fact_checks": len(events),
        "counts_by_failure_kind": dict(sorted(by_kind.items())),
        "counts_by_claim_type": dict(sorted(by_claim_type.items())),
        "counts_by_channel": dict(sorted(by_channel.items())),
        "examples": events[:max_examples],
    }