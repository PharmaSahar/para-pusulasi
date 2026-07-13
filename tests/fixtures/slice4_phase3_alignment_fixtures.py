from __future__ import annotations

from copy import deepcopy

from src.shadow_blueprint_prompt_alignment import CalibrationFixture


def _base_blueprint(*, blueprint_id: str, channel_id: str, niche: str, audience_level: str = "beginner") -> dict:
    return {
        "schema_version": "v1",
        "blueprint_id": blueprint_id,
        "created_at": "2026-07-13T10:00:00+00:00",
        "channel_profile": {
            "schema_version": "v1",
            "channel_id": channel_id,
            "name": channel_id,
            "niche": niche,
            "audience_summary": "audience",
            "experience_level": audience_level,
            "tone": "educational",
            "authority_level": "high" if niche in {"borsa", "kripto", "kisisel_finans"} else "medium",
            "educational_depth": "balanced",
            "preferred_video_length_seconds": 700,
            "preferred_shorts_length_seconds": 55,
            "preferred_cta_style": "educational",
            "risk_tolerance": "low" if niche in {"borsa", "kripto", "kisisel_finans"} else "medium",
            "monetization_suitability": "high",
            "evergreen_ratio": 0.6,
            "trend_ratio": 0.3,
            "upload_frequency_per_week": 7,
            "playlist_strategy": "clustered_series_by_topic",
            "canonical_channel_id": channel_id,
        },
        "audience_profile": {
            "schema_version": "v1",
            "audience_id": f"aud_{blueprint_id}",
            "primary_age_range": "25-50",
            "experience_level": audience_level,
            "primary_motivation": "improve outcomes",
            "pain_points": ["noise"],
            "desired_outcomes": ["clarity"],
            "language": "tr",
        },
        "topic_intent": {
            "schema_version": "v1",
            "topic_id": f"topic_{blueprint_id}",
            "topic_title": "Risk yonetimi",
            "topic_kind": "evergreen",
            "urgency": "medium",
            "expected_ctr_style": "result_oriented",
            "expected_retention_style": "steady",
            "expected_thumbnail_style": "authority",
            "recommended_narrative_structure": "educational_lecture",
        },
        "content_goal": {
            "schema_version": "v1",
            "goal_id": f"goal_{blueprint_id}",
            "primary_outcome": "educational value",
            "success_metric": "avg_percentage_viewed",
            "target_surface": "search",
            "performance_horizon": "mid_term",
        },
        "narrative_goal": {
            "schema_version": "v1",
            "narrative_template": "educational_lecture",
            "structure_notes": "clear sections",
            "psychological_strategy": "reduce uncertainty",
            "expected_payoff_window_seconds": 220,
        },
        "hook_goal": {
            "schema_version": "v1",
            "hook_type": "question",
            "psychological_intent": "capture attention",
            "ideal_audience": audience_level,
            "estimated_retention_objective": "increase first 30 second retention",
        },
        "retention_goal": {
            "schema_version": "v1",
            "opening_plan": "value first",
            "first_30_seconds_plan": "state objective",
            "curiosity_refresh_interval_seconds": 45,
            "payoff_timing_seconds": 210,
            "cta_timing_seconds": 420,
            "ending_plan": "summary and next step",
        },
        "thumbnail_goal": {
            "schema_version": "v1",
            "emotional_emphasis": "medium",
            "facial_emphasis": "low",
            "object_emphasis": "high",
            "contrast_level": "high",
            "information_density": "balanced",
            "text_length_target": 4,
            "curiosity_level": "medium",
            "urgency_level": "medium",
            "trust_signal_level": "high",
            "authority_signal_level": "high",
        },
        "seo_goal": {
            "schema_version": "v1",
            "title_objective": "clear value proposition",
            "keyword_strategy": "keyword strategy for channel niche",
            "search_intent": "informational",
            "browse_intent": "adjacent recommendations",
            "suggested_traffic_objective": "related series",
            "playlist_relevance_plan": "clustered_series_by_topic",
            "tag_relevance_plan": "high intent",
            "hashtag_strategy": "concise",
        },
        "shorts_goal": {
            "schema_version": "v1",
            "clip_objective": "complete short insight",
            "hook_type": "question",
            "context_length_seconds": 12,
            "payoff_timing_seconds": 28,
            "ending_style": "cta_bridge",
            "looping_suitability": "medium",
            "continuation_suitability": "high",
        },
        "discovery_goal": {
            "schema_version": "v1",
            "primary_surface": "search",
            "secondary_surfaces": ["browse", "suggested"],
            "playlist_strategy": "clustered_series_by_topic",
            "cards_strategy": "bridge_to_related_topic",
            "end_screen_strategy": "next_logical_step",
        },
        "performance_expectation": {
            "schema_version": "v1",
            "expected_ctr": 0.08,
            "expected_average_view_duration_seconds": 220,
            "expected_average_percentage_viewed": 0.42,
            "expected_shorts_completion_rate": 0.72,
            "target_kpi": "avg_percentage_viewed",
        },
    }


def _fixture(
    *,
    idx: int,
    title: str,
    prompt_text: str,
    expected_states: dict[str, str],
    expected_conflict_codes: tuple[str, ...] = (),
    expected_failure_sources: dict[str, str] | None = None,
    coverage_range: tuple[float, float] = (0.0, 1.0),
    conflict_range: tuple[float, float] = (0.0, 1.0),
    prohibited_findings: tuple[str, ...] = (),
    channel_id: str = "para_pusulasi",
    niche: str = "kisisel_finans",
    audience_level: str = "beginner",
    artifacts: dict | None = None,
    expect_analyzer_failure: bool = False,
) -> CalibrationFixture:
    blueprint = _base_blueprint(
        blueprint_id=f"bp_fx{idx:02d}",
        channel_id=channel_id,
        niche=niche,
        audience_level=audience_level,
    )
    if idx == 5:
        blueprint["topic_intent"]["topic_kind"] = "evergreen"
    if idx == 8:
        blueprint["topic_intent"]["topic_title"] = "BIST analysis"

    payload_artifacts = {
        "title": "Egitim odakli baslik",
        "script": "Belirsizlik ve risk yonetimi anlatilir.",
        "description": "SEO keyword strategy ve search intent odakli aciklama.",
        "thumbnail_prompt": "trusted educational chart",
        "short_script": "Kisa ve tamamlanmis fikir",
    }
    if artifacts:
        payload_artifacts.update(artifacts)

    return CalibrationFixture(
        fixture_id=f"fx{idx:02d}",
        title=title,
        blueprint=deepcopy(blueprint),
        prompt_text=prompt_text,
        prompt_type="content_generation",
        template_id="fixture_content_v1",
        artifacts=payload_artifacts,
        expected_states=dict(expected_states),
        expected_conflict_codes=tuple(expected_conflict_codes),
        expected_failure_sources=dict(expected_failure_sources or {}),
        coverage_score_range=tuple(coverage_range),
        conflict_score_range=tuple(conflict_range),
        prohibited_findings=tuple(prohibited_findings),
        expect_analyzer_failure=expect_analyzer_failure,
    )


def build_phase3_calibration_fixtures() -> list[CalibrationFixture]:
    fixtures = [
        _fixture(idx=1, title="Fully aligned educational-finance prompt", prompt_text="channel audience topic narrative hook retention thumbnail seo shorts discovery safety json", expected_states={"channel_tone": "PRESENT_WEAK", "hook_type": "PRESENT_WEAK"}, coverage_range=(0.2, 1.0), conflict_range=(0.0, 0.2), prohibited_findings=("RISK_MANAGEMENT_GUARANTEED_RETURN_CONFLICT",)),
        _fixture(idx=2, title="Blueprint requires a hook but prompt omits it", prompt_text="topic narrative seo json without opening instruction", expected_states={"hook_type": "MISSING"}, expected_failure_sources={"hook_type": "PROMPT_COVERAGE_GAP"}, conflict_range=(0.0, 0.2)),
        _fixture(idx=3, title="Blueprint requires uncertainty but prompt uses certainty", prompt_text="kesin kazanc garanti getiri insider sirri hemen al", expected_states={"safety_uncertainty_language": "CONFLICTING"}, expected_conflict_codes=("UNCERTAINTY_CERTAINTY_CONFLICT", "RISK_MANAGEMENT_GUARANTEED_RETURN_CONFLICT"), expected_failure_sources={"safety_uncertainty_language": "PROMPT_CONFLICT"}, conflict_range=(0.02, 1.0), channel_id="borsa_akademi", niche="borsa"),
        _fixture(idx=4, title="Beginner audience with expert-only prompt", prompt_text="advanced expert only deep jargon", expected_states={"channel_audience_level": "CONFLICTING"}, expected_conflict_codes=("AUDIENCE_LEVEL_MISMATCH",), expected_failure_sources={"channel_audience_level": "PROMPT_CONFLICT"}, conflict_range=(0.02, 1.0), channel_id="girisim_okulu", niche="girisimcilik"),
        _fixture(idx=5, title="Evergreen topic with breaking-news prompt", prompt_text="breaking son dakika last 24 hours", expected_states={"topic_evergreen_trend": "CONFLICTING"}, expected_conflict_codes=("EVERGREEN_BREAKING_NEWS_CONFLICT",), conflict_range=(0.02, 1.0)),
        _fixture(idx=6, title="Safe finance blueprint with pump-style title instruction", prompt_text="pump x kat kazandir simdi al", expected_states={"safety_uncertainty_language": "CONFLICTING"}, expected_conflict_codes=("RISK_MANAGEMENT_GUARANTEED_RETURN_CONFLICT",), conflict_range=(0.02, 1.0), channel_id="kripto_rehber", niche="kripto"),
        _fixture(idx=7, title="Correct ticker across blueprint and prompt", prompt_text="BIST ticker analysis with safety", expected_states={"safety_ticker_company_consistency": "PRESENT_WEAK"}, conflict_range=(0.0, 0.2), artifacts={"title": "BIST strategy", "script": "BIST and risk disclaimers", "description": "bist analysis and caution"}, channel_id="borsa_akademi", niche="borsa"),
        _fixture(idx=8, title="Wrong ticker in prompt", prompt_text="BIST analysis with TSLA pivot", expected_states={"safety_ticker_company_consistency": "CONFLICTING"}, expected_conflict_codes=("TICKER_COMPANY_MISMATCH",), conflict_range=(0.02, 1.0), artifacts={"title": "BIST strategy", "script": "BIST only"}, channel_id="borsa_akademi", niche="borsa"),
        _fixture(idx=9, title="Narrative structure fully represented", prompt_text="narrative structure sequence payoff evidence conclusion", expected_states={"narrative_structure": "PRESENT_WEAK"}),
        _fixture(idx=10, title="Narrative structure missing", prompt_text="short generic instruction", expected_states={"narrative_structure": "MISSING"}),
        _fixture(idx=11, title="Retention plan fully represented", prompt_text="retention first 30 pacing curiosity cta timing", expected_states={"retention_first_30s": "PRESENT_WEAK"}),
        _fixture(idx=12, title="Retention plan absent", prompt_text="topic and seo only", expected_states={"retention_first_30s": "MISSING"}),
        _fixture(idx=13, title="Thumbnail trust goal aligned", prompt_text="thumbnail trust educational low urgency", expected_states={"thumbnail_trust_vs_urgency": "PRESENT_WEAK"}),
        _fixture(idx=14, title="Thumbnail wealth/urgency conflict", prompt_text="thumbnail son sans hemen zengin ol", expected_states={"thumbnail_trust_vs_urgency": "CONFLICTING"}, expected_conflict_codes=("TRUST_URGENCY_CONFLICT",)),
        _fixture(idx=15, title="Search-intent SEO alignment", prompt_text="seo keyword search intent tags hashtags", expected_states={"seo_search_intent": "PRESENT_WEAK"}),
        _fixture(idx=16, title="SEO objective missing", prompt_text="narrative only", expected_states={"seo_search_intent": "MISSING"}),
        _fixture(idx=17, title="Playlist/cards/end-screen unsupported", prompt_text="discovery playlist cards end screen", expected_states={"discovery_cards": "UNSUPPORTED", "discovery_end_screen": "UNSUPPORTED"}),
        _fixture(idx=18, title="Complete Shorts planning alignment", prompt_text="shorts hook context payoff ending looping continuation", expected_states={"shorts_hook": "PRESENT_WEAK", "shorts_context": "PRESENT_WEAK"}, channel_id="kariyer_pusulasi", niche="kariyer"),
        _fixture(idx=19, title="Fixed-duration mid-content clipping conflict", prompt_text="fixed-duration mid-content clipping instruction", expected_states={"shorts_sentence_completeness": "CONFLICTING"}, expected_conflict_codes=("SHORTS_COMPLETENESS_CLIPPING_CONFLICT",), channel_id="kariyer_pusulasi", niche="kariyer"),
        _fixture(idx=20, title="Prompt aligned but generated title mismatched", prompt_text="channel audience topic hook retention seo", expected_states={"seo_title_objective": "PRESENT_WEAK"}, artifacts={"title": "Alakasiz baslik xyz", "script": "aligned script"}),
        _fixture(idx=21, title="Prompt aligned but generated script repetitive", prompt_text="narrative retention hook", expected_states={"narrative_structure": "PRESENT_WEAK"}, artifacts={"script": "Ayni cumle. Ayni cumle. Ayni cumle."}),
        _fixture(idx=22, title="Blueprint gap causing artifact gap", prompt_text="topic only", expected_states={"retention_ending": "MISSING"}),
        _fixture(idx=23, title="Prompt conflict causing artifact conflict", prompt_text="hemen al simdi sat", expected_states={"safety_uncertainty_language": "CONFLICTING"}, expected_conflict_codes=("NEUTRAL_ANALYSIS_BUYSELL_PRESSURE_CONFLICT",), channel_id="borsa_akademi", niche="borsa"),
        _fixture(idx=24, title="Feature not implemented", prompt_text="cards end screen strategy", expected_states={"discovery_session_continuation": "UNSUPPORTED"}),
        _fixture(idx=25, title="Data unavailable", prompt_text="safety source requirements", expected_states={"safety_source_requirements": "UNKNOWN"}),
        _fixture(idx=26, title="Analyzer exception", prompt_text="valid prompt text", expected_states={}, expect_analyzer_failure=True),
        _fixture(idx=27, title="Malformed prior storage line", prompt_text="basic alignment prompt", expected_states={"channel_tone": "MISSING"}),
        _fixture(idx=28, title="Unicode/Turkish finance prompt", prompt_text="Kanal tonu eğitimsel; belirsizlik dili kullanılmalı, yatırım tavsiyesi değildir.", expected_states={"channel_tone": "PRESENT_WEAK", "safety_uncertainty_language": "PRESENT_WEAK"}, channel_id="para_pusulasi", niche="kisisel_finans"),
        _fixture(idx=29, title="Safe negation language", prompt_text="kesin getiri degildir, yatırım tavsiyesi değildir, garanti yoktur", expected_states={"safety_uncertainty_language": "PRESENT_WEAK"}, prohibited_findings=("RISK_MANAGEMENT_GUARANTEED_RETURN_CONFLICT", "UNCERTAINTY_CERTAINTY_CONFLICT"), channel_id="para_pusulasi", niche="kisisel_finans"),
        _fixture(idx=30, title="Dangerous financial assertion", prompt_text="garanti getiri insider secret x kat kazandir", expected_states={"safety_uncertainty_language": "CONFLICTING"}, expected_conflict_codes=("RISK_MANAGEMENT_GUARANTEED_RETURN_CONFLICT", "FINANCE_INSIDER_SECRET_CONFLICT"), channel_id="kripto_rehber", niche="kripto"),
    ]

    return fixtures
