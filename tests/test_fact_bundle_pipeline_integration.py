from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import src.pipeline as pipeline
import src.fact_bundle_pipeline_adapter as adapter_module


@dataclass
class FakeContent:
    title: str = "Test Baslik"
    created_at: str = "2026-07-08T10:00:00"
    script: str = "Bu metin volatil finansal iddia icermez."
    description: str = "Aciklama"
    tags: list[str] = None
    niche: str = "finance"
    thumbnail_prompt: str = "thumbnail prompt"
    prompt_metadata: dict | None = None
    channel_dna_metadata: dict | None = None
    quality_score_metadata: dict | None = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = ["finans"]


class FakeGenerator:
    def __init__(self, channel_cfg=None):
        self.model = "fake-model"

    def generate_and_save(self, topic):
        return FakeContent()


class FakeConfig:
    channel_id = "test_channel"
    scripts_dir = "output/scripts"
    output_dir = "output"
    videos_dir = "output/videos"
    prompt_version = None
    channel_dna_version = None
    thumbnail_strategy = None
    tts_strategy = None

    def ensure_directories(self):
        return None


def test_pipeline_does_not_invoke_adapter_when_feature_flag_off(monkeypatch, caplog):
    monkeypatch.delenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", raising=False)
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)

    calls = {"builder": 0}

    def _fake_builder(enabled: bool = False):
        calls["builder"] += 1
        return SimpleNamespace(run=lambda: None)

    monkeypatch.setattr(adapter_module, "build_fact_bundle_pipeline_adapter", _fake_builder)

    with caplog.at_level("INFO"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    assert calls["builder"] == 0
    assert "fact_bundle_pipeline_adapter" not in result
    assert "Fact Bundle pipeline adapter skipped: feature flag disabled" in caplog.text


def test_pipeline_invokes_adapter_when_feature_flag_on(monkeypatch, caplog):
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "true")
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)

    calls = {"builder": 0, "run": 0}

    def _fake_builder(enabled: bool = False):
        calls["builder"] += 1
        assert enabled is True

        class _FakeAdapter:
            def run(self):
                calls["run"] += 1
                return SimpleNamespace(
                    enabled=True,
                    applied=True,
                    reason="enabled",
                    orchestration_result=SimpleNamespace(
                        provider_count=2,
                        provider_names=("ProviderA", "ProviderB"),
                    ),
                )

        return _FakeAdapter()

    monkeypatch.setattr(adapter_module, "build_fact_bundle_pipeline_adapter", _fake_builder)

    with caplog.at_level("INFO"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    assert calls == {"builder": 1, "run": 1}
    assert result["fact_bundle_pipeline_adapter"] == {
        "enabled": True,
        "applied": True,
        "reason": "enabled",
        "provider_count": 2,
        "provider_names": ["ProviderA", "ProviderB"],
    }
    assert "Fact Bundle pipeline adapter invoked: feature flag enabled" in caplog.text
    assert "Fact Bundle pipeline adapter success: applied=True provider_count=2" in caplog.text


def test_pipeline_logs_adapter_failure_summary_without_payload_leak(monkeypatch, caplog):
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "true")
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)

    class _FailingAdapter:
        def run(self):
            raise RuntimeError("sensitive-provider-payload")

    def _fake_builder(enabled: bool = False):
        assert enabled is True
        return _FailingAdapter()

    monkeypatch.setattr(adapter_module, "build_fact_bundle_pipeline_adapter", _fake_builder)

    with caplog.at_level("INFO"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    assert "fact_bundle_pipeline_adapter" not in result
    assert "Fact Bundle pipeline adapter failed: error_type=RuntimeError" in caplog.text
    assert "sensitive-provider-payload" not in caplog.text
