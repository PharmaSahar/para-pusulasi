from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.pipeline as pipeline
from src.fact_sources import FactSourceError, FactValue, FallbackFXProvider
from src.factual_freshness import FactCheckFailed, validate_script_factual_freshness


class MockProvider:
    def __init__(self, usd_try: float = 46.5, source: str = "trusted_fx_provider"):
        self.usd_try = usd_try
        self.source = source

    def get_usd_try(self) -> FactValue:
        return FactValue(name="USD/TRY", value=self.usd_try, source=self.source)


class BrokenProvider:
    def get_usd_try(self) -> FactValue:
        raise FactSourceError("provider_unreachable")


def test_valid_current_fx_claim_passes_with_provider():
    script = "Bugun USD/TRY 46-47 TL bandinda seyrediyor."
    metadata = validate_script_factual_freshness(script, MockProvider(usd_try=46.6))

    assert metadata["fact_check_status"] == "passed"
    assert metadata["checked_at"]
    assert metadata["sources"] == ["trusted_fx_provider"]
    assert "USD/TRY" in metadata["volatile_claims_checked"]


def test_stale_usd_try_claim_fails():
    script = "Dolar/TL bugun 30-35 TL araliginda."

    with pytest.raises(FactCheckFailed) as err:
        validate_script_factual_freshness(script, MockProvider(usd_try=46.7), tolerance_pct=0.05)

    assert "USD/TRY stale claim" in str(err.value)


def test_unverifiable_financial_claim_fails():
    script = "Turkiye'de enflasyon su an %22 seviyesinde."

    with pytest.raises(FactCheckFailed) as err:
        validate_script_factual_freshness(script, MockProvider())

    assert "unverifiable_volatile_claim" in str(err.value)


def test_non_volatile_script_passes():
    script = "Bugun yatirim disiplininin uzun vadeli onemini anlatiyoruz."
    metadata = validate_script_factual_freshness(script, MockProvider())

    assert metadata["fact_check_status"] == "passed"
    assert metadata["checked_at"]
    assert metadata["volatile_claims_checked"] == []
    assert metadata["historical_claims_exempted"] == []


def test_historical_claim_passes_without_live_comparison():
    script = "2021'de USD/TRY 8 TL idi, gecmiste bu seviyeler gorulmustu."
    metadata = validate_script_factual_freshness(script, MockProvider(usd_try=46.7))

    assert metadata["fact_check_status"] == "passed"
    assert metadata["volatile_claims_checked"] == []
    assert metadata["historical_claims_exempted"]


def test_fallback_provider_uses_second_source_when_primary_down():
    provider = FallbackFXProvider([BrokenProvider(), MockProvider(usd_try=46.7, source="fallback_fx")])
    metadata = validate_script_factual_freshness("USD/TRY 46-47 TL bandinda.", provider)

    assert metadata["fact_check_status"] == "passed"
    assert metadata["sources"] == ["fallback_fx"]


def test_provider_unreachable_fails_closed_when_all_sources_down():
    provider = FallbackFXProvider([BrokenProvider()])

    with pytest.raises(FactCheckFailed) as err:
        validate_script_factual_freshness("USD/TRY 46-47 TL bandinda.", provider)

    assert "fx_source_unavailable" in str(err.value)


def test_pipeline_fact_check_prevents_tts_render_upload_and_sends_alert(monkeypatch, tmp_path):
    alerts: list[str] = []

    class FakeConfig:
        channel_id = "test_channel"
        scripts_dir = str(tmp_path / "scripts")
        output_dir = str(tmp_path / "output")
        videos_dir = str(tmp_path / "videos")
        prompt_version = "test"
        channel_dna_version = "test"
        thumbnail_strategy = "test"
        tts_strategy = "test"
        niche = "kisisel_finans"
        default_category_id = "27"

        def ensure_directories(self):
            for path in [self.scripts_dir, self.output_dir, self.videos_dir]:
                tmp_path.joinpath(path.split(str(tmp_path))[-1].lstrip("/")).mkdir(parents=True, exist_ok=True)

    class FakeContent:
        title = "Dolar/TL bugun 30-35 TL"
        description = "desc"
        tags = ["USD", "TRY"]
        script = "Dolar/TL bugun 30-35 TL bandinda."
        thumbnail_prompt = "thumb"
        category_id = "27"
        niche = "kisisel_finans"
        hook = "hook"
        next_video_teaser = "teaser"
        pexels_search = "fx"
        chart_data = {}
        prompt_metadata = {}
        channel_dna_metadata = {}
        quality_score_metadata = {}
        created_at = "2026-07-08T00:00:00"

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            pass

        def generate_and_save(self, topic=None):
            return FakeContent()

    class FailIfCalledTTSEngine:
        def __init__(self, *args, **kwargs):
            pass

        def generate_audio(self, script):
            raise AssertionError("TTS should not be called after failed fact check")

    class FailIfCalledVideoCreator:
        def __init__(self, *args, **kwargs):
            pass

        def create_video(self, *args, **kwargs):
            raise AssertionError("Render should not be called after failed fact check")

        def create_thumbnail(self, *args, **kwargs):
            raise AssertionError("Thumbnail should not be called after failed fact check")

    class FailIfCalledUploader:
        def __init__(self, *args, **kwargs):
            pass

        def upload_video(self, *args, **kwargs):
            raise AssertionError("Upload should not be called after failed fact check")

    monkeypatch.setattr(pipeline, "_default_config", FakeConfig())
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FailIfCalledTTSEngine)
    monkeypatch.setattr(pipeline, "VideoCreator", FailIfCalledVideoCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", FailIfCalledUploader)
    monkeypatch.setattr(pipeline, "build_analytics_join_metadata", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_editor_review_metadata", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_render_metrics", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: MockProvider(usd_try=46.7))
    monkeypatch.setattr(
        pipeline,
        "validate_script_factual_freshness",
        lambda script, provider: (_ for _ in ()).throw(FactCheckFailed("USD/TRY stale claim: script='Dolar/TL bugun 30-35 TL bandinda.' live=46.70 outside [28.50, 31.50]")),
    )
    monkeypatch.setattr("src.scheduler_utils.send_telegram", lambda message: alerts.append(message))
    monkeypatch.setattr(pipeline, "generate_content_id", lambda: "content_test")
    monkeypatch.setattr(pipeline, "generate_run_id", lambda: "run_test")

    with pytest.raises(RuntimeError, match="failed_fact_check"):
        pipeline.run_full_pipeline(channel_cfg=FakeConfig(), publish_at="2026-07-08T20:00:00+03:00")

    assert alerts
    assert "Fact Check FAIL" in alerts[0]
    assert "USD/TRY stale claim" in alerts[0]
