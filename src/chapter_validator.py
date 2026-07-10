"""Shared chapter validation and auto-fix contract.

This module is pure and deterministic so runtime upload preflight and offline
metadata repair can use exactly the same rules.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = "2.0"
VALIDATOR_VERSION = "1.1.0"
MIN_SEGMENT_SECONDS = 10
ENDING_GUARD_SECONDS = 10

RULE_IDS = {
    "missing_start_00_00": "CH001",
    "timestamps_not_sorted": "CH002",
    "duplicate_timestamp": "CH003",
    "timestamp_beyond_duration": "CH004",
    "cta_chapter_detected": "CH005",
    "ending_guard_violation": "CH006",
    "short_segment_detected": "CH007",
    "duration_unknown_no_destructive_fix": "CH008",
    "shorts_bypassed": "CH009",
}

_CHAPTER_HEADING_RE = re.compile(r"^(?:[\W_]*)(?:bolumler|chapters?)\b", re.IGNORECASE)
_TIMESTAMP_LINE_RE = re.compile(r"^(?P<t>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<title>.+)$")
_CTA_CHAPTER_RE = re.compile(
    r"\b(abone\s*ol|abone|subscribe|takip\s*et|outro|sonuc|sonu\w*|like|begen\w*)\b",
    re.IGNORECASE,
)


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except Exception:
        return default


def parse_timestamp_seconds(token: str) -> int:
    text = str(token or "").strip()
    if not text:
        return -1
    parts = [p for p in text.split(":") if p]
    nums = [_safe_int(p, -1) for p in parts]
    if any(n < 0 for n in nums):
        return -1
    if len(nums) == 2:
        mm, ss = nums
        return mm * 60 + ss
    if len(nums) == 3:
        hh, mm, ss = nums
        return hh * 3600 + mm * 60 + ss
    return -1


def _format_timestamp(seconds: int) -> str:
    sec = max(0, int(seconds))
    mm = sec // 60
    ss = sec % 60
    return f"{mm:02d}:{ss:02d}"


def remove_chapter_lines(description: str) -> str:
    out: list[str] = []
    for raw in str(description or "").splitlines():
        line = raw.strip()
        if not line:
            out.append(raw)
            continue
        if _CHAPTER_HEADING_RE.match(line):
            continue
        if _TIMESTAMP_LINE_RE.match(line):
            continue
        out.append(raw)
    return "\n".join(out).strip()


def chapter_entries_from_description(description: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in str(description or "").splitlines():
        line = raw.strip()
        if not line or _CHAPTER_HEADING_RE.match(line):
            continue
        m = _TIMESTAMP_LINE_RE.match(line)
        if not m:
            continue
        sec = parse_timestamp_seconds(m.group("t"))
        if sec < 0:
            continue
        title = str(m.group("title") or "").strip()
        if not title:
            continue
        entries.append({"timestamp": _format_timestamp(sec), "seconds": sec, "title": title})
    return entries


def render_chapter_block(chapters: list[dict[str, Any]]) -> str:
    if not chapters:
        return ""
    lines = ["⏱️ BOLUMLER:"]
    for item in chapters:
        sec = _safe_int(item.get("seconds"), -1)
        title = str(item.get("title") or "").strip()
        if sec < 0 or not title:
            continue
        lines.append(f"{_format_timestamp(sec)} {title}")
    return "\n".join(lines)


def _dedupe_by_seconds(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in chapters:
        sec = int(item["seconds"])
        if sec in seen:
            continue
        seen.add(sec)
        deduped.append(item)
    return deduped


def validate_and_fix_chapters(
    description: str,
    video_duration_seconds: int | None,
    is_short: bool = False,
) -> dict[str, Any]:
    original_description = str(description or "")
    prose = remove_chapter_lines(original_description)
    original_chapters = chapter_entries_from_description(original_description)
    final_chapters = [dict(item) for item in original_chapters]

    issue_codes: list[str] = []
    issue_labels: list[str] = []
    auto_fix_actions: list[str] = []
    bypass_reason: str | None = None
    ending_guard_pass = True
    short_segment_merges = 0
    cta_removed_count = 0
    ending_trim_count = 0
    duplicate_removed_count = 0

    def _record_issue(label: str) -> None:
        issue_labels.append(label)
        issue_codes.append(RULE_IDS.get(label, label))

    duration_known = isinstance(video_duration_seconds, (int, float)) and int(video_duration_seconds) > 0
    duration = int(video_duration_seconds or 0) if duration_known else None

    shorts_bypassed = bool(is_short)
    if shorts_bypassed:
        _record_issue("shorts_bypassed")
        bypass_reason = "short_duration"
        final_chapters = []

    valid_before = True
    if original_chapters:
        secs = [int(item["seconds"]) for item in original_chapters]
        if secs[0] != 0:
            valid_before = False
            _record_issue("missing_start_00_00")
        if secs != sorted(secs):
            valid_before = False
            _record_issue("timestamps_not_sorted")
        if len(set(secs)) != len(secs):
            valid_before = False
            _record_issue("duplicate_timestamp")
        if duration_known and any(sec > int(duration or 0) for sec in secs):
            valid_before = False
            _record_issue("timestamp_beyond_duration")

    if not shorts_bypassed and final_chapters:
        if [int(c["seconds"]) for c in final_chapters] != sorted(int(c["seconds"]) for c in final_chapters):
            final_chapters.sort(key=lambda item: int(item["seconds"]))
            auto_fix_actions.append("sort_timestamps")

        before_count = len(final_chapters)
        final_chapters = _dedupe_by_seconds(final_chapters)
        if len(final_chapters) != before_count:
            auto_fix_actions.append("remove_duplicate_timestamps")
            duplicate_removed_count += before_count - len(final_chapters)

        cta_removed = 0
        kept: list[dict[str, Any]] = []
        for item in final_chapters:
            if _CTA_CHAPTER_RE.search(str(item.get("title") or "")):
                cta_removed += 1
                continue
            kept.append(item)
        final_chapters = kept
        if cta_removed > 0:
            auto_fix_actions.append("remove_cta_chapters")
            _record_issue("cta_chapter_detected")
            cta_removed_count = cta_removed

        if duration_known and duration is not None:
            before = len(final_chapters)
            final_chapters = [item for item in final_chapters if int(item["seconds"]) <= duration]
            if len(final_chapters) != before:
                auto_fix_actions.append("drop_beyond_duration")

            if final_chapters and int(final_chapters[0]["seconds"]) != 0:
                final_chapters.insert(0, {"timestamp": "00:00", "seconds": 0, "title": "Giris"})
                auto_fix_actions.append("add_start_00_00")

            max_start = max(0, duration - ENDING_GUARD_SECONDS)
            if final_chapters and int(final_chapters[-1]["seconds"]) > max_start:
                final_chapters.pop()
                auto_fix_actions.append("drop_ending_guard_violation")
                _record_issue("ending_guard_violation")
                ending_guard_pass = False
                ending_trim_count += 1

            merged: list[dict[str, Any]] = []
            merge_count = 0
            for item in final_chapters:
                if not merged:
                    merged.append(item)
                    continue
                prev = merged[-1]
                if int(item["seconds"]) - int(prev["seconds"]) < MIN_SEGMENT_SECONDS:
                    merge_count += 1
                    continue
                merged.append(item)
            final_chapters = merged
            if merge_count > 0:
                auto_fix_actions.append("merge_short_segments")
                _record_issue("short_segment_detected")
                short_segment_merges += merge_count

            while (
                len(final_chapters) >= 2
                and duration - int(final_chapters[-1]["seconds"]) < MIN_SEGMENT_SECONDS
            ):
                final_chapters.pop()
                if "merge_short_segments" not in auto_fix_actions:
                    auto_fix_actions.append("merge_short_segments")
                if RULE_IDS["short_segment_detected"] not in issue_codes:
                    _record_issue("short_segment_detected")
                short_segment_merges += 1
        else:
            if RULE_IDS["duration_unknown_no_destructive_fix"] not in issue_codes:
                _record_issue("duration_unknown_no_destructive_fix")
            bypass_reason = "duration_unknown"

    final_chapters = _dedupe_by_seconds(sorted(final_chapters, key=lambda item: int(item["seconds"])))

    valid_after = True
    if final_chapters:
        secs = [int(item["seconds"]) for item in final_chapters]
        if secs[0] != 0:
            valid_after = False
        if secs != sorted(secs):
            valid_after = False
        if len(set(secs)) != len(secs):
            valid_after = False
        if any((secs[i + 1] - secs[i]) < MIN_SEGMENT_SECONDS for i in range(len(secs) - 1)):
            valid_after = False
        if duration_known and duration is not None:
            if any(sec > duration for sec in secs):
                valid_after = False
            if duration - secs[-1] < MIN_SEGMENT_SECONDS:
                valid_after = False

    if not final_chapters and not shorts_bypassed and original_chapters:
        bypass_reason = bypass_reason or "chapter_contract_failed"

    chapter_contract_pass = bool(valid_after and (shorts_bypassed or not original_chapters or len(final_chapters) >= 3))
    min_gap_ok = True
    if len(final_chapters) >= 2:
        sec_values = [int(item["seconds"]) for item in final_chapters]
        min_gap_ok = all((sec_values[i + 1] - sec_values[i]) >= MIN_SEGMENT_SECONDS for i in range(len(sec_values) - 1))
    elif original_chapters and not final_chapters and not shorts_bypassed:
        min_gap_ok = False

    chapter_block = render_chapter_block(final_chapters)
    if chapter_block:
        normalized_description = f"{prose}\n\n{chapter_block}".strip() if prose else chapter_block
    else:
        normalized_description = prose

    return {
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "original_description": original_description,
        "normalized_description": normalized_description,
        "original_chapters": original_chapters,
        "final_chapters": final_chapters,
        "valid_before": bool(valid_before),
        "valid_after": bool(valid_after),
        "issue_codes": sorted(set(issue_codes)),
        "issue_labels": sorted(set(issue_labels)),
        "auto_fix_actions": list(dict.fromkeys(auto_fix_actions)),
        "fix_counts": {
            "cta_removed_count": int(cta_removed_count),
            "merge_count": int(short_segment_merges),
            "ending_trim_count": int(ending_trim_count),
            "duplicate_removed_count": int(duplicate_removed_count),
        },
        "min_segment_seconds": MIN_SEGMENT_SECONDS,
        "min_gap_seconds": MIN_SEGMENT_SECONDS,
        "ending_guard_seconds": ENDING_GUARD_SECONDS,
        "shorts_bypassed": bool(shorts_bypassed),
        "shorts_bypass": bool(shorts_bypassed),
        "input_chapter_count": len(original_chapters),
        "chapter_count": len(final_chapters),
        "chapter_contract_pass": chapter_contract_pass,
        "bypass_reason": bypass_reason,
        "min_gap_ok": min_gap_ok,
        "ending_guard_pass": ending_guard_pass,
        "short_segment_merges": short_segment_merges,
        "cta_removed_count": cta_removed_count,
        "ending_trim_count": ending_trim_count,
        "duplicate_removed_count": duplicate_removed_count,
    }
