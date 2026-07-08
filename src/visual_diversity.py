"""Deterministic thumbnail prompt diversity guard.

This module is fail-safe by design: if a candidate prompt violates diversity
rules, it generates an alternate concept instead of blocking the pipeline.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any


_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "from", "into", "to", "of", "in", "on", "at", "by",
    "video", "short", "shorts", "thumbnail", "concept", "style", "mood", "topic", "about",
}

_STYLE_ROTATION = [
    "editorial_photo",
    "cinematic_realism",
    "flat_illustration",
    "infographic_minimal",
    "isometric_3d",
    "retro_poster",
    "macro_detail",
    "documentary_frame",
]

_ANGLE_ROTATION = [
    "eye-level close-up",
    "low-angle dramatic",
    "top-down composition",
    "wide establishing frame",
    "three-quarter portrait",
    "over-shoulder framing",
]

_BACKGROUND_ROTATION = [
    "city skyline with depth blur",
    "minimal studio with geometric shapes",
    "data wall with glowing overlays",
    "workspace desk with layered props",
    "outdoor architectural backdrop",
    "abstract gradient environment",
]

_MOOD_ROTATION = [
    "bold",
    "analytical",
    "calm",
    "urgent",
    "optimistic",
    "premium",
]

_PALETTE_ROTATION = [
    "teal, charcoal, white",
    "amber, navy, ivory",
    "crimson, black, steel",
    "mint, slate, silver",
    "royal blue, graphite, sand",
]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> set[str]:
    normalized = _normalize_text(text)
    parts = re.findall(r"[a-z0-9]{3,}", normalized)
    return {p for p in parts if p not in _STOPWORDS}


def topic_similarity(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def build_prompt_fingerprint(record: dict[str, Any]) -> str:
    fields = [
        _normalize_text(str(record.get("thumbnail_prompt", ""))),
        _normalize_text(str(record.get("visual_style", ""))),
        _normalize_text(str(record.get("main_subject", ""))),
        _normalize_text(str(record.get("background", ""))),
        _normalize_text(str(record.get("camera_angle", ""))),
        _normalize_text(str(record.get("mood", ""))),
    ]
    digest = hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()
    return digest


def _day_key(value: str | None = None) -> str:
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.date().isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).date().isoformat()


def _entry_datetime(item: dict[str, Any]) -> datetime:
    created_at = str(item.get("created_at") or "").strip()
    if created_at:
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            pass

    day = str(item.get("day") or "").strip()
    if day:
        try:
            return datetime.fromisoformat(day + "T00:00:00+00:00")
        except Exception:
            pass

    return datetime.now(timezone.utc)


def _is_within_last_days(item: dict[str, Any], days: int) -> bool:
    days = max(1, int(days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return _entry_datetime(item) >= cutoff


def _extract_subject(topic: str, fallback: str) -> str:
    toks = list(_tokens(topic))
    if not toks:
        return fallback
    return " ".join(toks[:3])


def _build_prompt(topic: str, concept: dict[str, str], seed_prompt: str) -> str:
    return (
        f"{topic}. Distinct thumbnail concept: {concept['main_subject']} in {concept['background']}, "
        f"{concept['camera_angle']} camera, {concept['mood']} mood, {concept['visual_style']} style, "
        f"palette {concept['color_palette']}. Seed: {seed_prompt}"
    )


def _candidate_concept(
    *,
    profile: dict[str, Any],
    topic: str,
    slot: str,
    content_type: str,
    attempt: int,
) -> dict[str, str]:
    slot_styles = dict(profile.get("slot_styles") or {})
    base_style = slot_styles.get(slot) or profile.get("visual_style") or _STYLE_ROTATION[0]
    style_idx = (_STYLE_ROTATION.index(base_style) if base_style in _STYLE_ROTATION else 0)

    # Push short/video apart on the same day by offsetting style index.
    type_offset = 2 if content_type == "short" else 0
    idx = (style_idx + type_offset + attempt) % len(_STYLE_ROTATION)

    main_subject_seed = profile.get("character_rule") or "no-character"
    main_subject = _extract_subject(topic, str(main_subject_seed))
    if profile.get("character_rule") and profile.get("character_rule") != "no-character":
        main_subject = f"{profile.get('character_rule')} focused on {main_subject}"

    return {
        "visual_style": _STYLE_ROTATION[idx],
        "main_subject": main_subject,
        "background": _BACKGROUND_ROTATION[(idx + attempt) % len(_BACKGROUND_ROTATION)]
        if attempt
        else str(profile.get("background") or _BACKGROUND_ROTATION[idx % len(_BACKGROUND_ROTATION)]),
        "camera_angle": _ANGLE_ROTATION[(idx + attempt) % len(_ANGLE_ROTATION)]
        if attempt
        else str(profile.get("camera_angle") or _ANGLE_ROTATION[idx % len(_ANGLE_ROTATION)]),
        "mood": _MOOD_ROTATION[(idx + attempt) % len(_MOOD_ROTATION)]
        if attempt
        else str(profile.get("mood") or _MOOD_ROTATION[idx % len(_MOOD_ROTATION)]),
        "color_palette": _PALETTE_ROTATION[(idx + attempt) % len(_PALETTE_ROTATION)]
        if attempt
        else str(profile.get("color_palette") or _PALETTE_ROTATION[idx % len(_PALETTE_ROTATION)]),
    }


def _evaluate_rules(candidate: dict[str, Any], recent: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    fingerprint = candidate["fingerprint"]
    channel_id = candidate["channel_id"]
    slot = candidate["slot"]
    content_type = candidate["content_type"]
    day = candidate["day"]

    for item in recent:
        if item.get("fingerprint") == fingerprint:
            reasons.append("fingerprint_duplicate")
            break

    # Same channel: same main subject + background in recent 7-day window.
    for item in recent:
        if item.get("channel_id") != channel_id:
            continue
        if not _is_within_last_days(item, 7):
            continue
        if (
            _normalize_text(str(item.get("main_subject"))) == _normalize_text(str(candidate.get("main_subject")))
            and _normalize_text(str(item.get("background"))) == _normalize_text(str(candidate.get("background")))
        ):
            reasons.append("channel_subject_background_repeat")
            break

    # Same day same channel: video and short must not share style.
    for item in recent:
        if item.get("channel_id") != channel_id or item.get("day") != day:
            continue
        if item.get("content_type") != content_type and _normalize_text(str(item.get("visual_style"))) == _normalize_text(str(candidate.get("visual_style"))):
            reasons.append("same_day_video_short_style_collision")
            break

    # Same day same channel morning/evening style should differ.
    for item in recent:
        if item.get("channel_id") != channel_id or item.get("day") != day:
            continue
        if item.get("slot") != slot and _normalize_text(str(item.get("visual_style"))) == _normalize_text(str(candidate.get("visual_style"))):
            reasons.append("same_channel_slot_style_collision")
            break

    # More than 2 channels cannot share same style in same slot/day.
    style = _normalize_text(str(candidate.get("visual_style")))
    channels_using_style = {
        str(item.get("channel_id"))
        for item in recent
        if item.get("day") == day
        and item.get("slot") == slot
        and _normalize_text(str(item.get("visual_style"))) == style
    }
    channels_using_style.add(channel_id)
    if len(channels_using_style) > 2:
        reasons.append("slot_style_overused_across_channels")

    # Topic similarity across channels in same day.
    for item in recent:
        if item.get("day") != day or item.get("channel_id") == channel_id:
            continue
        if topic_similarity(str(item.get("topic", "")), str(candidate.get("topic", ""))) >= 0.8:
            reasons.append("cross_channel_topic_too_similar")
            break

    # Repeated face/character/pose/background combinations.
    combo = (
        _normalize_text(str(candidate.get("main_subject"))),
        _normalize_text(str(candidate.get("camera_angle"))),
        _normalize_text(str(candidate.get("background"))),
    )
    for item in recent:
        item_combo = (
            _normalize_text(str(item.get("main_subject"))),
            _normalize_text(str(item.get("camera_angle"))),
            _normalize_text(str(item.get("background"))),
        )
        if combo == item_combo:
            reasons.append("subject_pose_background_repeat")
            break

    return sorted(set(reasons))


def enforce_thumbnail_diversity(
    *,
    channel_id: str,
    content_type: str,
    slot: str,
    topic: str,
    thumbnail_prompt: str,
    profile: dict[str, Any],
    recent_history: list[dict[str, Any]],
    publish_at: str | None = None,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Return accepted prompt + concept metadata with fail-safe regeneration."""
    day = _day_key(publish_at)
    seed_prompt = thumbnail_prompt or topic
    rejected: list[dict[str, Any]] = []

    for attempt in range(max(1, max_attempts)):
        concept = _candidate_concept(
            profile=profile,
            topic=topic,
            slot=slot,
            content_type=content_type,
            attempt=attempt,
        )
        prompt = _build_prompt(topic, concept, seed_prompt)
        candidate = {
            "channel_id": channel_id,
            "content_type": content_type,
            "slot": slot,
            "day": day,
            "topic": topic,
            "thumbnail_prompt": prompt,
            **concept,
        }
        candidate["fingerprint"] = build_prompt_fingerprint(candidate)

        reasons = _evaluate_rules(candidate, recent_history)
        # Near-duplicate prompt guard.
        if not reasons:
            for item in recent_history:
                sim = topic_similarity(str(item.get("thumbnail_prompt", "")), prompt)
                if sim >= 0.78:
                    reasons.append("near_duplicate_prompt")
                    break

        if not reasons:
            return {
                "accepted": True,
                "regenerated": attempt > 0,
                "attempts": attempt + 1,
                "rejected_attempts": rejected,
                "record": candidate,
            }

        rejected.append({"attempt": attempt + 1, "reasons": reasons, "fingerprint": candidate["fingerprint"]})

    # Fail-safe fallback: return last generated candidate even if still imperfect.
    fallback_concept = _candidate_concept(
        profile=profile,
        topic=topic,
        slot=slot,
        content_type=content_type,
        attempt=max(1, max_attempts - 1),
    )
    fallback_prompt = _build_prompt(topic, fallback_concept, seed_prompt)
    fallback = {
        "channel_id": channel_id,
        "content_type": content_type,
        "slot": slot,
        "day": day,
        "topic": topic,
        "thumbnail_prompt": fallback_prompt,
        **fallback_concept,
    }
    fallback["fingerprint"] = build_prompt_fingerprint(fallback)

    return {
        "accepted": False,
        "regenerated": True,
        "attempts": max(1, max_attempts),
        "rejected_attempts": rejected,
        "record": fallback,
    }
