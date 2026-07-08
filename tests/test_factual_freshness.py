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


def test_pipeline_retries_once_for_unverifiable_claim_and_continues(monkeypatch, tmp_path):
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
        def __init__(self, title: str, script: str):
            self.title = title
            self.description = "desc"
            self.tags = ["USD", "TRY"]
            self.script = script
            self.thumbnail_prompt = "thumb"
            self.category_id = "27"
            self.niche = "kisisel_finans"
            self.hook = "hook"
            self.next_video_teaser = "teaser"
            self.pexels_search = "fx"
            self.chart_data = {}
            self.prompt_metadata = {}
            self.channel_dna_metadata = {}
            self.quality_score_metadata = {}
            self.created_at = "2026-07-08T00:00:00"

        def seo_description(self):
            return "seo"

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            self.calls: list[tuple[str | None, str | None]] = []
            self.model = "fake-model"

        def generate_and_save(self, topic=None, additional_guidance=None):
            self.calls.append((topic, additional_guidance))
            if len(self.calls) == 1:
                return FakeContent("First title", "BIST 100 bugun yukseliyor")
            return FakeContent("Retry title", "Uzun vadeli veri odakli yorum")

    class FakeTTS:
        def __init__(self, channel_cfg=None):
            pass

        def generate_audio(self, script):
            return str(tmp_path / "audio.mp3")

    class FakeFetcher:
        def __init__(self, channel_cfg=None):
            pass

        def fetch_video_clips(self, title, count=4, output_dir="", query_override=None):
            return [str(tmp_path / "clip.mp4")]

        def fetch_thumbnail_photo(self, title):
            return str(tmp_path / "thumb.jpg")

    class FakeCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_video(self, audio_path, title, image_paths=None, script=None):
            return str(tmp_path / "video.mp4")

        def create_thumbnail(self, title, image_path=None):
            return str(tmp_path / "thumb-out.jpg")

    class FakeUploader:
        def __init__(self, channel_cfg=None):
            self.calls = 0

        def upload_video(self, **kwargs):
            self.calls += 1
            return "video-id" if self.calls == 1 else "short-id"

    class FakeShortsCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_short(self, script, title, hook, image_paths=None):
            return str(tmp_path / "short.mp4")

    generator_instances: list[FakeGenerator] = []

    def build_generator(channel_cfg=None):
        instance = FakeGenerator(channel_cfg=channel_cfg)
        generator_instances.append(instance)
        return instance

    validation_calls = {"count": 0}

    def fake_validate(script, provider):
        validation_calls["count"] += 1
        if validation_calls["count"] == 1:
            raise FactCheckFailed("unverifiable_volatile_claim: 'BIST 100' (stock)")
        return {
            "fact_check_status": "passed",
            "checked_at": "2026-07-08T00:00:00+00:00",
            "sources": [],
            "volatile_claims_checked": [],
        }

    monkeypatch.setattr(pipeline, "_default_config", FakeConfig())
    monkeypatch.setattr(pipeline, "ContentGenerator", build_generator)
    monkeypatch.setattr(pipeline, "TTSEngine", FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", FakeUploader)
    monkeypatch.setattr(pipeline, "build_analytics_join_metadata", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_editor_review_metadata", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_render_metrics", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: MockProvider(usd_try=46.7))
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", fake_validate)
    monkeypatch.setattr("src.scheduler_utils.send_telegram", lambda message: alerts.append(message))
    monkeypatch.setattr(pipeline, "generate_content_id", lambda: "content_test")
    monkeypatch.setattr(pipeline, "generate_run_id", lambda: "run_test")

    import sys
    from types import ModuleType

    fake_shorts = ModuleType("src.shorts_creator")
    fake_shorts.ShortsCreator = FakeShortsCreator
    monkeypatch.setitem(sys.modules, "src.shorts_creator", fake_shorts)

    result = pipeline.run_full_pipeline(channel_cfg=FakeConfig(), publish_at="2026-07-08T20:00:00+03:00")

    assert result["video_id"] == "video-id"
    assert result["fact_check_regeneration_attempted"] is True
    assert result["title"] == "Retry title"
    assert result["fact_check_regeneration_topic"] == "Borsa ve hisse yorumlarinda fiyat hedefi vermeden risk yonetimi rehberi"
    assert validation_calls["count"] >= 2
    assert len(generator_instances) == 1
    assert len(generator_instances[0].calls) == 2
    assert generator_instances[0].calls[1][0] == "Borsa ve hisse yorumlarinda fiyat hedefi vermeden risk yonetimi rehberi"
    assert generator_instances[0].calls[1][1] is not None
    assert "FACT-CHECK SAFE MODE" in generator_instances[0].calls[1][1]
    assert "fiyat hedefi" in generator_instances[0].calls[1][1]
    assert alerts == []


def test_retry_topic_for_crypto_claim_becomes_risk_management_focused():
    retry_topic = pipeline._build_retry_topic(
        "Bitcoin 2026 sonu hedef fiyat",
        "Bitcoin 150.000$ Hedefi: 2026'da Tuzak mı Fırsat mı?",
        "failed_fact_check: unverifiable_volatile_claim: 'Bitcoin 150.000' (crypto)",
    )

    assert retry_topic == "Kripto piyasasinda fiyat hedefi vermeden risk yonetimi ve volatiliteyi anlama rehberi"


def test_retry_guidance_for_crypto_claim_bans_price_targets():
    guidance = pipeline._build_retry_guidance(
        "failed_fact_check: unverifiable_volatile_claim: 'Bitcoin 150.000' (crypto)"
    )

    assert "FACT-CHECK SAFE MODE" in guidance
    assert "Kripto fiyat hedefi" in guidance


def test_pipeline_keeps_fail_closed_when_unverifiable_retry_also_fails(monkeypatch, tmp_path):
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
        title = "Retry fail title"
        description = "desc"
        tags = ["USD", "TRY"]
        script = "BIST 100 bugun yukseliyor"
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
            self.calls = 0

        def generate_and_save(self, topic=None, additional_guidance=None):
            self.calls += 1
            return FakeContent()

    class FailIfCalledTTSEngine:
        def __init__(self, *args, **kwargs):
            pass

        def generate_audio(self, script):
            raise AssertionError("TTS should not be called after failed retry")

    monkeypatch.setattr(pipeline, "_default_config", FakeConfig())
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FailIfCalledTTSEngine)
    monkeypatch.setattr(pipeline, "build_analytics_join_metadata", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_editor_review_metadata", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_render_metrics", lambda **kwargs: {})
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: MockProvider(usd_try=46.7))
    monkeypatch.setattr(
        pipeline,
        "validate_script_factual_freshness",
        lambda script, provider: (_ for _ in ()).throw(FactCheckFailed("unverifiable_volatile_claim: 'BIST 100' (stock)")),
    )
    monkeypatch.setattr("src.scheduler_utils.send_telegram", lambda message: alerts.append(message))
    monkeypatch.setattr(pipeline, "generate_content_id", lambda: "content_test")
    monkeypatch.setattr(pipeline, "generate_run_id", lambda: "run_test")

    with pytest.raises(RuntimeError, match="failed_fact_check: unverifiable_volatile_claim"):
        pipeline.run_full_pipeline(channel_cfg=FakeConfig(), publish_at="2026-07-08T20:00:00+03:00")

    assert len(alerts) == 1
    assert "unverifiable_volatile_claim" in alerts[0]
