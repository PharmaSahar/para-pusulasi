import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_prompt_metadata_is_deterministic_for_same_prompt():
    from src.prompt_registry import build_prompt_metadata

    p = "same prompt text"
    m1 = build_prompt_metadata(p)
    m2 = build_prompt_metadata(p)

    assert m1["prompt_hash"] == m2["prompt_hash"]
    assert m1["prompt_id"] == m2["prompt_id"]
    assert m1["prompt_version"] == m2["prompt_version"]


def test_build_prompt_metadata_changes_for_different_prompt():
    from src.prompt_registry import build_prompt_metadata

    m1 = build_prompt_metadata("prompt A")
    m2 = build_prompt_metadata("prompt B")

    assert m1["prompt_hash"] != m2["prompt_hash"]
    assert m1["prompt_id"] != m2["prompt_id"]
    assert m1["prompt_version"] != m2["prompt_version"]


def test_build_prompt_metadata_has_valid_created_at_iso_utc():
    from src.prompt_registry import build_prompt_metadata

    m = build_prompt_metadata("prompt")
    parsed = datetime.fromisoformat(m["created_at"])
    assert parsed.tzinfo is not None


def test_content_generator_attaches_prompt_metadata(monkeypatch):
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

    monkeypatch.setattr(cg.ContentGenerator, "__init__", fake_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", lambda self, count=3: ["a", "b", "c"])

    content = cg.ContentGenerator().generate_video_content("Topic")
    assert content.prompt_metadata.get("prompt_hash")
    assert content.prompt_metadata.get("prompt_id", "").startswith("pr_")
    assert content.prompt_metadata.get("prompt_version", "").startswith("v1-")
    assert "created_at" in content.prompt_metadata
    assert "prompt_metadata" in content.to_dict()

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)


def test_content_generator_fail_open_when_registry_fails(monkeypatch):
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

    monkeypatch.setattr(cg.ContentGenerator, "__init__", fake_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", lambda self, count=3: ["a", "b", "c"])

    def boom(_prompt):
        raise RuntimeError("registry down")

    monkeypatch.setattr(cg, "build_prompt_metadata", boom)

    content = cg.ContentGenerator().generate_video_content("Topic")
    assert content.title == "Title"
    assert content.prompt_metadata == {}

    monkeypatch.setattr(cg.ContentGenerator, "__init__", original_init)
    monkeypatch.setattr(cg.ContentGenerator, "generate_topic_ideas", original_topics)
