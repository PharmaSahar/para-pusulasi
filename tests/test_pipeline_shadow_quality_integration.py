from __future__ import annotations

from pathlib import Path

import src.pipeline as pipeline


class _FakeContent:
    title = "Birikim Yaparken 5 Hata"
    created_at = "2026-07-13T10:00:00"
    script = "Birikim plani, harcama disiplini ve risk yonetimi gerektirir."
    description = "Bu videoda birikim surecinde yapilan temel hatalari adim adim anlatiyoruz."
    tags = ["birikim", "finans", "tasarruf"]
    category_id = "27"
    niche = "kisisel_finans"
    thumbnail_prompt = "Savings mistakes warning icon"
    hook = "Birikim neden artmiyor"
    next_video_teaser = "Bir sonraki videoda acil durum fonu"
    pexels_search = "money saving plan"
    chart_data = None
    prompt_metadata = {}
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
        p = Path(self.channel_cfg.videos_dir) / "thumb.jpg"
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


class _AllowDecision:
    publish_decision = "allow"
    block_reasons: list[str] = []
    scores: dict[str, float] = {}
    script_similarity = 0.0


def _setup_pipeline(monkeypatch, tmp_path: Path) -> _FakeConfig:
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
            "checked_at": "2026-07-13T10:00:00+00:00",
            "sources": [],
            "volatile_claims_checked": [],
        },
    )
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "append_performance_snapshot",
        lambda *_args, **_kwargs: None,
    )
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
    monkeypatch.setattr(
        pipeline,
        "evaluate_content_quality",
        lambda *_args, **_kwargs: _AllowDecision(),
        raising=False,
    )
    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)
    return cfg


def test_pipeline_behavior_unchanged_when_shadow_disabled(monkeypatch, tmp_path: Path):
    cfg = _setup_pipeline(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTENT_QUALITY_SHADOW_MODE_ENABLED", "0")

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["video_id"] == "video-1"
    assert result["final_status"] == "success"
    assert "shadow_quality" not in result


def test_pipeline_behavior_unchanged_when_shadow_enabled(monkeypatch, tmp_path: Path):
    cfg = _setup_pipeline(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTENT_QUALITY_SHADOW_MODE_ENABLED", "true")

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["video_id"] == "video-1"
    assert result["final_status"] == "success"
    assert result["title"] == _FakeContent.title
    assert result["script"] == _FakeContent.script
    assert result.get("shadow_quality", {}).get("enabled") is True


def test_shadow_evaluation_failure_does_not_fail_pipeline(monkeypatch, tmp_path: Path):
    cfg = _setup_pipeline(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTENT_QUALITY_SHADOW_MODE_ENABLED", "true")

    import src.shadow_content_quality as scq

    monkeypatch.setattr(
        scq.ShadowContentQualityEngine,
        "evaluate_and_store",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("shadow down")),
    )

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["video_id"] == "video-1"
    assert result["final_status"] == "success"
    checkpoints = result.get("shadow_quality", {}).get("checkpoints", [])
    assert any(item.get("storage_status") == "failed" for item in checkpoints)


def test_shadow_storage_failure_does_not_fail_pipeline(monkeypatch, tmp_path: Path):
    cfg = _setup_pipeline(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTENT_QUALITY_SHADOW_MODE_ENABLED", "true")

    import src.shadow_content_quality as scq

    monkeypatch.setattr(
        scq,
        "append_shadow_row",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("store failed")),
    )

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["video_id"] == "video-1"
    assert result["final_status"] == "success"


def test_one_context_created_per_transaction(monkeypatch, tmp_path: Path):
    cfg = _setup_pipeline(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTENT_QUALITY_SHADOW_MODE_ENABLED", "true")

    import src.shadow_content_quality as scq

    calls = {"count": 0}
    original_builder = scq.build_shadow_evaluation_context

    def _counted_builder(*args, **kwargs):
        calls["count"] += 1
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(scq, "build_shadow_evaluation_context", _counted_builder)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["final_status"] == "success"
    assert calls["count"] == 1

