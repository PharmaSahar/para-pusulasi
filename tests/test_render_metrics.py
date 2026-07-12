import importlib
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _install_fake_dotenv(monkeypatch):
    fake_module = ModuleType("dotenv")
    fake_module.load_dotenv = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_module)


def _import_pipeline_with_stubs(monkeypatch, tmp_path: Path):
    _install_fake_dotenv(monkeypatch)

    dashboard_md_path = tmp_path / "production_dashboard_latest.md"
    dashboard_json_path = tmp_path / "production_dashboard_latest.json"

    # Force dashboard artifacts to an isolated tmp path before importing modules.
    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(dashboard_md_path))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(dashboard_json_path))

    fake_config = ModuleType("src.config")

    class DummyConfig:
        channel_id = "default"
        video_width = 1920
        video_height = 1080

        def ensure_directories(self):
            return None

    fake_config.config = DummyConfig()
    monkeypatch.setitem(sys.modules, "src.config", fake_config)

    fake_content_generator = ModuleType("src.content_generator")

    class DummyGenerator:
        def __init__(self, channel_cfg=None):
            self.model = "fake-model"

        def generate_and_save(self, topic):
            raise NotImplementedError()

    class DummyVideoContent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def seo_description(self):
            return getattr(self, "description", "")

    fake_content_generator.ContentGenerator = DummyGenerator
    fake_content_generator.VideoContent = DummyVideoContent
    fake_content_generator.TopicDomainBlockedError = type("TopicDomainBlockedError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "src.content_generator", fake_content_generator)

    for module_name, class_name in [
        ("src.image_fetcher", "ImageFetcher"),
        ("src.tts_engine", "TTSEngine"),
        ("src.video_creator_pro", "VideoCreator"),
        ("src.youtube_uploader", "YouTubeUploader"),
    ]:
        fake_module = ModuleType(module_name)
        setattr(fake_module, class_name, type(class_name, (), {}))
        monkeypatch.setitem(sys.modules, module_name, fake_module)

    sys.modules.pop("src.production_quality_platform", None)
    sys.modules.pop("src.pipeline", None)
    pipeline = importlib.import_module("src.pipeline")

    # Reinforce isolation even if function globals were bound from a prior import chain.
    prod_globals = pipeline.update_production_dashboard.__globals__
    monkeypatch.setitem(prod_globals, "PRODUCTION_DASHBOARD_MD_PATH", dashboard_md_path)
    monkeypatch.setitem(prod_globals, "PRODUCTION_DASHBOARD_JSON_PATH", dashboard_json_path)
    return pipeline


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_render_metrics_has_expected_shape_and_non_negative_duration():
    from src.render_metrics import build_render_metrics

    started = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 7, 8, 10, 2, 3, 456000, tzinfo=timezone.utc)

    metrics = build_render_metrics(
        render_started_at=started,
        render_finished_at=finished,
        render_status="completed",
        output_resolution="1920x1080",
        output_fps=24,
    )

    assert metrics["render_metrics_version"] == "v1"
    assert metrics["render_started_at"] == started.isoformat()
    assert metrics["render_finished_at"] == finished.isoformat()
    assert metrics["render_duration_seconds"] == 123.456
    assert metrics["render_duration_seconds"] >= 0
    assert metrics["render_status"] == "completed"
    assert metrics["output_resolution"] == "1920x1080"
    assert metrics["output_fps"] == 24


def test_build_render_metrics_clamps_negative_duration_to_zero():
    from src.render_metrics import build_render_metrics

    metrics = build_render_metrics(
        render_started_at="2026-07-08T10:02:00+00:00",
        render_finished_at="2026-07-08T10:01:00+00:00",
    )

    assert metrics["render_duration_seconds"] == 0.0


def test_pipeline_attaches_render_metrics_on_success(monkeypatch, tmp_path):
    pipeline = _import_pipeline_with_stubs(monkeypatch, tmp_path)
    tracked_dashboard = Path(__file__).resolve().parents[1] / "docs" / "production_dashboard_latest.md"
    baseline_dashboard = _sha256(tracked_dashboard)

    class FakeContent:
        title = "Title"
        description = "desc"
        tags = ["a"]
        script = "script"
        thumbnail_prompt = "thumb"
        category_id = "27"
        niche = "test"
        hook = "hook"
        next_video_teaser = "teaser"
        pexels_search = "test query"
        chart_data = {}
        created_at = "2026-07-08T00:00:00"
        prompt_metadata = {}
        channel_dna_metadata = {}
        quality_score_metadata = {}

        def seo_description(self):
            return "seo"

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"
        video_width = 1920
        video_height = 1080

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            self.model = "fake-model"

        def generate_and_save(self, topic):
            return FakeContent()

    class FakeTTS:
        def __init__(self, channel_cfg=None):
            pass

        def generate_audio(self, script):
            return "/tmp/fake-audio.mp3"

    class FakeFetcher:
        def __init__(self, channel_cfg=None):
            pass

        def fetch_video_clips(self, title, count=4, output_dir="", query_override=None):
            return ["/tmp/clip.mp4"]

        def fetch_thumbnail_photo(self, title):
            return "/tmp/thumb.jpg"

    class FakeCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_video(self, audio_path, title, image_paths=None, script=None):
            return "/tmp/video.mp4"

        def create_thumbnail(self, title, image_path=None):
            return "/tmp/thumb-out.jpg"

    class FakeUploader:
        def __init__(self, channel_cfg=None):
            self.calls = 0

        def upload_video(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "video-id"
            return "short-id"

    fake_shorts = ModuleType("src.shorts_creator")

    class FakeShortsCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_short(self, script, title, hook, image_paths=None):
            return "/tmp/fake-short.mp4"

    fake_shorts.ShortsCreator = FakeShortsCreator
    monkeypatch.setitem(sys.modules, "src.shorts_creator", fake_shorts)
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", FakeUploader)
    monkeypatch.setattr(pipeline, "persist_ownership_manifest", lambda **_kwargs: "/tmp/fake_ownership_manifest.json")
    monkeypatch.setattr(
        pipeline,
        "evaluate_upload_precheck",
        lambda **_kwargs: {
            "status": "allow",
            "quarantine_reason": "",
            "guard_reason_codes": [],
            "recoverable": True,
            "details": {"gate_enabled": False},
        },
    )

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=FakeConfig())

    metrics = result["render_metrics"]
    assert metrics["render_metrics_version"] == "v1"
    assert metrics["render_status"] == "completed"
    assert metrics["output_resolution"] == "1920x1080"
    assert metrics["output_fps"] == 24
    assert metrics["render_duration_seconds"] >= 0
    assert _sha256(tracked_dashboard) == baseline_dashboard


def test_pipeline_keeps_fail_open_when_render_metrics_builder_raises(monkeypatch, tmp_path):
    pipeline = _import_pipeline_with_stubs(monkeypatch, tmp_path)
    tracked_dashboard = Path(__file__).resolve().parents[1] / "docs" / "production_dashboard_latest.md"
    baseline_dashboard = _sha256(tracked_dashboard)

    class FakeContent:
        title = "Title"
        description = "desc"
        tags = ["a"]
        script = "script"
        thumbnail_prompt = "thumb"
        category_id = "27"
        niche = "test"
        hook = "hook"
        next_video_teaser = "teaser"
        pexels_search = "test query"
        chart_data = {}
        created_at = "2026-07-08T00:00:00"
        prompt_metadata = {}
        channel_dna_metadata = {}
        quality_score_metadata = {}

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"
        video_width = 1920
        video_height = 1080

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            self.model = "fake-model"

        def generate_and_save(self, topic):
            return FakeContent()

    class FakeTTS:
        def __init__(self, channel_cfg=None):
            pass

        def generate_audio(self, script):
            return "/tmp/fake-audio.mp3"

    class FakeFetcher:
        def __init__(self, channel_cfg=None):
            pass

        def fetch_video_clips(self, title, count=4, output_dir="", query_override=None):
            return ["/tmp/clip.mp4"]

        def fetch_thumbnail_photo(self, title):
            return "/tmp/thumb.jpg"

    class FakeCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_video(self, audio_path, title, image_paths=None, script=None):
            return "/tmp/video.mp4"

        def create_thumbnail(self, title, image_path=None):
            return "/tmp/thumb-out.jpg"

    class FakeUploader:
        def __init__(self, channel_cfg=None):
            self.calls = 0

        def upload_video(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "video-id"
            return "short-id"

    fake_shorts = ModuleType("src.shorts_creator")

    class FakeShortsCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_short(self, script, title, hook, image_paths=None):
            return "/tmp/fake-short.mp4"

    fake_shorts.ShortsCreator = FakeShortsCreator
    monkeypatch.setitem(sys.modules, "src.shorts_creator", fake_shorts)
    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", FakeUploader)
    monkeypatch.setattr(pipeline, "persist_ownership_manifest", lambda **_kwargs: "/tmp/fake_ownership_manifest.json")
    monkeypatch.setattr(
        pipeline,
        "evaluate_upload_precheck",
        lambda **_kwargs: {
            "status": "allow",
            "quarantine_reason": "",
            "guard_reason_codes": [],
            "recoverable": True,
            "details": {"gate_enabled": False},
        },
    )
    monkeypatch.setattr(pipeline, "build_render_metrics", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("metrics down")))

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=FakeConfig())

    assert result["video_id"] == "video-id"
    assert result["render_metrics"] == {}
    assert _sha256(tracked_dashboard) == baseline_dashboard


def test_pipeline_preserves_existing_failure_behavior_when_render_fails(monkeypatch, tmp_path):
    pipeline = _import_pipeline_with_stubs(monkeypatch, tmp_path)

    class FakeContent:
        title = "Title"
        description = "desc"
        tags = ["a"]
        script = "script"
        thumbnail_prompt = "thumb"
        category_id = "27"
        niche = "test"
        hook = "hook"
        next_video_teaser = "teaser"
        pexels_search = "test query"
        chart_data = {}
        created_at = "2026-07-08T00:00:00"
        prompt_metadata = {}
        channel_dna_metadata = {}
        quality_score_metadata = {}

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            self.model = "fake-model"

        def generate_and_save(self, topic):
            return FakeContent()

    class FakeTTS:
        def __init__(self, channel_cfg=None):
            pass

        def generate_audio(self, script):
            return "/tmp/fake-audio.mp3"

    class FakeFetcher:
        def __init__(self, channel_cfg=None):
            pass

        def fetch_video_clips(self, title, count=4, output_dir="", query_override=None):
            return ["/tmp/clip.mp4"]

        def fetch_thumbnail_photo(self, title):
            return "/tmp/thumb.jpg"

    class BrokenCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_video(self, audio_path, title, image_paths=None, script=None):
            raise RuntimeError("render boom")

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", BrokenCreator)

    failed = False
    try:
        pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=FakeConfig())
    except RuntimeError:
        failed = True

    assert failed is True