from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.content_generator as content_generator


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]


class _FakeMessages:
    def __init__(self, text: str):
        self._text = text

    def create(self, **kwargs):
        return _FakeResponse(self._text)


class _FakeAnthropicClient:
    def __init__(self, api_key=None, max_retries=None):
        text = (
            "1. Dolar/TL 2026 sonu tahminleri\n"
            "2. Uyku duzenini guclendirme yollari\n"
            "3. Stres yonetimi rutini"
        )
        self.messages = _FakeMessages(text)


class _FakeConfig:
    anthropic_api_key = "key"
    niche = "saglik"
    persona = "Saglik editor"
    name = "Saglik Pusulasi"
    topics = ["uyku", "stres", "beslenme"]


class _FakeFinanceConfig:
    anthropic_api_key = "key"
    niche = "kisisel_finans"
    persona = "Finans editor"
    name = "Para Pusulasi"
    topics = ["dolar", "borsa", "enflasyon"]


class _FakeContent:
    def __init__(self, title: str = "Saglik Basligi"):
        self.title = title
        self.description = "desc"
        self.tags = ["a"]
        self.script = "script"
        self.thumbnail_prompt = "thumb"
        self.category_id = "27"
        self.niche = "saglik"
        self.hook = "hook"
        self.next_video_teaser = "next"
        self.pexels_search = "query"
        self.chart_data = {}
        self.prompt_metadata = {}
        self.channel_dna_metadata = {}
        self.quality_score_metadata = {}
        self.created_at = "2026-07-11T10:00:00"

    def save(self, path: str | None = None) -> str:
        p = Path(path or "output/scripts/fake_test_content.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        return str(p)


def _build_health_generator(monkeypatch, provenance_context: dict | None = None):
    monkeypatch.setattr(content_generator.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(content_generator, "_load_used_titles", lambda: [])
    monkeypatch.setattr(
        "src.content_generator.get_trending_topics_with_metadata",
        lambda niche, count=4: {
            "provider": "pytrends",
            "raw_provider_rows": [
                {"keyword": "diyet", "query": "Dolar/TL 2026 sonu tahminleri", "value": 1200},
                {"keyword": "uyku", "query": "Uyku duzenini guclendirme yollari", "value": 800},
            ],
            "normalized_provider_rows": [
                "Dolar/TL 2026 sonu tahminleri",
                "Uyku duzenini guclendirme yollari",
            ],
            "topics": [
                "Dolar/TL 2026 sonu tahminleri",
                "Uyku duzenini guclendirme yollari",
            ],
        },
        raising=False,
    )
    monkeypatch.setattr("src.content_generator.get_seasonal_boost_topics", lambda niche: [], raising=False)
    return content_generator.ContentGenerator(channel_cfg=_FakeConfig(), provenance_context=provenance_context)


def test_health_channel_rejects_finance_candidates(monkeypatch):
    generator = _build_health_generator(monkeypatch)

    topics = generator.generate_topic_ideas(count=3)

    assert topics
    assert all("Dolar/TL" not in item for item in topics)
    rejected = generator._last_topic_trace.get("rejected_candidates") or []
    assert any("market_term_not_allowed_for_non_market_niche" in r.get("reasons", []) for r in rejected)


def test_all_rejected_uses_channel_scoped_fallback(monkeypatch):
    generator = _build_health_generator(monkeypatch)
    generator._channel_topics = ["uyku", "stres"]

    monkeypatch.setattr(
        "src.content_generator.get_trending_topics_with_metadata",
        lambda niche, count=4: {
            "provider": "pytrends",
            "raw_provider_rows": [{"keyword": "x", "query": "Dolar/TL 2026 sonu tahminleri", "value": 10}],
            "normalized_provider_rows": ["Dolar/TL 2026 sonu tahminleri"],
            "topics": ["Dolar/TL 2026 sonu tahminleri"],
        },
        raising=False,
    )

    topics = generator.generate_topic_ideas(count=2)

    assert topics == ["uyku", "stres"]
    assert generator._last_topic_trace.get("fallback_invoked") is True
    assert generator._last_topic_trace.get("fallback_source") == "channel_scoped"


def test_no_valid_fallback_blocks_run(monkeypatch):
    generator = _build_health_generator(monkeypatch)
    generator._channel_topics = []

    monkeypatch.setattr(
        "src.content_generator.get_trending_topics_with_metadata",
        lambda niche, count=4: {
            "provider": "pytrends",
            "raw_provider_rows": [{"keyword": "x", "query": "Dolar/TL 2026 sonu tahminleri", "value": 10}],
            "normalized_provider_rows": ["Dolar/TL 2026 sonu tahminleri"],
            "topics": ["Dolar/TL 2026 sonu tahminleri"],
        },
        raising=False,
    )

    with pytest.raises(content_generator.TopicDomainBlockedError):
        generator.generate_topic_ideas(count=2)


def test_provenance_file_persisted_with_selected_index(monkeypatch, tmp_path):
    ctx = {
        "run_id": "run_abc",
        "content_id": "content_xyz",
        "channel_id": "saglik_pusulasi",
        "channel_slug": "saglik-pusulasi",
        "runtime_build_identity": {
            "git_sha_full": "abc123",
            "git_sha_short": "abc123",
            "process_pid": 1,
            "process_started_at_utc": "2026-07-11T00:00:00+00:00",
            "python_executable": "/usr/bin/python",
            "working_directory": "/repo",
        },
        "output_dir": str(tmp_path),
    }
    generator = _build_health_generator(monkeypatch, provenance_context=ctx)
    monkeypatch.setattr(generator, "generate_video_content", lambda *args, **kwargs: _FakeContent())

    content = generator.generate_and_save(topic=None)

    assert content.title == "Saglik Basligi"
    path = tmp_path / "topic_provenance" / "saglik_pusulasi" / "run_abc" / "content_xyz.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["selected_index"] == 0
    assert data["selected_topic"]
    assert data["raw_provider_rows"]
    assert data["hashes"]["payload"]


def test_same_run_regeneration_replaces_provenance_without_collision(monkeypatch, tmp_path):
    ctx = {
        "run_id": "run_retry",
        "content_id": "content_retry",
        "channel_id": "para_pusulasi",
        "channel_slug": "para_pusulasi",
        "runtime_build_identity": {},
        "output_dir": str(tmp_path),
    }
    generator = content_generator.ContentGenerator(channel_cfg=_FakeFinanceConfig(), provenance_context=ctx)

    generator._last_topic_trace = {
        "provider": "internal_topic_source",
        "raw_provider_rows": [{"query": "Türkiye'de Emeklilik Planlaması"}],
        "normalized_provider_rows": ["Türkiye'de Emeklilik Planlaması"],
        "pre_filter_candidates": ["Türkiye'de Emeklilik Planlaması"],
        "post_filter_candidates": ["Türkiye'de Emeklilik Planlaması"],
    }
    generator._persist_topic_provenance(
        selected_index=0,
        selected_topic="Türkiye'de Emeklilik Planlaması",
        final_topics=["Türkiye'de Emeklilik Planlaması"],
    )

    generator._last_topic_trace = {
        "provider": "fact_check_retry",
        "raw_provider_rows": [{"query": "Emtia oynakligini kesin seviye vermeden yorumlama rehberi"}],
        "normalized_provider_rows": ["Emtia oynakligini kesin seviye vermeden yorumlama rehberi"],
        "pre_filter_candidates": ["Emtia oynakligini kesin seviye vermeden yorumlama rehberi"],
        "post_filter_candidates": ["Emtia oynakligini kesin seviye vermeden yorumlama rehberi"],
    }
    generator._persist_topic_provenance(
        selected_index=0,
        selected_topic="Emtia oynakligini kesin seviye vermeden yorumlama rehberi",
        final_topics=["Emtia oynakligini kesin seviye vermeden yorumlama rehberi"],
    )

    path = tmp_path / "topic_provenance" / "para_pusulasi" / "run_retry" / "content_retry.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "run_retry"
    assert data["content_id"] == "content_retry"
    assert data["channel_id"] == "para_pusulasi"
    assert data["provider_name"] == "fact_check_retry"
    assert data["selected_topic"] == "Emtia oynakligini kesin seviye vermeden yorumlama rehberi"


def test_conflicting_provenance_identity_remains_blocked(monkeypatch, tmp_path):
    ctx = {
        "run_id": "run_retry",
        "content_id": "content_retry",
        "channel_id": "para_pusulasi",
        "channel_slug": "para_pusulasi",
        "runtime_build_identity": {},
        "output_dir": str(tmp_path),
    }
    path = tmp_path / "topic_provenance" / "para_pusulasi" / "run_retry" / "content_retry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "run_retry",
                "content_id": "content_retry",
                "channel_id": "saglik_pusulasi",
                "selected_topic": "Uyku kalitesini artirma yollari",
            }
        ),
        encoding="utf-8",
    )
    generator = content_generator.ContentGenerator(channel_cfg=_FakeFinanceConfig(), provenance_context=ctx)
    generator._last_topic_trace = {
        "provider": "internal_topic_source",
        "raw_provider_rows": [{"query": "Dolar/TL 2026 sonu tahminleri"}],
        "normalized_provider_rows": ["Dolar/TL 2026 sonu tahminleri"],
        "pre_filter_candidates": ["Dolar/TL 2026 sonu tahminleri"],
        "post_filter_candidates": ["Dolar/TL 2026 sonu tahminleri"],
    }

    with pytest.raises(content_generator.TopicDomainBlockedError) as excinfo:
        generator._persist_topic_provenance(
            selected_index=0,
            selected_topic="Dolar/TL 2026 sonu tahminleri",
            final_topics=["Dolar/TL 2026 sonu tahminleri"],
        )

    assert "topic_provenance_collision" in str(excinfo.value)
    assert excinfo.value.trace["existing_identity"]["channel_id"] == "saglik_pusulasi"
    assert excinfo.value.trace["attempted_identity"]["channel_id"] == "para_pusulasi"


def test_retry_cannot_bypass_filter(monkeypatch):
    generator = _build_health_generator(monkeypatch)
    captured = {"topic": None}

    def _fake_generate_video_content(topic, *args, **kwargs):
        captured["topic"] = topic
        return _FakeContent()

    monkeypatch.setattr(generator, "generate_video_content", _fake_generate_video_content)

    generator.generate_and_save(topic="Dolar/TL 2026 sonu tahminleri")

    assert captured["topic"] in {"uyku", "stres", "beslenme"}


def test_finance_channel_accepts_finance_candidates(monkeypatch):
    monkeypatch.setattr(content_generator.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(content_generator, "_load_used_titles", lambda: [])
    monkeypatch.setattr(
        "src.content_generator.get_trending_topics_with_metadata",
        lambda niche, count=4: {
            "provider": "pytrends",
            "raw_provider_rows": [{"keyword": "dolar", "query": "Dolar/TL 2026 sonu tahminleri", "value": 10}],
            "normalized_provider_rows": ["Dolar/TL 2026 sonu tahminleri"],
            "topics": ["Dolar/TL 2026 sonu tahminleri"],
        },
        raising=False,
    )
    monkeypatch.setattr("src.content_generator.get_seasonal_boost_topics", lambda niche: [], raising=False)

    generator = content_generator.ContentGenerator(channel_cfg=_FakeFinanceConfig())
    topics = generator.generate_topic_ideas(count=2)

    assert any("Dolar/TL" in item for item in topics)


def test_provenance_paths_are_run_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(content_generator.anthropic, "Anthropic", _FakeAnthropicClient)
    monkeypatch.setattr(content_generator, "_load_used_titles", lambda: [])
    monkeypatch.setattr(
        "src.content_generator.get_trending_topics_with_metadata",
        lambda niche, count=4: {
            "provider": "pytrends",
            "raw_provider_rows": [{"keyword": "uyku", "query": "Uyku duzenini guclendirme yollari", "value": 10}],
            "normalized_provider_rows": ["Uyku duzenini guclendirme yollari"],
            "topics": ["Uyku duzenini guclendirme yollari"],
        },
        raising=False,
    )
    monkeypatch.setattr("src.content_generator.get_seasonal_boost_topics", lambda niche: [], raising=False)

    ctx1 = {
        "run_id": "run_1",
        "content_id": "content_1",
        "channel_id": "saglik_pusulasi",
        "runtime_build_identity": {},
        "output_dir": str(tmp_path),
    }
    ctx2 = {
        "run_id": "run_2",
        "content_id": "content_2",
        "channel_id": "saglik_pusulasi",
        "runtime_build_identity": {},
        "output_dir": str(tmp_path),
    }

    g1 = content_generator.ContentGenerator(channel_cfg=_FakeConfig(), provenance_context=ctx1)
    g2 = content_generator.ContentGenerator(channel_cfg=_FakeConfig(), provenance_context=ctx2)
    monkeypatch.setattr(g1, "generate_video_content", lambda *args, **kwargs: _FakeContent())
    monkeypatch.setattr(g2, "generate_video_content", lambda *args, **kwargs: _FakeContent())

    g1.generate_and_save()
    g2.generate_and_save()

    p1 = tmp_path / "topic_provenance" / "saglik_pusulasi" / "run_1" / "content_1.json"
    p2 = tmp_path / "topic_provenance" / "saglik_pusulasi" / "run_2" / "content_2.json"
    assert p1.exists()
    assert p2.exists()
    assert p1.read_text(encoding="utf-8") != p2.read_text(encoding="utf-8")
