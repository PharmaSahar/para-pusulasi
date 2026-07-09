"""Channel-level visual identity profiles for thumbnail diversity guard."""

from __future__ import annotations

from typing import Any


DEFAULT_STYLE_POOL = [
    "editorial_photo",
    "cinematic_realism",
    "flat_illustration",
    "infographic_minimal",
    "isometric_3d",
    "retro_poster",
    "macro_detail",
    "documentary_frame",
]


CHANNEL_VISUAL_PROFILES: dict[str, dict[str, Any]] = {
    "para_pusulasi": {
        "color_palette": "gold, navy, graphite",
        "visual_style": "editorial_photo",
        "character_rule": "confident analyst",
        "camera_angle": "eye-level close-up",
        "background": "modern finance desk with market display",
        "mood": "disciplined and credible",
        "slot_styles": {"morning": "editorial_photo", "evening": "cinematic_realism"},
    },
    "borsa_akademi": {
        "color_palette": "emerald, charcoal, white",
        "visual_style": "infographic_minimal",
        "character_rule": "no-character",
        "camera_angle": "top-down data board",
        "background": "candlestick wall and notebook overlays",
        "mood": "technical and precise",
        "slot_styles": {"morning": "infographic_minimal", "evening": "macro_detail"},
    },
    "kripto_rehber": {
        "color_palette": "orange, obsidian, neon cyan",
        "visual_style": "cinematic_realism",
        "character_rule": "no-character",
        "camera_angle": "low-angle dramatic",
        "background": "cyber trading terminal at night",
        "mood": "high-energy and speculative",
        "slot_styles": {"morning": "documentary_frame", "evening": "cinematic_realism"},
    },
    "kariyer_pusulasi": {
        "color_palette": "royal blue, slate, ivory",
        "visual_style": "documentary_frame",
        "character_rule": "professional portrait",
        "camera_angle": "three-quarter portrait",
        "background": "office corridor with depth blur",
        "mood": "aspirational and focused",
        "slot_styles": {"morning": "documentary_frame", "evening": "retro_poster"},
    },
    "girisim_okulu": {
        "color_palette": "coral red, black, warm gray",
        "visual_style": "retro_poster",
        "character_rule": "founder silhouette",
        "camera_angle": "dynamic over-shoulder",
        "background": "startup war-room with sticky notes",
        "mood": "bold and disruptive",
        "slot_styles": {"morning": "flat_illustration", "evening": "retro_poster"},
    },
    "saglik_pusulasi": {
        "color_palette": "mint, teal, white",
        "visual_style": "flat_illustration",
        "character_rule": "no-character",
        "camera_angle": "clean front view",
        "background": "wellness studio with natural light",
        "mood": "calm and reassuring",
        "slot_styles": {"morning": "flat_illustration", "evening": "isometric_3d"},
    },
    "teknoloji_pusulasi": {
        "color_palette": "electric blue, graphite, silver",
        "visual_style": "isometric_3d",
        "character_rule": "no-character",
        "camera_angle": "wide-angle tech desk",
        "background": "futuristic workstation and holographic ui",
        "mood": "innovative and sharp",
        "slot_styles": {"morning": "isometric_3d", "evening": "macro_detail"},
    },
    "egitim_rehberi": {
        "color_palette": "amber, navy, cream",
        "visual_style": "infographic_minimal",
        "character_rule": "no-character",
        "camera_angle": "front board composition",
        "background": "study desk and lesson cards",
        "mood": "clear and instructive",
        "slot_styles": {"morning": "infographic_minimal", "evening": "documentary_frame"},
    },
    "gayrimenkul_tv": {
        "color_palette": "terracotta, beige, charcoal",
        "visual_style": "macro_detail",
        "character_rule": "no-character",
        "camera_angle": "drone-like exterior perspective",
        "background": "modern residential skyline",
        "mood": "premium and grounded",
        "slot_styles": {"morning": "macro_detail", "evening": "cinematic_realism"},
    },
}


def get_channel_visual_profile(channel_id: str, niche: str = "") -> dict[str, Any]:
    """Return a deterministic visual profile for a channel.

    Unknown channels get a stable fallback profile keyed by channel_id hash,
    ensuring diversity without manual profile edits.
    """
    if channel_id in CHANNEL_VISUAL_PROFILES:
        return dict(CHANNEL_VISUAL_PROFILES[channel_id])

    idx = abs(hash(channel_id)) % len(DEFAULT_STYLE_POOL)
    morning_style = DEFAULT_STYLE_POOL[idx]
    evening_style = DEFAULT_STYLE_POOL[(idx + 3) % len(DEFAULT_STYLE_POOL)]

    fallback_by_niche = {
        "kisisel_finans": "financial editorial visuals",
        "borsa": "market chart storytelling",
        "kripto": "cyber market storytelling",
        "kariyer": "career portrait storytelling",
        "girisimcilik": "startup momentum scenes",
        "saglik": "wellness and clean compositions",
        "teknoloji": "future tech compositions",
    }

    niche_hint = fallback_by_niche.get((niche or "").strip().lower(), "topic-centric visual narrative")
    return {
        "color_palette": "indigo, slate, white",
        "visual_style": morning_style,
        "character_rule": "no-character",
        "camera_angle": "eye-level",
        "background": niche_hint,
        "mood": "informative and distinct",
        "slot_styles": {"morning": morning_style, "evening": evening_style},
    }
