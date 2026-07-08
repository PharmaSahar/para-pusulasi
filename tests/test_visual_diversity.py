import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.visual_diversity import build_prompt_fingerprint, enforce_thumbnail_diversity


def _base_profile():
    return {
        "color_palette": "gold, navy, graphite",
        "visual_style": "editorial_photo",
        "character_rule": "analyst portrait",
        "camera_angle": "eye-level close-up",
        "background": "finance desk with monitor wall",
        "mood": "disciplined",
        "slot_styles": {"morning": "editorial_photo", "evening": "editorial_photo"},
    }


def _history_record(
    *,
    channel_id,
    content_type,
    slot,
    day,
    topic,
    thumbnail_prompt,
    visual_style,
    main_subject,
    background,
    camera_angle,
    mood,
):
    item = {
        "channel_id": channel_id,
        "content_type": content_type,
        "slot": slot,
        "day": day,
        "topic": topic,
        "thumbnail_prompt": thumbnail_prompt,
        "visual_style": visual_style,
        "main_subject": main_subject,
        "background": background,
        "color_palette": "gold, navy, graphite",
        "camera_angle": camera_angle,
        "mood": mood,
    }
    item["fingerprint"] = build_prompt_fingerprint(item)
    return item


def test_exact_duplicate_prompt_is_regenerated():
    profile = _base_profile()
    day = "2026-07-08"

    existing = _history_record(
        channel_id="kripto_rehber",
        content_type="video",
        slot="morning",
        day=day,
        topic="Bitcoin ETF momentum",
        thumbnail_prompt=(
            "Bitcoin ETF momentum. Distinct thumbnail concept: analyst portrait focused on bitcoin etf momentum "
            "in finance desk with monitor wall, eye-level close-up camera, disciplined mood, editorial_photo style, "
            "palette gold, navy, graphite. Seed: dramatic bitcoin prompt"
        ),
        visual_style="editorial_photo",
        main_subject="analyst portrait focused on bitcoin etf momentum",
        background="finance desk with monitor wall",
        camera_angle="eye-level close-up",
        mood="disciplined",
    )

    decision = enforce_thumbnail_diversity(
        channel_id="para_pusulasi",
        content_type="video",
        slot="morning",
        topic="Bitcoin ETF momentum",
        thumbnail_prompt="dramatic bitcoin prompt",
        profile=profile,
        recent_history=[existing],
        publish_at="2026-07-08T08:00:00+00:00",
    )

    assert decision["regenerated"] is True
    assert decision["record"]["fingerprint"] != existing["fingerprint"]


def test_same_channel_morning_evening_style_collision_is_rejected():
    profile = _base_profile()
    day = "2026-07-08"

    morning = _history_record(
        channel_id="para_pusulasi",
        content_type="video",
        slot="morning",
        day=day,
        topic="Budget systems",
        thumbnail_prompt="Budget systems prompt",
        visual_style="editorial_photo",
        main_subject="analyst portrait focused on budget systems",
        background="finance desk with monitor wall",
        camera_angle="eye-level close-up",
        mood="disciplined",
    )

    decision = enforce_thumbnail_diversity(
        channel_id="para_pusulasi",
        content_type="video",
        slot="evening",
        topic="Debt snowball strategy",
        thumbnail_prompt="debt strategy prompt",
        profile=profile,
        recent_history=[morning],
        publish_at="2026-07-08T20:00:00+00:00",
    )

    assert decision["regenerated"] is True
    assert decision["record"]["visual_style"] != "editorial_photo"


def test_video_and_short_same_day_cannot_share_style():
    profile = _base_profile()
    day = "2026-07-08"

    video_item = _history_record(
        channel_id="teknoloji_pusulasi",
        content_type="video",
        slot="morning",
        day=day,
        topic="AI agent workflows",
        thumbnail_prompt="AI workflow prompt",
        visual_style="flat_illustration",
        main_subject="analyst portrait focused on ai workflows",
        background="finance desk with monitor wall",
        camera_angle="eye-level close-up",
        mood="disciplined",
    )

    decision = enforce_thumbnail_diversity(
        channel_id="teknoloji_pusulasi",
        content_type="short",
        slot="morning",
        topic="AI agent workflows quick tips",
        thumbnail_prompt="AI workflow short prompt",
        profile=profile,
        recent_history=[video_item],
        publish_at="2026-07-08T08:30:00+00:00",
    )

    assert decision["regenerated"] is True
    assert decision["record"]["visual_style"] != video_item["visual_style"]


def test_slot_style_overuse_and_topic_similarity_trigger_alternative():
    profile = _base_profile()
    day = "2026-07-08"

    recent = [
        _history_record(
            channel_id="kanal_a",
            content_type="video",
            slot="morning",
            day=day,
            topic="Bitcoin ETF inflow analysis",
            thumbnail_prompt="prompt a",
            visual_style="editorial_photo",
            main_subject="analyst portrait focused on bitcoin etf",
            background="finance desk with monitor wall",
            camera_angle="eye-level close-up",
            mood="disciplined",
        ),
        _history_record(
            channel_id="kanal_b",
            content_type="video",
            slot="morning",
            day=day,
            topic="Bitcoin ETF inflow risks",
            thumbnail_prompt="prompt b",
            visual_style="editorial_photo",
            main_subject="analyst portrait focused on bitcoin etf risks",
            background="finance desk with monitor wall",
            camera_angle="eye-level close-up",
            mood="disciplined",
        ),
    ]

    decision = enforce_thumbnail_diversity(
        channel_id="kanal_c",
        content_type="video",
        slot="morning",
        topic="Bitcoin ETF inflow forecast",
        thumbnail_prompt="bitcoin etf forecast dramatic",
        profile=profile,
        recent_history=recent,
        publish_at="2026-07-08T09:00:00+00:00",
    )

    assert decision["regenerated"] is True
    assert decision["record"]["visual_style"] != "editorial_photo"
