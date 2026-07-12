import importlib
import sys
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _install_fake_dotenv(monkeypatch):
    fake_module = ModuleType("dotenv")
    fake_module.load_dotenv = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", fake_module)


def _import_pipeline_with_stubs(monkeypatch):
    _install_fake_dotenv(monkeypatch)

    fake_config = ModuleType("src.config")

    class DummyConfig:
        channel_id = "default"

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

    sys.modules.pop("src.pipeline", None)
    return importlib.import_module("src.pipeline")


def test_build_editor_review_metadata_is_deterministic():
    from src.editor_review import build_editor_review_metadata

    payload = dict(
        title="2026'da 80.000 TL ile ne yapilir?",
        description="Detayli analiz, anahtar kelimeler ve somut strateji ozeti.",
        script="Giris\nNeden\nAdim 1\nAdim 2\nSonuc\n50.000 TL ornek\n%12 oran",
        tags=["yatirim", "2026", "strateji"],
    )

    assert build_editor_review_metadata(**payload) == build_editor_review_metadata(**payload)


def test_build_editor_review_metadata_has_expected_shape_and_ranges():
    from src.editor_review import build_editor_review_metadata

    metadata = build_editor_review_metadata(
        title="2026'da 80.000 TL ile ne yapilir?",
        description="Detayli analiz, anahtar kelimeler ve somut strateji ozeti.",
        script="Giris\nNeden\nAdim 1\nAdim 2\nSonuc\n50.000 TL ornek\n%12 oran",
        tags=["yatirim", "2026", "strateji"],
    )

    assert metadata["review_mode"] == "shadow"
    assert metadata["review_version"] == "v1"
    assert isinstance(metadata["overall_review_score"], int)
    assert 0 <= metadata["overall_review_score"] <= 100

    for key in [
        "hook_review",
        "structure_review",
        "seo_review",
        "originality_review",
        "information_density_review",
    ]:
        assert key in metadata
        assert isinstance(metadata[key]["score"], int)
        assert 0 <= metadata[key]["score"] <= 100
        assert isinstance(metadata[key]["findings"], list)


def test_build_editor_review_metadata_changes_for_weak_vs_strong_inputs():
    from src.editor_review import build_editor_review_metadata

    weak = build_editor_review_metadata(
        title="kisa",
        description="",
        script="Merhaba sevgili izleyiciler\nBu videoda",
        tags=[],
    )
    strong = build_editor_review_metadata(
        title="2026'da 120.000 TL ile en iyi strateji nedir?",
        description="Detayli analiz, temel kavramlar, strateji ve veri odakli ozet.",
        script="Giris\nNeden\nAdim 1\nAdim 2\nSonuc\n100.000 TL ornek\n%18 getiri\nveri ve istatistik",
        tags=["yatirim", "strateji", "2026", "borsa"],
    )

    assert weak != strong
    assert strong["overall_review_score"] > weak["overall_review_score"]


def test_build_editor_review_metadata_does_not_rewrite_or_mutate_inputs():
    from src.editor_review import build_editor_review_metadata

    title = "2026'da 80.000 TL ile ne yapilir?"
    description = "Detayli analiz, anahtar kelimeler ve somut strateji ozeti."
    script = "Giris\nNeden\nAdim 1\nAdim 2\nSonuc"
    tags = ["yatirim", "2026", "strateji"]
    original_tags = list(tags)

    metadata = build_editor_review_metadata(
        title=title,
        description=description,
        script=script,
        tags=tags,
    )

    assert title == "2026'da 80.000 TL ile ne yapilir?"
    assert description == "Detayli analiz, anahtar kelimeler ve somut strateji ozeti."
    assert script == "Giris\nNeden\nAdim 1\nAdim 2\nSonuc"
    assert tags == original_tags
    assert "title" not in metadata
    assert "script" not in metadata
    assert "rewritten_title" not in metadata
    assert "rewritten_script" not in metadata
    assert "prompt_rewrite" not in metadata


def test_pipeline_attaches_editor_review_metadata_in_generate_only(monkeypatch):
    pipeline = _import_pipeline_with_stubs(monkeypatch)

    class FakeContent:
        title = "2026'da 80.000 TL ile ne yapilir?"
        description = "Detayli analiz, anahtar kelimeler ve somut strateji ozeti."
        tags = ["yatirim", "2026", "strateji"]
        script = "Giris\nNeden\nAdim 1\nAdim 2\nSonuc\n80.000 TL ornek"
        thumbnail_prompt = "thumb"
        category_id = "27"
        niche = "test"
        hook = "hook"
        next_video_teaser = "teaser"
        pexels_search = "test query"
        chart_data = {}
        created_at = "2026-07-07T00:00:00"
        prompt_metadata = {"prompt_id": "pr_123", "prompt_version": "prompt-v1"}
        channel_dna_metadata = {"channel_dna_id": "cd_123", "channel_dna_version": "dna-v2"}
        quality_score_metadata = {"overall_quality_score": 88}

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

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    review = result["editor_review_metadata"]
    assert review["review_mode"] == "shadow"
    assert review["review_version"] == "v1"
    assert "hook_review" in review
    assert "structure_review" in review
    assert "seo_review" in review
    assert "originality_review" in review
    assert "information_density_review" in review
    assert result["analytics_join_metadata"]["overall_quality_score"] == 88


def test_pipeline_keeps_full_flow_when_editor_review_succeeds(monkeypatch):
    pipeline = _import_pipeline_with_stubs(monkeypatch)

    class FakeContent:
        title = "2026'da 80.000 TL ile ne yapilir?"
        description = "Detayli analiz, anahtar kelimeler ve somut strateji ozeti."
        tags = ["yatirim", "2026", "strateji"]
        script = "Giris\nNeden\nAdim 1\nAdim 2\nSonuc\n80.000 TL ornek"
        thumbnail_prompt = "thumb"
        category_id = "27"
        niche = "test"
        hook = "hook"
        next_video_teaser = "teaser"
        pexels_search = "test query"
        chart_data = {}
        created_at = "2026-07-07T00:00:00"
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

    assert result["video_id"] == "video-id"
    assert result["youtube_url"].endswith("video-id")
    assert result["short_url"].endswith("short-id")
    assert result["editor_review_metadata"]["review_mode"] == "shadow"


def test_pipeline_keeps_fail_open_when_editor_review_builder_raises(monkeypatch):
    pipeline = _import_pipeline_with_stubs(monkeypatch)

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

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)
    monkeypatch.setattr(pipeline, "build_editor_review_metadata", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("review down")))

    result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    assert result["content_id"].startswith("content_")
    assert result["run_id"].startswith("run_")
    assert result["editor_review_metadata"] == {}