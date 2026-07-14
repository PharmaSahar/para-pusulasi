from __future__ import annotations

import json
from pathlib import Path

import src.pipeline as pipeline


class _FakeContent:
    title = "Thumbnail lineage test"
    created_at = "2026-07-14T10:00:00"
    script = "Deterministic thumbnail lineage script." * 10
    description = "desc"
    tags = ["thumbnail"]
    category_id = "27"
    niche = "kisisel_finans"
    thumbnail_prompt = "bold chart"
    hook = "hook"
    next_video_teaser = "teaser"
    pexels_search = "finance"
    chart_data = None
    prompt_metadata = {"prompt_hash": "ph_test", "safe_prompt": {"prompt_hash": "ph_test"}}
    channel_dna_metadata = {}
    quality_score_metadata = {}

    def seo_description(self) -> str:
        return self.description


class _FakeGenerator:
    def __init__(self, channel_cfg=None, provenance_context=None):
        self.model = "fake-model"

    def generate_and_save(self, topic=None, additional_guidance=None):
        return _FakeContent()


class _FakeTTS:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def generate_audio(self, script: str) -> str:
        p = Path(self.channel_cfg.audio_dir) / "fake.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"00")
        return str(p)


class _FakeFetcher:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def fetch_video_clips(self, *args, **kwargs):
        return []

    def fetch_thumbnail_photo(self, *args, **kwargs):
        return None


class _FakeCreator:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg
        self.last_audio_mix_metadata = {}

    def create_video(self, audio_path, title, image_paths=None, script=""):
        p = Path(self.channel_cfg.videos_dir) / "video.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"video")
        return str(p)

    def create_thumbnail(self, title, image_path=None):
        p = Path(self.channel_cfg.videos_dir) / f"{title[:8]}_thumb.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"thumb")
        return str(p)


class _FakeUploader:
    def __init__(self, channel_cfg=None):
        self.calls = 0

    def upload_video(self, video_path, content, thumbnail_path=None, privacy="public", publish_at=None):
        self.calls += 1
        return f"video-{self.calls}"

    def get_channel_stats(self):
        return {"subscribers": 1}


class _FakeShortsCreator:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def create_short(self, script, title, hook="", image_paths=None):
        p = Path(self.channel_cfg.videos_dir) / "short.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"short")
        return str(p)


class _FakeConfig:
    channel_id = "test_channel"
    prompt_version = None
    channel_dna_version = None
    thumbnail_strategy = None
    tts_strategy = None
    pexels_query = "finance"
    video_width = 1920
    video_height = 1080
    niche = "kisisel_finans"

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


def _setup(monkeypatch, tmp_path: Path) -> _FakeConfig:
    cfg = _FakeConfig(tmp_path)
    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(
        pipeline,
        "validate_script_factual_freshness",
        lambda *_args, **_kwargs: {
            "fact_check_status": "passed",
            "checked_at": "2026-07-14T10:00:00+00:00",
            "sources": [],
            "volatile_claims_checked": [],
        },
    )
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "append_performance_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "persist_ownership_manifest",
        lambda **_kwargs: str(tmp_path / "ownership_manifest.json"),
    )
    monkeypatch.setattr(
        pipeline,
        "evaluate_upload_precheck",
        lambda **_kwargs: {
            "status": "allow",
            "guard_reason_codes": [],
            "recoverable": True,
            "quarantine_reason": None,
        },
    )

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)
    return cfg


def test_default_off_does_not_write(monkeypatch, tmp_path: Path) -> None:
    cfg = _setup(monkeypatch, tmp_path)
    monkeypatch.delenv("THUMBNAIL_METADATA_LINEAGE_ENABLED", raising=False)
    path = tmp_path / "thumbnail_lineage.jsonl"
    monkeypatch.setenv("THUMBNAIL_METADATA_LINEAGE_PATH", str(path))

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)
    assert result["final_status"] == "success"
    assert not path.exists()


def test_enabled_writes_and_keeps_pipeline_output(monkeypatch, tmp_path: Path) -> None:
    cfg = _setup(monkeypatch, tmp_path)
    path = tmp_path / "thumbnail_lineage.jsonl"
    monkeypatch.setenv("THUMBNAIL_METADATA_LINEAGE_PATH", str(path))

    monkeypatch.setenv("THUMBNAIL_METADATA_LINEAGE_ENABLED", "false")
    baseline = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    monkeypatch.setenv("THUMBNAIL_METADATA_LINEAGE_ENABLED", "true")
    enriched = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    for key in ["video_id", "final_status", "title", "script", "description", "topic"]:
        assert baseline.get(key) == enriched.get(key)

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2
    assert {line["content_type"] for line in lines}.issuperset({"video", "short"})
    assert all(line["advisory_only"] is True for line in lines)
    assert all(line["pipeline_output_changed"] is False for line in lines)


def test_storage_failure_is_fail_open(monkeypatch, tmp_path: Path) -> None:
    cfg = _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("THUMBNAIL_METADATA_LINEAGE_ENABLED", "true")

    import src.thumbnail_metadata_lineage as tml

    original_append = tml.ThumbnailMetadataLineageStore.append

    def _boom(self, row):
        raise RuntimeError("store_down")

    monkeypatch.setattr(tml.ThumbnailMetadataLineageStore, "append", _boom)
    try:
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)
    finally:
        monkeypatch.setattr(tml.ThumbnailMetadataLineageStore, "append", original_append)

    assert result["final_status"] == "success"
    assert result["video_id"] == "video-1"