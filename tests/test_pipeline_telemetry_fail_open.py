from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import src.pipeline as pipeline


@dataclass
class _FakeContent:
    title: str = "Test Baslik"
    created_at: str = "2026-07-09T10:00:00"
    script: str = "Test script"
    description: str = "Test description"
    tags: list[str] | None = None
    category_id: str = "27"
    niche: str = "finance"
    thumbnail_prompt: str = "test thumb"
    hook: str = "hook"
    pexels_search: str = "finance"
    chart_data: dict | None = None
    prompt_metadata: dict | None = None
    channel_dna_metadata: dict | None = None
    quality_score_metadata: dict | None = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = ["test"]

    def seo_description(self) -> str:
        return self.description


class _FakeGenerator:
    def __init__(self, channel_cfg=None):
        self.model = "fake-model"

    def generate_and_save(self, topic=None, additional_guidance=None):
        return _FakeContent()


class _FakeTTS:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def generate_audio(self, script: str) -> str:
        audio_path = Path(self.channel_cfg.audio_dir) / "fake.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"00")
        return str(audio_path)


class _FakeFetcher:
    def __init__(self, channel_cfg=None):
        pass

    def fetch_video_clips(self, *args, **kwargs):
        return []

    def fetch_thumbnail_photo(self, *args, **kwargs):
        return None


class _FakeCreator:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg
        self.last_audio_mix_metadata = {}

    def create_video(self, audio_path, title, image_paths=None, script=""):
        video_path = Path(self.channel_cfg.videos_dir) / "fake_video.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"video")
        return str(video_path)

    def create_thumbnail(self, title, image_path=None):
        thumb_path = Path(self.channel_cfg.videos_dir) / "fake_thumb.jpg"
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.write_bytes(b"thumb")
        return str(thumb_path)


class _FakeUploader:
    def __init__(self, channel_cfg=None):
        self.calls = 0

    def upload_video(self, video_path, content, thumbnail_path=None, privacy="public", publish_at=None):
        self.calls += 1
        return f"video-{self.calls}"

    def get_channel_stats(self):
        return {"subscribers": 0}


class _FakeShortsCreator:
    def __init__(self, channel_cfg=None):
        pass

    def create_short(self, script, title, hook="", image_paths=None):
        raise RuntimeError("short disabled in unit test")


class _FakeConfig:
    channel_id = "test_channel"
    prompt_version = None
    channel_dna_version = None
    thumbnail_strategy = None
    tts_strategy = None
    pexels_query = "finance"
    video_width = 1920
    video_height = 1080

    def __init__(self, root: Path):
        self.output_dir = str(root / "output")
        self.scripts_dir = str(root / "output" / "scripts")
        self.audio_dir = str(root / "output" / "audio")
        self.videos_dir = str(root / "output" / "videos")

    def ensure_directories(self):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.scripts_dir).mkdir(parents=True, exist_ok=True)
        Path(self.audio_dir).mkdir(parents=True, exist_ok=True)
        Path(self.videos_dir).mkdir(parents=True, exist_ok=True)


def _fact_check_ok(*args, **kwargs):
    return {
        "fact_check_status": "passed",
        "checked_at": "2026-07-09T10:00:00+00:00",
        "sources": [],
        "volatile_claims_checked": [],
    }


def test_pipeline_telemetry_emit_fail_open_sets_visible_warning(monkeypatch, tmp_path, caplog):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("telemetry down")))

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=cfg)

    assert "telemetry_warning" in result
    assert result["telemetry_warning"]["code"] == "telemetry_emit_failed"
    assert result["telemetry_warning"]["count"] >= 1
    assert "Telemetry emit fail-open" in caplog.text


def test_pipeline_snapshot_append_fail_open_sets_metrics_warning(monkeypatch, tmp_path, caplog):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "build_performance_snapshot",
        lambda **kwargs: {
            "performance_schema_version": "v1",
            "day": "2026-07-09",
            "created_at": "2026-07-09T10:00:00+00:00",
            "channel_id": "test_channel",
            "content_id": "content_1",
            "run_id": "run_1",
            "title": "title",
        },
    )
    monkeypatch.setattr(
        pipeline,
        "append_performance_snapshot",
        lambda snapshot: (_ for _ in ()).throw(RuntimeError("snapshot sink down")),
    )

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result.get("performance_snapshot", {}).get("content_id") == "content_1"
    assert "metrics_warning" in result
    assert result["metrics_warning"]["code"] == "performance_snapshot_append_failed"
    assert "Metrics fail-open" in caplog.text


def test_pipeline_snapshot_validation_guard_skips_invalid_row(monkeypatch, tmp_path, caplog):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "build_performance_snapshot",
        lambda **kwargs: {
            "performance_schema_version": "v1",
            "day": "2026-07-09",
            "created_at": "2026-07-09T10:00:00+00:00",
            "channel_id": "test_channel",
            "content_id": "",  # invalid required field
            "run_id": "run_1",
            "title": "title",
        },
    )

    append_calls = {"count": 0}

    def _append(_snapshot):
        append_calls["count"] += 1

    monkeypatch.setattr(pipeline, "append_performance_snapshot", _append)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert append_calls["count"] == 0
    assert result.get("performance_snapshot_append_skipped") is True
    assert "analytics_warning" in result
    assert result["analytics_warning"]["code"] == "performance_snapshot_validation_failed"
    assert "Analytics fail-open" in caplog.text


def test_pipeline_thumbnail_validator_fail_open_writes_standard_fields(monkeypatch, tmp_path, caplog):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "validate_thumbnail_metadata_contract",
        lambda _payload: (_ for _ in ()).throw(RuntimeError("validator down")),
    )

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert "thumbnail_metadata" in result
    assert "video" in result["thumbnail_metadata"]
    assert "rejection_reasons" in result
    assert isinstance(result["rejection_reasons"], list)
    assert "validation_warning" in result
    assert result["validation_warning"]["code"] == "thumbnail_validator_failed"
    assert "Validation fail-open" in caplog.text
