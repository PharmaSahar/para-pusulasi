import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_quality_scores_is_deterministic_for_same_input():
    from src.quality_scoring import build_quality_scores

    payload = {
        "title": "2026'da 50.000 TL ile yatirim stratejisi nedir?",
        "description": "Detayli analiz ve adim adim plan.",
        "script": "Giris\nNeden\nAdim 1\nAdim 2\nSonuc",
        "tags": ["yatirim", "2026", "borsa"],
    }

    s1 = build_quality_scores(**payload)
    s2 = build_quality_scores(**payload)

    assert s1 == s2


def test_build_quality_scores_contains_required_keys_and_ranges():
    from src.quality_scoring import build_quality_scores

    scores = build_quality_scores(
        title="Borsa mi altin mi? 2026 karsilastirma",
        description="SEO uyumlu aciklama metni ve temel kavramlar.",
        script="Giris\nNasil\nAdim\nOzet\nSonuc",
        tags=["borsa", "altin", "karsilastirma", "finans"],
    )

    expected_keys = {
        "hook_score",
        "structure_score",
        "information_density_score",
        "originality_score",
        "humanity_score",
        "promise_to_payoff_score",
        "seo_score",
        "overall_quality_score",
    }

    assert set(scores.keys()) == expected_keys
    for value in scores.values():
        assert isinstance(value, int)
        assert 0 <= value <= 100


def test_build_quality_scores_changes_with_input_variation():
    from src.quality_scoring import build_quality_scores

    low = build_quality_scores(
        title="kisa",
        description="",
        script="",
        tags=[],
    )
    high = build_quality_scores(
        title="2026'da 120.000 TL icin en iyi strateji nedir?",
        description="Anahtar kelimelerle detayli SEO aciklamasi ve strateji ozetleri.",
        script="Giris\nNeden\nAdim\nStrateji\nSonuc\nOzet\n50000 TL ornek",
        tags=["yatirim", "strateji", "2026", "finans", "getiri", "borsa"],
    )

    assert low != high


def test_content_generator_attaches_quality_score_metadata(monkeypatch):
    import src.content_generator as cg

    class FakeMessages:
        def create(self, **kwargs):
            payload = {
                "title": "Title 2026?",
                "description": "Description",
                "tags": ["a", "b"],
                "script": "Script with sonuc and adim.",
                "thumbnail_prompt": "Thumb",
                "category_id": "27",
                "hook": "Hook",
                "next_video_teaser": "Teaser",
                "pexels_search": "query",
                "chart_data": {"type": "bar", "data": {"labels": ["x"], "values": [1]}},
            }
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))])

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    original_init = cg.ContentGenerator.__init__
    original_topics = cg.ContentGenerator.generate_topic_ideas

    def fake_init(self, channel_cfg=None):
        self.client = FakeClient()
        self.niche = "test"
        self.model = "fake-model"
        self._persona = None
        self._channel_name = "Test"
        self._channel_dna_overrides = {}

    monkeypatch.setattr(cg.ContentGenerator, "__init__", fake_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", lambda self, count=3: ["a", "b", "c"])

    content = cg.ContentGenerator().generate_video_content("Topic")

    assert "quality_score_metadata" in content.to_dict()
    assert "overall_quality_score" in content.quality_score_metadata
    assert isinstance(content.quality_score_metadata["overall_quality_score"], int)

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)


def test_content_generator_fail_open_when_quality_scoring_fails(monkeypatch):
    import src.content_generator as cg

    class FakeMessages:
        def create(self, **kwargs):
            payload = {
                "title": "Title",
                "description": "Description",
                "tags": ["a"],
                "script": "Script",
                "thumbnail_prompt": "Thumb",
                "category_id": "27",
                "hook": "Hook",
                "next_video_teaser": "Teaser",
                "pexels_search": "query",
                "chart_data": None,
            }
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))])

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    original_init = cg.ContentGenerator.__init__
    original_topics = cg.ContentGenerator.generate_topic_ideas

    def fake_init(self, channel_cfg=None):
        self.client = FakeClient()
        self.niche = "test"
        self.model = "fake-model"
        self._persona = None
        self._channel_name = "Test"
        self._channel_dna_overrides = {}

    monkeypatch.setattr(cg.ContentGenerator, "__init__", fake_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", lambda self, count=3: ["a", "b", "c"])

    def boom(**_kwargs):
        raise RuntimeError("quality scoring down")

    monkeypatch.setattr(cg, "build_quality_scores", boom)

    content = cg.ContentGenerator().generate_video_content("Topic")
    assert content.title == "Title"
    assert content.quality_score_metadata == {}

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)


def test_quality_scoring_does_not_change_prompt_text(monkeypatch):
    import src.content_generator as cg

    captured = {"prompt": None}

    class FakeMessages:
        def create(self, **kwargs):
            payload = {
                "title": "Title",
                "description": "Description",
                "tags": ["a"],
                "script": "Script",
                "thumbnail_prompt": "Thumb",
                "category_id": "27",
                "hook": "Hook",
                "next_video_teaser": "Teaser",
                "pexels_search": "query",
                "chart_data": None,
            }
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))])

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    original_init = cg.ContentGenerator.__init__
    original_topics = cg.ContentGenerator.generate_topic_ideas

    def fake_init(self, channel_cfg=None):
        self.client = FakeClient()
        self.niche = "test"
        self.model = "fake-model"
        self._persona = None
        self._channel_name = "Test"
        self._channel_dna_overrides = {}

    monkeypatch.setattr(cg.ContentGenerator, "__init__", fake_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", lambda self, count=3: ["a", "b", "c"])
    monkeypatch.setattr(cg, "_build_content_prompt", lambda *args, **kwargs: "FIXED_PROMPT")

    def fake_build_prompt_metadata(prompt_text):
        captured["prompt"] = prompt_text
        return {}

    monkeypatch.setattr(cg, "build_prompt_metadata", fake_build_prompt_metadata)

    cg.ContentGenerator().generate_video_content("Topic")
    assert captured["prompt"] == "FIXED_PROMPT"

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)
