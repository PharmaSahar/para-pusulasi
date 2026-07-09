from __future__ import annotations

import json
import re
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

    def __init__(self, root: Path, experiment_id: str | None = None):
        self.output_dir = str(root / "output")
        self.scripts_dir = str(root / "output" / "scripts")
        self.audio_dir = str(root / "output" / "audio")
        self.videos_dir = str(root / "output" / "videos")
        self.experiment_id = experiment_id

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


def _setup_pipeline_mocks(monkeypatch, append_calls: dict | None = None):
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
            "channel_id": kwargs.get("channel_id"),
            "content_id": kwargs.get("content_id"),
            "run_id": kwargs.get("run_id"),
            "title": kwargs.get("title"),
        },
    )

    if append_calls is not None:
        def _append(snapshot):
            append_calls["snapshots"].append(dict(snapshot))

        monkeypatch.setattr(pipeline, "append_performance_snapshot", _append)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)


def test_pipeline_uses_existing_experiment_id_and_propagates_to_result_and_snapshot(monkeypatch, tmp_path):
    append_calls = {"snapshots": []}
    _setup_pipeline_mocks(monkeypatch, append_calls=append_calls)

    registry_path = tmp_path / "experiments.jsonl"
    monkeypatch.setenv("EXPERIMENT_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("EXPERIMENT_ID", "exp-from-env-001")

    cfg = _FakeConfig(tmp_path)
    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["experiment_id"] == "exp-from-env-001"
    assert result.get("thumbnail_experiments", {}).get("experiment_id") == "exp-from-env-001"
    assert result.get("render_metrics", {}).get("experiment_id") == "exp-from-env-001"
    assert result.get("upload_metadata", {}).get("experiment_id") == "exp-from-env-001"
    assert result.get("performance_snapshot", {}).get("experiment_id") == "exp-from-env-001"
    assert append_calls["snapshots"][0].get("experiment_id") == "exp-from-env-001"

    lines = registry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    event = json.loads(lines[0])
    assert event["event_type"] == "pipeline_run"
    assert event["experiment_id"] == "exp-from-env-001"
    assert event["created_by"] == "pipeline"
    assert event["payload"].get("run_id") == result["run_id"]
    assert event["payload"].get("channel_id") == "test_channel"
    assert event["payload"].get("title") == result.get("title")


def test_pipeline_generates_experiment_id_when_missing_and_snapshot_matches(monkeypatch, tmp_path):
    append_calls = {"snapshots": []}
    _setup_pipeline_mocks(monkeypatch, append_calls=append_calls)

    registry_path = tmp_path / "experiments.jsonl"
    monkeypatch.setenv("EXPERIMENT_REGISTRY_PATH", str(registry_path))
    monkeypatch.delenv("EXPERIMENT_ID", raising=False)

    cfg = _FakeConfig(tmp_path, experiment_id=None)
    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    generated = result.get("experiment_id")
    assert isinstance(generated, str)
    assert re.fullmatch(r"[0-9a-f]{32}", generated) is not None
    assert result.get("performance_snapshot", {}).get("experiment_id") == generated
    assert append_calls["snapshots"][0].get("experiment_id") == generated

    lines = registry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    event = json.loads(lines[0])
    assert event.get("schema_version")
    assert event.get("experiment_id") == generated


def test_pipeline_prefers_param_experiment_id_over_config_and_env(monkeypatch, tmp_path):
    _setup_pipeline_mocks(monkeypatch, append_calls={"snapshots": []})

    monkeypatch.setenv("EXPERIMENT_REGISTRY_PATH", str(tmp_path / "experiments.jsonl"))
    monkeypatch.setenv("EXPERIMENT_ID", "env-id")
    cfg = _FakeConfig(tmp_path, experiment_id="cfg-id")

    result = pipeline.run_full_pipeline(
        topic="x",
        generate_only=False,
        channel_cfg=cfg,
        experiment_id="param-id",
    )

    assert result["experiment_id"] == "param-id"
    assert result.get("performance_snapshot", {}).get("experiment_id") == "param-id"
