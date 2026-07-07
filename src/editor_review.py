"""Deterministic shadow editor review helpers.

This module produces passive editorial review metadata from already-generated
content. It never rewrites content, prompts, or pipeline decisions.
"""

from __future__ import annotations

import re


REVIEW_MODE = "shadow"
REVIEW_VERSION = "v1"


def _clamp(score: float) -> int:
    return max(0, min(100, int(round(score))))


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9ığüşöçİĞÜŞÖÇ]+", value.lower())


def _safe_div(a: float, b: float) -> float:
    if not b:
        return 0.0
    return a / b


def _keyword_overlap(left: set[str], right: set[str]) -> int:
    if not left or not right:
        return 0
    return len(left & right)


def _findings_for_score(score: int, good: str, medium: str, weak: str) -> list[str]:
    if score >= 75:
        return [good]
    if score >= 50:
        return [medium]
    return [weak]


def build_editor_review_metadata(
    *,
    title: str,
    description: str,
    script: str,
    tags: list[str] | None = None,
) -> dict:
    title_n = _normalize_text(title)
    description_n = _normalize_text(description)
    script_n = _normalize_text(script)
    tags_n = [str(t).strip() for t in (tags or []) if str(t).strip()]

    title_tokens = set(_tokens(title_n))
    desc_tokens = set(_tokens(description_n))
    script_tokens = _tokens(script_n)
    tag_tokens = set(_tokens(" ".join(tags_n)))
    unique_script_ratio = _safe_div(len(set(script_tokens)), len(script_tokens))
    opening_window = script_n[:220].lower()
    script_lower = script_n.lower()

    hook_signal = 0
    if any(ch.isdigit() for ch in title_n):
        hook_signal += 18
    if "?" in title_n or "!" in title_n:
        hook_signal += 12
    if 20 <= len(title_n) <= 70:
        hook_signal += 15
    if any(marker in opening_window for marker in ["neden", "sok", "dikkat", "bugun", "hemen"]):
        hook_signal += 20
    if len(opening_window) >= 140:
        hook_signal += 10
    hook_score = _clamp(25 + hook_signal)

    paragraph_count = len([p for p in script_n.splitlines() if p.strip()])
    structure_markers = ["giris", "neden", "nasil", "adim", "sonuc", "ozet"]
    structure_hits = sum(1 for marker in structure_markers if marker in script_lower)
    structure_score = _clamp(20 + min(35, paragraph_count * 3) + min(45, structure_hits * 8))

    seo_overlap = _keyword_overlap(title_tokens, desc_tokens) + _keyword_overlap(title_tokens, tag_tokens)
    seo_score = _clamp(
        20
        + (20 if 20 <= len(title_n) <= 70 else 0)
        + min(20, len(tags_n) * 3)
        + min(20, seo_overlap * 5)
        + (10 if len(description_n) >= 80 else 0)
    )

    cliches = [
        "merhaba sevgili izleyiciler",
        "bu videoda",
        "kanalima hos geldiniz",
        "videoyu sonuna kadar izleyin",
        "ekranda gordugunuz",
    ]
    cliche_hits = sum(1 for phrase in cliches if phrase in script_lower)
    originality_score = _clamp(30 + unique_script_ratio * 55 - cliche_hits * 12)

    detail_markers = ["tl", "%", "oran", "veri", "istatistik", "strateji", "ornek"]
    detail_hits = sum(script_lower.count(marker) for marker in detail_markers)
    digit_density = _safe_div(sum(ch.isdigit() for ch in script_n), max(1, len(script_n)))
    information_density_score = _clamp(25 + unique_script_ratio * 35 + min(20, detail_hits * 4) + min(20, digit_density * 1200))

    overall_review_score = _clamp(
        (hook_score + structure_score + seo_score + originality_score + information_density_score) / 5
    )

    return {
        "review_mode": REVIEW_MODE,
        "review_version": REVIEW_VERSION,
        "hook_review": {
            "score": hook_score,
            "findings": _findings_for_score(
                hook_score,
                "hook_signal_strong",
                "hook_signal_moderate",
                "hook_signal_weak",
            ),
        },
        "structure_review": {
            "score": structure_score,
            "findings": _findings_for_score(
                structure_score,
                "structure_markers_clear",
                "structure_markers_partial",
                "structure_markers_thin",
            ),
        },
        "seo_review": {
            "score": seo_score,
            "findings": _findings_for_score(
                seo_score,
                "seo_alignment_strong",
                "seo_alignment_partial",
                "seo_alignment_weak",
            ),
        },
        "originality_review": {
            "score": originality_score,
            "findings": _findings_for_score(
                originality_score,
                "originality_signal_strong",
                "originality_signal_moderate",
                "originality_signal_weak",
            ),
        },
        "information_density_review": {
            "score": information_density_score,
            "findings": _findings_for_score(
                information_density_score,
                "information_density_strong",
                "information_density_moderate",
                "information_density_weak",
            ),
        },
        "overall_review_score": overall_review_score,
    }