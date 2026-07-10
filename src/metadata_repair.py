"""Metadata normalization helpers for YouTube description/tags/chapters.

This module is intentionally pure and side-effect free so both runtime uploader
and offline repair tools can reuse exactly the same rules.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .chapter_validator import (
    chapter_entries_from_description,
    remove_chapter_lines,
    render_chapter_block,
    validate_and_fix_chapters,
)
from .quality_scoring import build_quality_scores


_CHAPTER_HEADING_RE = re.compile(r"^(?:[\W_]*)(?:bolumler|chapters?)\b", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"^(?P<t>\d{1,2}:\d{2}(?::\d{2})?)\b")


@dataclass(frozen=True)
class MetadataAssessment:
    chapter_issue: bool
    tag_issue: bool
    seo_issue: bool
    chapter_count: int
    min_gap_ok: bool
    seo_score_before: int
    seo_score_after: int


@dataclass(frozen=True)
class NormalizedMetadata:
    description: str
    tags: list[str]
    assessment: MetadataAssessment


def _normalize_ascii(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch)
    )


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def parse_iso8601_duration_seconds(duration: str | None) -> int:
    """Parse YouTube contentDetails.duration (ISO8601) to seconds."""
    text = str(duration or "").strip().upper()
    if not text.startswith("P"):
        return 0

    # Matches PnDTnHnMnS
    rx = re.compile(
        r"^P"
        r"(?:(?P<days>\d+)D)?"
        r"(?:T"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
        r")?$"
    )
    m = rx.match(text)
    if not m:
        return 0

    days = _safe_int(m.group("days"), 0)
    hours = _safe_int(m.group("hours"), 0)
    minutes = _safe_int(m.group("minutes"), 0)
    seconds = _safe_int(m.group("seconds"), 0)
    return max(0, days * 86400 + hours * 3600 + minutes * 60 + seconds)


def _parse_timestamp_to_seconds(token: str) -> int:
    parts = token.split(":")
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


def extract_chapter_seconds(description: str) -> list[int]:
    entries = chapter_entries_from_description(description)
    return [int(item.get("seconds", 0)) for item in entries]


def chapter_rule_ok(description: str, min_gap: int = 10, min_count: int = 3) -> tuple[bool, int, bool]:
    result = validate_and_fix_chapters(
        description=description,
        video_duration_seconds=None,
        is_short=False,
    )
    secs = [int(item.get("seconds", 0)) for item in result.get("final_chapters", [])]
    if len(secs) < min_count:
        return False, len(secs), False

    # Remove duplicates and enforce monotonicity check on sorted timeline.
    unique = sorted(set(secs))
    if len(unique) < min_count:
        return False, len(unique), False

    min_gap_ok = all((unique[i + 1] - unique[i]) >= min_gap for i in range(len(unique) - 1))
    return min_gap_ok, len(unique), min_gap_ok


def strip_existing_chapters(description: str) -> str:
    """Remove existing chapter heading/timestamp lines from description."""
    return remove_chapter_lines(description)


def sanitize_tags(tags: list[str] | None, max_tags: int = 15) -> list[str]:
    clean: list[str] = []
    total_len = 0
    for tag in tags or []:
        t = re.sub(r"[^\w\s\-.,&'\u00C0-\u024F]", "", str(tag), flags=re.UNICODE)
        t = t.strip()[:50]
        if not t:
            continue
        if total_len + len(t) + 1 > 500:
            break
        clean.append(t)
        total_len += len(t) + 1
        if len(clean) >= max_tags:
            break
    return clean


def fallback_tags_from_title(title: str, niche: str = "") -> list[str]:
    words: list[str] = []
    lowered = _normalize_ascii(title).lower()
    for token in re.findall(r"[\wığüşöçİĞÜŞÖÇ]+", lowered):
        if len(token) < 3:
            continue
        if token in {"ve", "ile", "icin", "ama", "gibi", "daha", "bir", "bu", "that", "this"}:
            continue
        words.append(token)

    defaults = [
        "finans",
        "yatirim",
        "turkiye",
        "egitim",
        "para pusulasi",
        niche.strip() or "kisisel finans",
    ]

    merged = defaults + words
    out: list[str] = []
    seen: set[str] = set()
    for item in merged:
        candidate = str(item).strip()[:50]
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= 15:
            break
    return out


def ensure_minimum_tags(title: str, tags: list[str] | None, niche: str = "", min_tags: int = 8) -> list[str]:
    normalized = sanitize_tags(tags)
    seen = {x.lower() for x in normalized}

    for fallback in fallback_tags_from_title(title=title, niche=niche):
        key = fallback.lower()
        if key in seen:
            continue
        normalized.append(fallback)
        seen.add(key)
        if len(normalized) >= max(min_tags, 15):
            break

    if len(normalized) < min_tags:
        for i in range(min_tags - len(normalized)):
            extra = f"anahtar konu {i + 1}"
            if extra not in seen:
                normalized.append(extra)
    return normalized[:15]


def build_duration_safe_chapters(duration_sec: int) -> list[tuple[int, str]]:
    """Create chapters that satisfy YouTube min 10s spacing rule."""
    duration_sec = max(0, int(duration_sec or 0))
    if duration_sec < 45:
        return []

    available = duration_sec - 10
    if available < 30:
        return []

    target_count = min(6, max(3, duration_sec // 120 + 2))
    points: list[int] = [0]
    for i in range(1, target_count):
        candidate = int(round((available * i) / (target_count - 1)))
        candidate = max(10, min(available, candidate))
        if candidate - points[-1] < 10:
            candidate = points[-1] + 10
        if candidate > available:
            break
        points.append(candidate)

    while len(points) >= 2 and (available - points[-1]) < 10:
        points.pop()

    if len(points) < 3:
        return []

    titles = [
        "Giris ve Hook",
        "Temel Kavramlar",
        "Ornekler ve Veri",
        "Adim Adim Uygulama",
        "Kritik Hatalar",
        "Ozet ve Sonraki Adim",
    ]
    return [(sec, titles[min(i, len(titles) - 1)]) for i, sec in enumerate(points)]


def render_chapters_block(chapters: list[tuple[int, str]]) -> str:
    if not chapters:
        return ""
    lines = ["BOLUMLER:"]
    for sec, title in chapters:
        mm = sec // 60
        ss = sec % 60
        lines.append(f"{mm:02d}:{ss:02d} {title}")
    return "\n".join(lines)


def _keyword_line(tags: list[str]) -> str:
    return "Anahtar kelimeler: " + ", ".join(tags[:10]) + "."


def _hashtags_line(tags: list[str]) -> str:
    tokens: list[str] = []
    for tag in tags[:8]:
        token = "".join(ch for ch in str(tag) if ch.isalnum())
        if token:
            tokens.append(f"#{token}")
    return " ".join(tokens)


def build_normalized_description(
    *,
    title: str,
    base_description: str,
    tags: list[str],
    duration_sec: int,
) -> str:
    summary = f"Bu videoda: {title}".strip()
    question = f"Yorum sorusu: {title} konusunda en cok hangi adim zor geliyor?".strip()
    body = strip_existing_chapters(base_description)
    proposed_chapters = render_chapters_block(build_duration_safe_chapters(duration_sec))
    chapter_candidate = body
    if proposed_chapters:
        chapter_candidate = f"{body}\n\n{proposed_chapters}".strip()
    chapter_result = validate_and_fix_chapters(
        description=chapter_candidate,
        video_duration_seconds=duration_sec,
        is_short=bool(int(duration_sec or 0) < 60),
    )
    chapters = render_chapter_block(chapter_result.get("final_chapters", []))

    parts = [summary]
    if body:
        parts.append(body)
    if chapters:
        parts.append(chapters)
    parts.append(question)
    parts.append(_keyword_line(tags))

    hashtags = _hashtags_line(tags)
    if hashtags:
        parts.append(hashtags)

    text = "\n\n".join(p for p in parts if p).strip()
    if len(text) < 220:
        text += "\n\nBu icerik egitim amaclidir. Risk yonetimi ve uygulama adimlarina odaklanir."
    return text


def score_seo_proxy(title: str, description: str, tags: list[str]) -> int:
    score = build_quality_scores(
        title=title,
        description=description,
        script="",
        tags=tags,
        thumbnail_prompt="",
    )
    return _safe_int(score.get("seo_score"), 0)


def normalize_metadata(
    *,
    title: str,
    description: str,
    tags: list[str] | None,
    duration_sec: int,
    niche: str = "",
    min_tags: int = 8,
    min_seo: int = 60,
) -> NormalizedMetadata:
    ok, chapter_count, min_gap_ok = chapter_rule_ok(description)
    chapter_issue = False if int(duration_sec or 0) < 60 else not ok

    normalized_tags = ensure_minimum_tags(title=title, tags=tags, niche=niche, min_tags=min_tags)
    tag_issue = len(sanitize_tags(tags)) < min_tags

    seo_before = score_seo_proxy(title=title, description=description, tags=sanitize_tags(tags))
    new_description = build_normalized_description(
        title=title,
        base_description=description,
        tags=normalized_tags,
        duration_sec=duration_sec,
    )
    seo_after = score_seo_proxy(title=title, description=new_description, tags=normalized_tags)
    seo_issue = seo_before < min_seo

    return NormalizedMetadata(
        description=new_description,
        tags=normalized_tags,
        assessment=MetadataAssessment(
            chapter_issue=chapter_issue,
            tag_issue=tag_issue,
            seo_issue=seo_issue,
            chapter_count=chapter_count,
            min_gap_ok=min_gap_ok,
            seo_score_before=seo_before,
            seo_score_after=seo_after,
        ),
    )
