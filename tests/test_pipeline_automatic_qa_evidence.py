from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import src.automatic_qa_evidence as automatic_qa_evidence
import src.content_quality_guard as content_quality_guard
import src.pipeline as pipeline
import src.thumbnail_experiments as thumbnail_experiments
import src.visual_diversity as visual_diversity
from src.production_quality_platform import evaluate_automatic_qa as _real_evaluate_automatic_qa


@dataclass
class _FakeContent:
    title: str
    thumbnail_prompt: str
    created_at: str = "2026-07-18T10:00:00"
    script: str = "Borsa stratejisi ve risk yonetimi icin sade egitim metni"
    description: str = "Borsa stratejisi aciklama metni"
    tags: list[str] | None = None
    category_id: str = "27"
    niche: str = "borsa"
    hook: str = "hook"
    pexels_search: str = "borsa chart"
    chart_data: dict | None = None
    prompt_metadata: dict | None = None
    channel_dna_metadata: dict | None = None
    quality_score_metadata: dict | None = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = ["borsa", "strateji", "risk"]

    def seo_description(self) -> str:
        return self.description


class _SequenceGenerator:
    contents: list[_FakeContent] = []
    calls = 0
    events: list[tuple[str, int]] = []

    def __init__(self, channel_cfg=None):
        self.model = "fake-model"

    def generate_and_save(self, topic=None, additional_guidance=None):
        index = min(type(self).calls, len(type(self).contents) - 1)
        type(self).events.append(("generate", type(self).calls))
        type(self).calls += 1
        return type(self).contents[index]


class _FakeConfig:
    channel_id = "borsa_akademi"
    niche = "borsa"
    name = "Borsa Akademi"
    prompt_version = None
    channel_dna_version = None
    thumbnail_strategy = None
    tts_strategy = None
    pexels_query = "borsa chart"
    video_width = 1920
    video_height = 1080

    def __init__(self, root: Path):
        self.output_dir = str(root / "output")
        self.scripts_dir = str(root / "output" / "scripts")
        self.audio_dir = str(root / "output" / "audio")
        self.videos_dir = str(root / "output" / "videos")
        self.logs_dir = str(root / "logs")

    def ensure_directories(self):
        for path in (self.output_dir, self.scripts_dir, self.audio_dir, self.videos_dir, self.logs_dir):
            Path(path).mkdir(parents=True, exist_ok=True)


class _FakeTTS:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def generate_audio(self, script: str) -> str:
        path = Path(self.channel_cfg.audio_dir) / "fake.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
        return str(path)


class _FakeFetcher:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg

    def fetch_video_clips(self, *args, **kwargs):
        path = Path(kwargs["output_dir"]) / "clip.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"clip")
        return [str(path)]

    def fetch_thumbnail_photo(self, *args, **kwargs):
        return None


class _FakeCreator:
    def __init__(self, channel_cfg=None):
        self.channel_cfg = channel_cfg
        self.last_audio_mix_metadata = {}

    def create_video(self, audio_path, title, image_paths=None, script=""):
        path = Path(self.channel_cfg.videos_dir) / "fake.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0" * 100_001)
        return str(path)

    def create_thumbnail(self, title, image_path=None):
        path = Path(self.channel_cfg.videos_dir) / "fake.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"thumb")
        return str(path)


class _FakeUploader:
    def __init__(self, channel_cfg=None):
        pass

    def upload_video(self, video_path, content, thumbnail_path=None, privacy="public", publish_at=None):
        return "video-test"

    def get_channel_stats(self):
        return {"subscribers": 0}


class _AllowGate:
    def to_dict(self):
        return {"ok": True, "status": "allowed"}


class _AllowContentQuality:
    publish_decision = "allow"
    block_reasons: list[str] = []
    scores: dict[str, float] = {}
    script_similarity = 0.0


def _fact_check_ok(*args, **kwargs):
    return {"fact_check_status": "passed", "sources": [], "volatile_claims_checked": []}


def _read_evidence(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _setup_pipeline(monkeypatch, tmp_path, contents, *, prompt_mutation: str | None = None, append_failure: bool = False):
    evidence_path = tmp_path / "evidence" / "automatic_qa_evidence.jsonl"
    events: list[tuple[str, int]] = []
    evaluator_results: list[dict] = []
    _SequenceGenerator.contents = list(contents)
    _SequenceGenerator.calls = 0
    _SequenceGenerator.events = events
    cfg = _FakeConfig(tmp_path)
    cfg.ensure_directories()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRODUCTION_QUALITY_PLATFORM_ENABLED", "true")
    monkeypatch.setenv("PIPELINE_RUNTIME_GATES_IN_TESTS", "true")
    monkeypatch.setattr(automatic_qa_evidence, "AUTOMATIC_QA_EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(pipeline, "ContentGenerator", _SequenceGenerator)
    monkeypatch.setattr(pipeline, "TTSEngine", _FakeTTS)
    monkeypatch.setattr(pipeline, "ImageFetcher", _FakeFetcher)
    monkeypatch.setattr(pipeline, "VideoCreator", _FakeCreator)
    monkeypatch.setattr(pipeline, "YouTubeUploader", _FakeUploader)
    monkeypatch.setattr(pipeline, "ensure_production_safety_gate", lambda **_kwargs: _AllowGate())
    monkeypatch.setattr(pipeline, "build_default_fact_provider", lambda: object())
    monkeypatch.setattr(pipeline, "validate_script_factual_freshness", _fact_check_ok)
    monkeypatch.setattr(content_quality_guard, "evaluate_content_quality", lambda *_args, **_kwargs: _AllowContentQuality())
    monkeypatch.setattr(pipeline, "evaluate_upload_precheck", lambda **_kwargs: {"status": "allow", "guard_reason_codes": [], "details": {}})
    monkeypatch.setattr(pipeline, "register_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "append_performance_snapshot", lambda *_args, **_kwargs: None)
    real_record_automatic_qa_evidence = pipeline.record_automatic_qa_evidence

    def _evaluate_once(payload):
        result = _real_evaluate_automatic_qa(payload)
        evaluator_results.append(result)
        events.append(("evaluate", len(evaluator_results) - 1))
        return result

    def _record_once(**kwargs):
        events.append(("append", int(kwargs.get("qa_attempt", -1))))
        if append_failure:
            raise RuntimeError("append failed")
        return real_record_automatic_qa_evidence(**kwargs)

    monkeypatch.setattr(pipeline, "evaluate_automatic_qa", _evaluate_once)
    monkeypatch.setattr(pipeline, "record_automatic_qa_evidence", _record_once)
    monkeypatch.setattr(
        visual_diversity,
        "enforce_thumbnail_diversity",
        lambda **kwargs: {
            "accepted": True,
            "regenerated": False,
            "attempts": 1,
            "rejected_attempts": [],
            "record": {"thumbnail_prompt": prompt_mutation or kwargs.get("thumbnail_prompt")},
        },
    )
    monkeypatch.setattr(
        thumbnail_experiments,
        "build_thumbnail_experiment_bundle",
        lambda **kwargs: {
            "accepted": True,
            "regenerated": False,
            "selected_variant_id": "A",
            "selected_prompt": prompt_mutation or kwargs.get("thumbnail_prompt"),
            "variants": [],
        },
    )
    return cfg, evidence_path, events, evaluator_results


def test_pipeline_allow_path_emits_one_level1_record_from_final_payload(monkeypatch, tmp_path):
    cfg, evidence_path, events, evaluator_results = _setup_pipeline(
        monkeypatch,
        tmp_path,
        [_FakeContent(title="Borsa stratejisi", thumbnail_prompt="borsa stratejisi chart")],
    )

    result = pipeline.run_full_pipeline(topic="Borsa stratejisi", generate_only=False, channel_cfg=cfg)

    rows = _read_evidence(evidence_path)
    assert result["automatic_qa"]["decision"] == "allow"
    assert len(rows) == 1
    assert len(evaluator_results) == 1
    assert rows[0]["qa_attempt"] == 0
    assert rows[0]["stage"] == "media_fetch"
    assert rows[0]["decision_evidence"]["thumbnail_prompt"] == "borsa stratejisi chart"
    assert rows[0]["qa_output"]["checks"] == evaluator_results[0]["checks"]
    assert rows[0]["qa_output"]["blocked_checks"] == evaluator_results[0]["blocked_checks"]
    assert rows[0]["qa_output"]["final_decision"] == evaluator_results[0]["decision"]
    assert events.index(("evaluate", 0)) < events.index(("append", 0))


def test_pipeline_retry_regeneration_emits_distinct_records(monkeypatch, tmp_path):
    cfg, evidence_path, events, evaluator_results = _setup_pipeline(
        monkeypatch,
        tmp_path,
        [
            _FakeContent(title="Borsa stratejisi", thumbnail_prompt="unrelated landscape"),
            _FakeContent(title="Borsa stratejisi", thumbnail_prompt="borsa stratejisi chart"),
        ],
    )

    result = pipeline.run_full_pipeline(topic="Borsa stratejisi", generate_only=False, channel_cfg=cfg)

    rows = _read_evidence(evidence_path)
    assert result["automatic_qa"]["decision"] == "allow"
    assert result["pipeline_retry_count"] == 1
    assert len(evaluator_results) == 2
    assert [row["qa_attempt"] for row in rows] == [0, 1]
    assert rows[0]["qa_output"]["final_decision"] == "block"
    assert rows[1]["qa_output"]["final_decision"] == "allow"
    assert rows[0]["decision_evidence"]["thumbnail_prompt"] == "unrelated landscape"
    assert rows[1]["decision_evidence"]["thumbnail_prompt"] == "borsa stratejisi chart"
    assert rows[0]["integrity"]["evidence_hash"] != rows[1]["integrity"]["evidence_hash"]
    assert events.index(("evaluate", 0)) < events.index(("append", 0)) < events.index(("generate", 1))
    assert events.index(("evaluate", 1)) < events.index(("append", 1))


def test_pipeline_evidence_retains_post_generation_prompt_mutation(monkeypatch, tmp_path):
    cfg, evidence_path, _events, _evaluator_results = _setup_pipeline(
        monkeypatch,
        tmp_path,
        [_FakeContent(title="Borsa stratejisi", thumbnail_prompt="original prompt")],
        prompt_mutation="borsa stratejisi mutated final prompt",
    )

    result = pipeline.run_full_pipeline(topic="Borsa stratejisi", generate_only=False, channel_cfg=cfg)

    rows = _read_evidence(evidence_path)
    assert result["automatic_qa"]["decision"] == "allow"
    assert rows[0]["decision_evidence"]["thumbnail_prompt"] == "borsa stratejisi mutated final prompt"


def test_pipeline_final_hard_block_emits_two_distinct_records(monkeypatch, tmp_path):
    cfg, evidence_path, _events, evaluator_results = _setup_pipeline(
        monkeypatch,
        tmp_path,
        [
            _FakeContent(title="Borsa stratejisi", thumbnail_prompt="unrelated landscape"),
            _FakeContent(title="Borsa stratejisi", thumbnail_prompt="another unrelated landscape"),
        ],
    )

    try:
        pipeline.run_full_pipeline(topic="Borsa stratejisi", generate_only=False, channel_cfg=cfg)
    except RuntimeError as exc:
        assert "automatic_qa_blocked: thumbnail_relevance" in str(exc)
    else:
        raise AssertionError("expected final automatic QA block")

    rows = _read_evidence(evidence_path)
    assert len(evaluator_results) == 2
    assert [row["qa_attempt"] for row in rows] == [0, 1]
    assert [row["qa_output"]["final_decision"] for row in rows] == ["block", "block"]
    assert rows[0]["integrity"]["evidence_hash"] != rows[1]["integrity"]["evidence_hash"]


def test_pipeline_evidence_append_failure_is_fail_open_and_visible(monkeypatch, tmp_path):
    cfg, evidence_path, _events, evaluator_results = _setup_pipeline(
        monkeypatch,
        tmp_path,
        [_FakeContent(title="Borsa stratejisi", thumbnail_prompt="borsa stratejisi chart")],
        append_failure=True,
    )

    result = pipeline.run_full_pipeline(topic="Borsa stratejisi", generate_only=False, channel_cfg=cfg)

    assert result["automatic_qa"]["decision"] == "allow"
    assert len(evaluator_results) == 1
    assert not evidence_path.exists()
    assert result["automatic_qa_evidence_warning"]["code"] == "automatic_qa_evidence_append_failed"