"""Quality scoring v1: deterministic, metadata-only heuristics."""

from __future__ import annotations

import re


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


def build_quality_scores(
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

    script_tokens = _tokens(script_n)
    desc_tokens = _tokens(description_n)
    title_tokens = _tokens(title_n)
    unique_script_ratio = _safe_div(len(set(script_tokens)), len(script_tokens))

    hook_signal = 0
    if any(ch.isdigit() for ch in title_n):
        hook_signal += 20
    if "?" in title_n or "!" in title_n:
        hook_signal += 15
    if 20 <= len(title_n) <= 70:
        hook_signal += 15
    if len(script_n[:220]) >= 140:
        hook_signal += 10
    hook_score = _clamp(40 + hook_signal)

    section_markers = ["giris", "sonuc", "ozet", "adim", "neden", "nasil"]
    paragraph_count = len([p for p in script_n.split("\n") if p.strip()])
    marker_hits = sum(1 for marker in section_markers if marker in script_n.lower())
    structure_score = _clamp(30 + min(30, paragraph_count * 2) + min(40, marker_hits * 7))

    digit_density = _safe_div(sum(ch.isdigit() for ch in script_n), max(1, len(script_n)))
    information_density_score = _clamp(30 + unique_script_ratio * 40 + min(30, digit_density * 1200))

    cliches = ["merhaba sevgili izleyiciler", "bu videoda", "videoyu izlemeye devam", "ekranda gordugunuz"]
    cliche_hits = sum(1 for c in cliches if c in script_n.lower())
    originality_score = _clamp(35 + unique_script_ratio * 50 - cliche_hits * 12)

    human_markers = ["sen", "sana", "senin", "biz", "haydi", "dusun", "bak"]
    humanity_hits = sum(1 for marker in human_markers if marker in script_n.lower())
    humanity_score = _clamp(30 + min(50, humanity_hits * 7) + min(20, _safe_div(len(script_tokens), 400) * 20))

    promise_markers = ["neden", "sir", "hata", "firsat", "kazanc", "getiri"]
    payoff_markers = ["sonuc", "ozet", "bu nedenle", "adim", "cozum", "strateji"]
    promise_hits = sum(1 for marker in promise_markers if marker in title_n.lower())
    payoff_hits = sum(1 for marker in payoff_markers if marker in script_n.lower())
    promise_to_payoff_score = _clamp(35 + min(30, promise_hits * 10) + min(35, payoff_hits * 7))

    title_set = set(title_tokens)
    desc_set = set(desc_tokens)
    tag_set = set(_tokens(" ".join(tags_n)))
    overlap_desc = len(title_set & desc_set)
    overlap_tags = len(title_set & tag_set)
    seo_score = _clamp(
        20
        + (20 if 20 <= len(title_n) <= 70 else 0)
        + min(20, len(tags_n) * 2)
        + min(20, overlap_desc * 4)
        + min(20, overlap_tags * 4)
    )

    overall_quality_score = _clamp(
        (
            hook_score
            + structure_score
            + information_density_score
            + originality_score
            + humanity_score
            + promise_to_payoff_score
            + seo_score
        )
        / 7
    )

    return {
        "hook_score": hook_score,
        "structure_score": structure_score,
        "information_density_score": information_density_score,
        "originality_score": originality_score,
        "humanity_score": humanity_score,
        "promise_to_payoff_score": promise_to_payoff_score,
        "seo_score": seo_score,
        "overall_quality_score": overall_quality_score,
    }