import sys
import importlib
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
        pass

    fake_content_generator.ContentGenerator = DummyGenerator
    fake_content_generator.VideoContent = DummyVideoContent
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


def test_build_analytics_join_metadata_is_deterministic():
    from src.analytics_join import build_analytics_join_metadata

    payload = dict(
        content_id="content_1",
        run_id="run_1",
        channel_id="test-channel",
        telemetry_metadata={
            "experiment_id": "exp-1",
            "experiment_group": "A",
            "model_version": "model-x",
            "thumbnail_strategy": "thumb-a",
            "tts_strategy": "tts-edge",
            "prompt_version": "prompt-fallback",
            "channel_dna_version": "dna-fallback",
        },
        prompt_metadata={"prompt_id": "pr_123", "prompt_version": "prompt-v1"},
        channel_dna_metadata={"channel_dna_id": "cd_123", "channel_dna_version": "dna-v2"},
        quality_score_metadata={"overall_quality_score": 84},
    )

    m1 = build_analytics_join_metadata(**payload)
    m2 = build_analytics_join_metadata(**payload)

    assert m1 == m2


def test_build_analytics_join_metadata_uses_existing_canonical_values():
    from src.analytics_join import build_analytics_join_metadata

    metadata = build_analytics_join_metadata(
        content_id="content_1",
        run_id="run_1",
        channel_id="test-channel",
        telemetry_metadata={
            "experiment_id": "exp-1",
            "experiment_group": "B",
            "model_version": "model-x",
            "thumbnail_strategy": "thumb-a",
            "tts_strategy": "tts-edge",
            "prompt_version": "prompt-fallback",
            "channel_dna_version": "dna-fallback",
        },
        prompt_metadata={"prompt_id": "pr_123", "prompt_version": "prompt-v1"},
        channel_dna_metadata={"channel_dna_id": "cd_123", "channel_dna_version": "dna-v2"},
        quality_score_metadata={"overall_quality_score": 91, "hook_score": 77, "thumbnail_attention_score": 66, "retention_signal_score": 72},
    )

    assert metadata["join_schema_version"] == "v1"
    assert metadata["content_id"] == "content_1"
    assert metadata["run_id"] == "run_1"
    assert metadata["channel_id"] == "test-channel"
    assert metadata["experiment_id"] == "exp-1"
    assert metadata["experiment_group"] == "B"
    assert metadata["model_version"] == "model-x"
    assert metadata["thumbnail_strategy"] == "thumb-a"
    assert metadata["tts_strategy"] == "tts-edge"
    assert metadata["prompt_id"] == "pr_123"
    assert metadata["prompt_version"] == "prompt-v1"
    assert metadata["channel_dna_id"] == "cd_123"
    assert metadata["channel_dna_version"] == "dna-v2"
    assert metadata["thumbnail_attention_score"] == 66
    assert metadata["retention_signal_score"] == 72
    assert metadata["overall_quality_score"] == 91


def test_build_analytics_join_metadata_handles_partial_inputs():
    from src.analytics_join import build_analytics_join_metadata

    metadata = build_analytics_join_metadata(
        content_id="content_1",
        run_id="run_1",
        telemetry_metadata={},
        prompt_metadata={},
        channel_dna_metadata={},
        quality_score_metadata={},
    )

    assert metadata["content_id"] == "content_1"
    assert metadata["run_id"] == "run_1"
    assert metadata["channel_id"] is None
    assert metadata["prompt_id"] is None
    assert metadata["prompt_version"] is None
    assert metadata["channel_dna_id"] is None
    assert metadata["channel_dna_version"] is None
    assert metadata["thumbnail_attention_score"] is None
    assert metadata["retention_signal_score"] is None
    assert metadata["overall_quality_score"] is None


def test_pipeline_attaches_derived_analytics_join_metadata(monkeypatch):
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
        prompt_metadata = {"prompt_id": "pr_123", "prompt_version": "prompt-v1"}
        channel_dna_metadata = {"channel_dna_id": "cd_123", "channel_dna_version": "dna-v2"}
        quality_score_metadata = {"overall_quality_score": 88}

    class FakeConfig:
        channel_id = "test-channel"
        output_dir = "/tmp"
        scripts_dir = "/tmp"
        videos_dir = "/tmp"
        prompt_version = "prompt-fallback"
        channel_dna_version = "dna-fallback"
        thumbnail_strategy = "thumb-a"
        tts_strategy = "tts-edge"

        def ensure_directories(self):
            return None

    class FakeGenerator:
        def __init__(self, channel_cfg=None):
            self.model = "fake-model"

        def generate_and_save(self, topic):
            return FakeContent()

    monkeypatch.setattr(pipeline, "ContentGenerator", FakeGenerator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    join = result["analytics_join_metadata"]
    assert join["content_id"] == result["content_id"]
    assert join["run_id"] == result["run_id"]
    assert join["channel_id"] == "test-channel"
    assert join["prompt_id"] == "pr_123"
    assert join["prompt_version"] == "prompt-v1"
    assert join["channel_dna_id"] == "cd_123"
    assert join["channel_dna_version"] == "dna-v2"
    assert join["model_version"] == "fake-model"
    assert join["overall_quality_score"] == 88


def test_pipeline_keeps_fail_open_when_join_builder_raises(monkeypatch):
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
    monkeypatch.setattr(pipeline, "build_analytics_join_metadata", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("join down")))

    result = pipeline.run_full_pipeline(topic="x", generate_only=True, channel_cfg=FakeConfig())

    assert result["content_id"].startswith("content_")
    assert result["run_id"].startswith("run_")
    assert result["analytics_join_metadata"] == {}