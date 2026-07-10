import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_channel_dna_metadata_is_deterministic_for_same_payload():
    from src.channel_dna import build_channel_dna_metadata

    payload = {
        "tone": "samimi",
        "audience": "yatirimci",
        "voice_archetype": "mentor",
        "evidence_style": "veri",
        "forbidden_patterns": ["genel gecis", "robotik acilis"],
        "signature_structure": ["hook", "analiz", "cta"],
    }
    m1 = build_channel_dna_metadata(**payload)
    m2 = build_channel_dna_metadata(**payload)

    assert m1["channel_dna_hash"] == m2["channel_dna_hash"]
    assert m1["channel_dna_id"] == m2["channel_dna_id"]
    assert m1["channel_dna_version"] == m2["channel_dna_version"]


def test_build_channel_dna_metadata_changes_when_payload_changes():
    from src.channel_dna import build_channel_dna_metadata

    m1 = build_channel_dna_metadata(tone="samimi")
    m2 = build_channel_dna_metadata(tone="analitik")

    assert m1["channel_dna_hash"] != m2["channel_dna_hash"]
    assert m1["channel_dna_id"] != m2["channel_dna_id"]


def test_build_channel_dna_metadata_has_simple_version_field():
    from src.channel_dna import build_channel_dna_metadata

    m = build_channel_dna_metadata()
    assert m["channel_dna_version"] == "v1"


def test_content_generator_attaches_channel_dna_metadata(monkeypatch):
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
    monkeypatch.setattr(cg, "_content_has_niche_mismatch", lambda *_args, **_kwargs: False)

    content = cg.ContentGenerator().generate_video_content("Topic")
    assert content.channel_dna_metadata.get("channel_dna_hash")
    assert content.channel_dna_metadata.get("channel_dna_id", "").startswith("cd_")
    assert content.channel_dna_metadata.get("channel_dna_version") == "v1"
    assert "channel_dna_metadata" in content.to_dict()

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)


def test_content_generator_fail_open_when_channel_dna_registry_fails(monkeypatch):
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
    monkeypatch.setattr(cg, "_content_has_niche_mismatch", lambda *_args, **_kwargs: False)

    def boom(**_kwargs):
        raise RuntimeError("channel dna registry down")

    monkeypatch.setattr(cg, "build_channel_dna_metadata", boom)

    content = cg.ContentGenerator().generate_video_content("Topic")
    assert content.title == "Title"
    assert content.channel_dna_metadata == {}

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)


def test_channel_dna_attachment_does_not_change_prompt_text(monkeypatch):
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
    monkeypatch.setattr(cg, "_content_has_niche_mismatch", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cg, "_build_content_prompt", lambda *args, **kwargs: "FIXED_PROMPT")

    def fake_build_prompt_metadata(prompt_text):
        captured["prompt"] = prompt_text
        return {}

    monkeypatch.setattr(cg, "build_prompt_metadata", fake_build_prompt_metadata)

    cg.ContentGenerator().generate_video_content("Topic")
    assert captured["prompt"] == "FIXED_PROMPT"

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)
