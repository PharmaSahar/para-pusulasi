from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

import src.pipeline as pipeline
import src.youtube_uploader as youtube_uploader
import src.content_quality_guard as content_quality_guard
from src.production_safety_gate import ProductionSafetyCheckResult, ProductionSafetyGateBlocked, ProductionSafetyGateResult


@pytest.fixture(autouse=True)
def _allow_automatic_qa(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "evaluate_automatic_qa",
        lambda _payload: {"decision": "allow", "blocked_checks": []},
    )


@pytest.fixture(autouse=True)
def _allow_content_quality_gate(monkeypatch):
    class _AllowDecision:
        publish_decision = "allow"
        block_reasons: list[str] = []
        scores: dict[str, float] = {}
        script_similarity = 0.0

    monkeypatch.setattr(
        content_quality_guard,
        "evaluate_content_quality",
        lambda *_args, **_kwargs: _AllowDecision(),
    )


def _load_thumbnail_fixture(filename: str) -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / filename
    return json.loads(fixture_path.read_text(encoding="utf-8"))


@dataclass
class _FakeContent:
    title: str = "Test Baslik"
    created_at: str = "2026-07-09T10:00:00"
    script: str = "Test script"
    description: str = (
        "Bu test aciklamasi kalite kapisini gecmek icin yeterli uzunlukta tutulmustur. "
        "Pipeline fail-open davranisi ayrica bu fixture ile dogrulanir."
    )
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
            self.tags = ["test", "pipeline", "quality"]

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


class _ForbiddenTTS:
    def __init__(self, channel_cfg=None):
        pass

    def generate_audio(self, script: str) -> str:
        raise AssertionError("TTS must not run in observation mode")


class _ForbiddenCreator:
    def __init__(self, channel_cfg=None):
        pass

    def create_video(self, *args, **kwargs):
        raise AssertionError("final render must not run in observation mode")

    def create_thumbnail(self, *args, **kwargs):
        raise AssertionError("thumbnail render must not run in observation mode")


class _ForbiddenUploader:
    def __init__(self, channel_cfg=None):
        pass

    def upload_video(self, *args, **kwargs):
        raise AssertionError("upload must not run in observation mode")

    def get_channel_stats(self):
        raise AssertionError("upload side-effect helpers must not run in observation mode")


class _FakeShortsCreator:
    def __init__(self, channel_cfg=None):
        pass

    def create_short(self, script, title, hook="", image_paths=None):
        raise RuntimeError("short disabled in unit test")


class _FakeShortsCreatorOk:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def create_short(self, script, title, hook="", image_paths=None):
        short_path = Path(self.channel_cfg.videos_dir) / "fake_short.mp4"
        short_path.parent.mkdir(parents=True, exist_ok=True)
        short_path.write_bytes(b"short")
        return str(short_path)


class _FakeUploaderMissingId:
    def __init__(self, channel_cfg=None):
        pass

    def upload_video(self, video_path, content, thumbnail_path=None, privacy="public", publish_at=None):
        return ""

    def get_channel_stats(self):
        return {"subscribers": 0}


class _FakeUploaderSafetyBlocked:
    def __init__(self, channel_cfg=None):
        pass

    def upload_video(self, *args, **kwargs):
        raise ProductionSafetyGateBlocked(
            ProductionSafetyGateResult(
                operation="upload",
                channel_id="test_channel",
                job_id="run_1",
                allowed=False,
                status="blocked",
                blocking_reason="active_deployment_lock",
                timestamp="2026-07-18T00:00:00+00:00",
                release_sha="a" * 40,
                checks=(
                    ProductionSafetyCheckResult(
                        check_name="active_deployment_lock",
                        status="fail",
                        severity="critical",
                        reason_code="active_deployment_lock",
                        message="blocked",
                        timestamp="2026-07-18T00:00:00+00:00",
                        release_sha="a" * 40,
                        channel_id="test_channel",
                        job_id="run_1",
                        evidence={},
                    ),
                ),
                evidence={},
            )
        )

    def get_channel_stats(self):
        return {"subscribers": 0}


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


def test_observation_mode_pipeline_generates_manifest_and_precheck_without_side_effects(monkeypatch, tmp_path):
    import src.production_safety_gate as production_safety_gate

    cfg = _FakeConfig(tmp_path)
    cfg.channel_id = "test_channel"
    cfg.niche = "finance"
    cfg.name = "Test Channel"
    cfg.logs_dir = str(tmp_path / "logs")
    cfg.validate = lambda: []
    cfg.ensure_directories()
    script_path = Path(cfg.scripts_dir) / "2026-07-09_Test Baslik.json"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("{}", encoding="utf-8")

    class _ObservationFetcher:
        def __init__(self, channel_cfg=None):
            self.channel_cfg = channel_cfg

        def fetch_video_clips(self, *_args, **kwargs):
            out = Path(kwargs["output_dir"]) / "clip.jpg"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"clip")
            return [str(out)]

        def fetch_thumbnail_photo(self, *_args, **_kwargs):
            return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRODUCTION_OBSERVATION_MODE", "true")
    monkeypatch.setenv("PRODUCTION_SAFETY_GATE_IN_TESTS", "1")
    monkeypatch.setenv("UPLOAD_PRECHECK_ENABLED", "true")
    monkeypatch.setattr(production_safety_gate, "check_token_health", lambda _cfg: (True, "ok"))
    monkeypatch.setattr(production_safety_gate, "get_free_disk_gb", lambda: 9.5)
    monkeypatch.setattr(production_safety_gate, "get_global_overload_pause_status", lambda: {"is_open": False, "retry_after_seconds": 0, "pause_until": "", "reason": ""})
    monkeypatch.setattr(production_safety_gate, "get_provider_circuit_status", lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}})
    monkeypatch.setattr(production_safety_gate, "_resolve_git_head", lambda: "a" * 40)
    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _ForbiddenTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _ObservationFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _ForbiddenCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _ForbiddenUploader)
    monkeypatch.setattr(pipeline, "record_production_event", lambda _payload: (_ for _ in ()).throw(AssertionError("analytics/telemetry write blocked")))

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result["final_status"] == "observation_complete"
    assert result["production_safety_gate"]["blocking_reason"] == "production_observation_mode"
    assert result["upload_safety_gate"]["blocking_reason"] == "production_observation_mode"
    assert result["upload_metadata"]["api_invoked"] is False
    assert result["shorts_upload_metadata"]["api_invoked"] is False
    assert Path(result["visual_manifest_path"]).exists()
    assert result["upload_precheck"]["details"]["production_observation_mode"] is True
    assert not (tmp_path / "output" / "telemetry" / "experiments.jsonl").exists()


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

    expected_contract = _load_thumbnail_fixture("thumbnail_metadata_valid.json")
    produced = result.get("thumbnail_metadata", {}).get("video", {})

    assert "thumbnail_metadata" in result
    assert "video" in result["thumbnail_metadata"]
    assert set(produced.keys()) == set(expected_contract.keys())
    assert isinstance(produced.get("quality"), dict)
    assert set(produced.get("quality", {}).keys()) == set(expected_contract.get("quality", {}).keys())
    assert isinstance(produced.get("diversity"), dict)
    assert set(produced.get("diversity", {}).keys()) == set(expected_contract.get("diversity", {}).keys())
    assert "rejection_reasons" in result
    assert isinstance(result["rejection_reasons"], list)
    assert "validation_warning" in result


def test_pipeline_marks_upload_failed_when_video_id_missing(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploaderMissingId)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result.get("video_id") is None
    assert result.get("final_status") in {"failed", "blocked"}
    if result.get("final_status") == "failed":
        assert "upload_response_missing_id" in str(result.get("upload_error"))
    else:
        assert result.get("upload_precheck", {}).get("status") == "blocked"
        assert "upload_precheck_final_guard" in (result.get("upload_precheck", {}).get("guard_reason_codes") or [])


def test_pipeline_short_upload_is_skipped_when_main_upload_fails(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)
    emitted: list[tuple[str, str, dict]] = []

    def _capture_event(*args, **kwargs):
        envelope = args[0] if args else kwargs.get("event") or {}
        stage = str(envelope.get("stage") or "")
        event_type = str(envelope.get("event_type") or "")
        payload = dict(envelope.get("payload") or {})
        emitted.append((stage, event_type, payload))

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploaderMissingId)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", _capture_event)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreatorOk)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert result.get("video_id") is None
    assert result.get("final_status") in {"failed", "blocked"}
    shorts_events = [row for row in emitted if row[0] == "shorts_upload"]
    assert shorts_events
    assert any(
        event_type == "stage_completed" and payload.get("reason") in {"main_upload_failed", "main_upload_blocked"}
        for _, event_type, payload in shorts_events
    )
    assert not any(event_type == "stage_failed" for _, event_type, _ in shorts_events)


def test_pipeline_thumbnail_experiment_binding_success_writes_variant_metadata(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    from src.thumbnail_experiment import create_thumbnail_variant

    fake_candidates = [
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0001",
            variant_label="A",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/a.jpg",
            prompt="a",
            strategy="default_ab",
        ),
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0002",
            variant_label="B",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/a.jpg",
            prompt="b",
            strategy="default_ab",
        ),
    ]

    monkeypatch.setattr(pipeline, "generate_thumbnail_candidates", lambda **kwargs: fake_candidates)
    monkeypatch.setattr(
        pipeline,
        "register_thumbnail_variant_bindings",
        lambda **kwargs: [{"event_type": "thumbnail_variant_registered", "variant_id": "var_0001"}],
    )

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    assert "thumbnail_variants" in result
    assert len(result["thumbnail_variants"]) == 2
    assert result["thumbnail_variants"][0]["variant_id"] == "var_0001"
    assert "thumbnail_variant_registry_events" in result
    assert result["thumbnail_variant_registry_events"][0]["event_type"] == "thumbnail_variant_registered"


def test_pipeline_thumbnail_experiment_binding_fail_open_continues(monkeypatch, tmp_path, caplog):
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
        "generate_thumbnail_candidates",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("candidate generator down")),
    )

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    if result.get("video_id") is None:
        assert result.get("final_status") == "blocked"
        assert result.get("upload_precheck", {}).get("status") == "blocked"
    else:
        assert result.get("final_status") == "success"
    assert "thumbnail_experiment_warning" in result
    assert result["thumbnail_experiment_warning"]["code"] == "thumbnail_experiment_binding_failed"
    assert "Thumbnail experiment fail-open" in caplog.text


def test_pipeline_thumbnail_experiment_binding_preserves_existing_experiment_id(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    captured = {}

    from src.thumbnail_experiment import create_thumbnail_variant

    def _fake_generate_thumbnail_candidates(**kwargs):
        captured["experiment_id"] = kwargs.get("experiment_id")
        return [
            create_thumbnail_variant(
                experiment_id=str(kwargs.get("experiment_id")),
                variant_id="var_0001",
                variant_label="A",
                channel_id="test_channel",
                content_id="content_1",
                thumbnail_path="/tmp/a.jpg",
                prompt="a",
                strategy="default_ab",
            )
        ]

    monkeypatch.setattr(pipeline, "generate_thumbnail_candidates", _fake_generate_thumbnail_candidates)
    monkeypatch.setattr(pipeline, "register_thumbnail_variant_bindings", lambda **kwargs: [])

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_custom_001")

    assert result["experiment_id"] == "exp_custom_001"
    assert captured.get("experiment_id") == "exp_custom_001"


def test_pipeline_thumbnail_selection_writes_selected_variant_metadata(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    from src.thumbnail_experiment import create_thumbnail_variant

    fake_candidates = [
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0001",
            variant_label="A",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/a.jpg",
            prompt="a",
            strategy="default_ab",
        ),
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0002",
            variant_label="B",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/b.jpg",
            prompt="b",
            strategy="default_ab",
        ),
    ]

    monkeypatch.setattr(pipeline, "generate_thumbnail_candidates", lambda **kwargs: fake_candidates)
    monkeypatch.setattr(pipeline, "register_thumbnail_variant_bindings", lambda **kwargs: [])

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    assert "selected_thumbnail_variant" in result
    assert result["selected_thumbnail_variant"]["variant_id"] == "var_0001"
    assert "thumbnail_selection_policy" in result


def test_pipeline_thumbnail_selection_default_policy_is_first(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    from src.thumbnail_experiment import create_thumbnail_variant

    fake_candidates = [
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0001",
            variant_label="A",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/a.jpg",
            prompt="a",
            strategy="default_ab",
        ),
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0002",
            variant_label="B",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/b.jpg",
            prompt="b",
            strategy="default_ab",
        ),
    ]

    monkeypatch.setattr(pipeline, "generate_thumbnail_candidates", lambda **kwargs: fake_candidates)
    monkeypatch.setattr(pipeline, "register_thumbnail_variant_bindings", lambda **kwargs: [])

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    assert result["thumbnail_selection_policy"] == "first"
    assert result["selected_thumbnail_variant"]["variant_id"] == "var_0001"


def test_pipeline_thumbnail_selection_fail_open_continues(monkeypatch, tmp_path, caplog):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    from src.thumbnail_experiment import create_thumbnail_variant

    fake_candidates = [
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0001",
            variant_label="A",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/a.jpg",
            prompt="a",
            strategy="default_ab",
        )
    ]

    monkeypatch.setattr(pipeline, "generate_thumbnail_candidates", lambda **kwargs: fake_candidates)
    monkeypatch.setattr(pipeline, "register_thumbnail_variant_bindings", lambda **kwargs: [])
    monkeypatch.setattr(
        pipeline,
        "select_thumbnail_candidate",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("selection failed")),
    )

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    if result.get("video_id") is None:
        assert result.get("final_status") == "blocked"
        assert result.get("upload_precheck", {}).get("status") == "blocked"
    else:
        assert result.get("final_status") == "success"
    assert "thumbnail_selection_warning" in result
    assert result["thumbnail_selection_warning"]["code"] == "thumbnail_selection_failed"
    assert "Thumbnail selection fail-open" in caplog.text


def test_pipeline_thumbnail_selection_does_not_change_upload_or_thumbnail_paths(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    from src.thumbnail_experiment import create_thumbnail_variant

    fake_candidates = [
        create_thumbnail_variant(
            experiment_id="exp_keep",
            variant_id="var_0001",
            variant_label="A",
            channel_id="test_channel",
            content_id="content_1",
            thumbnail_path="/tmp/a.jpg",
            prompt="a",
            strategy="default_ab",
        )
    ]

    monkeypatch.setattr(pipeline, "generate_thumbnail_candidates", lambda **kwargs: fake_candidates)
    monkeypatch.setattr(pipeline, "register_thumbnail_variant_bindings", lambda **kwargs: [])

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    expected_video = str(Path(cfg.videos_dir) / "fake_video.mp4")
    expected_thumb = str(Path(cfg.videos_dir) / "fake_thumb.jpg")
    assert result["video_path"] == expected_video
    assert result["thumbnail_path"] == expected_thumb


def test_pipeline_audio_metadata_standardization_writes_fields(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    class _CreatorWithValidAudioMix(_FakeCreator):
        def __init__(self, channel_cfg=None):
            super().__init__(channel_cfg=channel_cfg)
            self.last_audio_mix_metadata = {
                "music_track_id": "track_001",
                "ducking_applied": True,
                "loudness_target": -16.0,
                "mix_applied": True,
            }

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _CreatorWithValidAudioMix)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert "audio_mix_metadata" in result
    assert result["audio_mix_metadata"]["schema_version"] == "1.0"
    assert result["music_track_id"] == "track_001"
    assert result["ducking_applied"] is True
    assert result["loudness_target"] == -16.0
    assert result.get("audio_warning") is None


def test_pipeline_audio_metadata_validation_fail_open_sets_warning(monkeypatch, tmp_path, caplog):
    cfg = _FakeConfig(tmp_path)

    class _CreatorWithInvalidAudioMix(_FakeCreator):
        def __init__(self, channel_cfg=None):
            super().__init__(channel_cfg=channel_cfg)
            self.last_audio_mix_metadata = {
                "music_track_id": "",
                "ducking_applied": "yes",
                "loudness_target": "-16",
            }

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _CreatorWithInvalidAudioMix)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", lambda *args, **kwargs: None)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    with caplog.at_level("WARNING"):
        result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    if result.get("video_id") is None:
        assert result.get("final_status") == "blocked"
        assert result.get("upload_precheck", {}).get("status") == "blocked"
    else:
        assert result.get("final_status") == "success"
    assert "audio_warning" in result
    assert result["audio_warning"]["code"] == "audio_metadata_validation_failed"
    assert "Audio metadata fail-open" in caplog.text


def test_pipeline_telemetry_payload_contains_observability_metadata(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    events = []

    def _capture_emit(event, *, logger=None, sink=None):
        events.append(event)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(pipeline, "emit_event", _capture_emit)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg, experiment_id="exp_keep")

    assert result["experiment_id"] == "exp_keep"
    assert result["live_collector_enabled"] is False
    assert result["analytics_live_status"] == "no_go_api_not_enabled"

    assert events
    payload = events[-1].get("payload", {})
    assert payload.get("experiment_id") == "exp_keep"
    assert "thumbnail_variants" in payload
    assert "selected_thumbnail_variant" in payload
    assert "thumbnail_selection_policy" in payload
    assert "audio_metadata" in payload
    assert "audio_warning" in payload
    assert "analytics_warning" in payload
    assert payload.get("analytics_live_status") == "no_go_api_not_enabled"


def test_pipeline_render_gate_blocks_before_artifacts(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)
    marker = {"generated": 0}

    def _block(**_kwargs):
        raise ProductionSafetyGateBlocked(
            ProductionSafetyGateResult(
                operation="render",
                channel_id="test_channel",
                job_id="run_1",
                allowed=False,
                status="blocked",
                blocking_reason="active_deployment_lock",
                timestamp="2026-07-18T00:00:00+00:00",
                release_sha="a" * 40,
                checks=(),
                evidence={},
            )
        )

    class _NeverGenerator:
        def __init__(self, channel_cfg=None):
            self.model = "fake"

        def generate_and_save(self, topic=None, additional_guidance=None):
            marker["generated"] += 1
            return _FakeContent()

    monkeypatch.setattr(pipeline, "ensure_production_safety_gate", _block)
    monkeypatch.setattr(pipeline, "ContentGenerator", _NeverGenerator)

    with pytest.raises(ProductionSafetyGateBlocked):
        pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    assert marker["generated"] == 0


def test_pipeline_upload_safety_block_emits_one_authoritative_event(monkeypatch, tmp_path):
    cfg = _FakeConfig(tmp_path)

    class _LargeVideoCreator(_FakeCreator):
        def create_video(self, audio_path, title, image_paths=None, script=""):
            video_path = Path(self.channel_cfg.videos_dir) / "fake_video.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"0" * 100_001)
            return str(video_path)

    monkeypatch.setattr(pipeline, "ContentGenerator", _FakeGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _LargeVideoCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", youtube_uploader.YouTubeUploader)
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    stage_events = []
    prod_events = []
    monkeypatch.setattr(pipeline, "emit_event", lambda envelope, logger=None: stage_events.append(envelope))
    monkeypatch.setattr(pipeline, "record_production_event", lambda payload: prod_events.append(payload))
    import src.production_safety_gate as production_safety_gate
    monkeypatch.setattr(production_safety_gate, "record_production_event", lambda payload: prod_events.append(payload))
    monkeypatch.setattr(pipeline, "evaluate_upload_precheck", lambda **_kwargs: {"status": "allow", "guard_reason_codes": [], "details": {}})
    def _raise_upload_gate(**_kwargs):
        prod_events.append(
            {
                "event_type": "production_safety_gate",
                "status": "blocked",
                "reason": "active_deployment_lock",
            }
        )
        raise ProductionSafetyGateBlocked(
            ProductionSafetyGateResult(
                operation="upload",
                channel_id="test_channel",
                job_id="run_1",
                allowed=False,
                status="blocked",
                blocking_reason="active_deployment_lock",
                timestamp="2026-07-18T00:00:00+00:00",
                release_sha="a" * 40,
                checks=(
                    ProductionSafetyCheckResult(
                        check_name="active_deployment_lock",
                        status="fail",
                        severity="critical",
                        reason_code="active_deployment_lock",
                        message="blocked",
                        timestamp="2026-07-18T00:00:00+00:00",
                        release_sha="a" * 40,
                        channel_id="test_channel",
                        job_id="run_1",
                        evidence={},
                    ),
                ),
                evidence={},
            )
        )

    monkeypatch.setattr(youtube_uploader, "ensure_production_safety_gate", _raise_upload_gate)
    monkeypatch.setattr(pipeline, "append_performance_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "update_production_observability_latest", lambda: {})
    monkeypatch.setattr(pipeline, "write_production_evidence", lambda *_args, **_kwargs: Path(tmp_path / "evidence.json"))
    monkeypatch.setattr(pipeline, "update_production_dashboard", lambda **_kwargs: None)

    import src.shorts_creator as shorts_creator_module

    monkeypatch.setattr(shorts_creator_module, "ShortsCreator", _FakeShortsCreator)

    result = pipeline.run_full_pipeline(topic="x", generate_only=False, channel_cfg=cfg)

    blocked_events = [event for event in prod_events if event.get("event_type") == "production_safety_gate"]
    upload_quality_blocks = [event for event in prod_events if event.get("event_type") == "upload_quality_block"]
    upload_stage_failed = [event for event in stage_events if event.get("event_type") == "stage_failed" and event.get("stage") == "upload"]

    assert result["final_status"] == "blocked"
    assert len(blocked_events) == 1
    assert len(upload_quality_blocks) == 0
    assert len(upload_stage_failed) == 0
