import types
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _install_fake_shorts_module(monkeypatch):
    import sys

    fake_module = types.ModuleType("src.shorts_creator")

    class FakeShortsCreator:
        def __init__(self, channel_cfg=None):
            pass

        def create_short(self, script, title, hook, image_paths=None):
            return "/tmp/fake-short.mp4"

    fake_module.ShortsCreator = FakeShortsCreator
    monkeypatch.setitem(sys.modules, "src.shorts_creator", fake_module)


def test_event_envelope_schema_required_and_optional_fields():
    from src.telemetry import build_event_envelope

    event = build_event_envelope(
        content_id="content_1",
        run_id="run_1",
        stage="content_generation",
        event_type="stage_started",
        channel_id="test-channel",
        payload={"k": "v"},
    )

    required = {
        "event_id",
        "content_id",
        "run_id",
        "stage",
        "event_type",
        "occurred_at_utc",
        "channel_id",
        "payload",
    }
    assert required.issubset(set(event.keys()))
    assert "experiment_id" in event
    assert "asset_id" in event
    assert event["experiment_id"] is None
    assert event["asset_id"] is None


def test_pipeline_emits_stage_events_and_ids(monkeypatch):
    from src import pipeline

    _install_fake_shorts_module(monkeypatch)

    events = []

    def capture_emit(event, *, logger=None, sink=None):
        events.append(event)

    monkeypatch.setattr(pipeline, "emit_event", capture_emit)

    class FakeContent:
        title = "Test Title"
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
        created_at = "2026-07-07T00:00:00"

        def seo_description(self):
            return "seo"

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            pass

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

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", FakeUploader)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=FakeConfig())

    assert result["content_id"].startswith("content_")
    assert result["run_id"].startswith("run_")

    event_types = {(e["stage"], e["event_type"]) for e in events}
    assert ("content_generation", "stage_started") in event_types
    assert ("content_generation", "stage_completed") in event_types
    assert ("tts", "stage_started") in event_types
    assert ("tts", "stage_completed") in event_types
    assert ("upload", "stage_started") in event_types
    assert ("upload", "stage_completed") in event_types


def test_pipeline_stage_failed_event_emitted(monkeypatch):
    from src import pipeline

    events = []

    def capture_emit(event, *, logger=None, sink=None):
        events.append(event)

    monkeypatch.setattr(pipeline, "emit_event", capture_emit)

    class FakeContent:
        title = "Test Title"
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
        created_at = "2026-07-07T00:00:00"

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            pass

        def generate_and_save(self, topic):
            return FakeContent()

    class BrokenTTS:
        def __init__(self, channel_cfg=None):
            pass

        def generate_audio(self, script):
            raise RuntimeError("tts boom")

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", BrokenTTS)

    failed = False
    try:
        pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=FakeConfig())
    except RuntimeError:
        failed = True

    assert failed is True
    event_types = {(e["stage"], e["event_type"]) for e in events}
    assert ("tts", "stage_failed") in event_types


def test_pipeline_telemetry_fail_open(monkeypatch):
    from src import pipeline

    def broken_emit(*args, **kwargs):
        raise RuntimeError("telemetry down")

    monkeypatch.setattr(pipeline, "emit_event", broken_emit)

    class FakeContent:
        title = "Test Title"
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
        created_at = "2026-07-07T00:00:00"

        def seo_description(self):
            return "seo"

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            pass

        def generate_and_save(self, topic):
            return FakeContent()

    class FakeTTS:
        def __init__(self, channel_cfg=None):
            pass

        def generate_audio(self, script):
            return "/tmp/fake-audio.mp3"

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", FakeTTS)

    result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    assert result["content_id"].startswith("content_")
    assert result["run_id"].startswith("run_")
