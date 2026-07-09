import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _profile():
    return {
        "color_palette": "gold, navy, graphite",
        "visual_style": "editorial_photo",
        "character_rule": "analyst portrait",
        "camera_angle": "eye-level close-up",
        "background": "finance desk with monitor wall",
        "mood": "disciplined",
        "slot_styles": {"morning": "editorial_photo", "evening": "editorial_photo"},
    }


def test_thumbnail_experiment_bundle_returns_two_competing_variants():
    from src.thumbnail_experiments import build_thumbnail_experiment_bundle

    bundle = build_thumbnail_experiment_bundle(
        channel_id="para_pusulasi",
        content_type="video",
        slot="morning",
        topic="2026 konut alimi",
        title="2026 Konut Alimi Herkesi Yaniltan 5 Hata",
        thumbnail_prompt="Kira carpani ve alım kararı",
        profile=_profile(),
        recent_history=[],
        publish_at="2026-07-09T08:00:00+00:00",
    )

    assert bundle["selected_variant_id"] in {"A", "B"}
    assert len(bundle["variants"]) == 2
    assert bundle["selected_prompt"]
    assert bundle["record"]["thumbnail_prompt"] == bundle["selected_prompt"]


def test_thumbnail_experiment_bundle_prefers_higher_attention_prompt():
    from src.thumbnail_experiments import build_thumbnail_experiment_bundle

    bundle = build_thumbnail_experiment_bundle(
        channel_id="para_pusulasi",
        content_type="video",
        slot="morning",
        topic="2026 emtia piyasasi",
        title="Emtia Piyasasinda Oynakligi Yanlis Okuyorsun",
        thumbnail_prompt="business finance concept",
        profile=_profile(),
        recent_history=[],
        publish_at="2026-07-09T08:00:00+00:00",
    )

    scores = {item["variant_id"]: item["thumbnail_attention_score"] for item in bundle["variants"]}
    assert scores[bundle["selected_variant_id"]] == max(scores.values())
