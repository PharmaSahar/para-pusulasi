from __future__ import annotations

from types import SimpleNamespace

import src.content_generator as content_generator


def test_system_prompt_uses_channel_persona_when_available(monkeypatch):
    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            self.messages = object()

    class FakeConfig:
        anthropic_api_key = "key"
        niche = "saglik"
        persona = "Sen Saglik Pusulasi icin yazan editor-sensin."
        name = "Saglik Pusulasi"

    monkeypatch.setattr(content_generator.anthropic, "Anthropic", FakeAnthropicClient)

    generator = content_generator.ContentGenerator(channel_cfg=FakeConfig())
    prompt = generator._system_prompt()

    assert prompt.startswith(FakeConfig.persona)
    assert "KANAL UYUMLULUK VE FACT-CHECK SINIRI" in prompt


def test_system_prompt_falls_back_to_default_persona(monkeypatch):
    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            self.messages = object()

    class FakeConfig:
        anthropic_api_key = "key"
        niche = "kisisel_finans"

    monkeypatch.setattr(content_generator.anthropic, "Anthropic", FakeAnthropicClient)

    generator = content_generator.ContentGenerator(channel_cfg=FakeConfig())
    prompt = generator._system_prompt()

    assert prompt.startswith(content_generator.CHANNEL_PERSONA.splitlines()[0])
    assert "Dogrulanamayan fiyat hedefi" in prompt


def test_non_finance_topic_prompt_avoids_market_claims():
    prompt = content_generator._build_topic_prompt(
        3,
        [],
        niche="saglik",
        channel_name="Saglik Pusulasi",
        channel_topics=["beslenme", "uyku", "stres"],
    )

    assert "kanalın ana nişi" in prompt
    assert "Finansal piyasa, BIST, hisse, dolar kuru, Bitcoin, altın, faiz ve enflasyon" in prompt
    assert "Saglik Pusulasi" in prompt


def test_non_finance_content_prompt_uses_non_market_real_world_rule():
    prompt = content_generator._build_content_prompt(
        topic="Saglikli uyku duzeni",
        prev_title=None,
        next_topic_hint="Stres yonetimi",
        content_type="semi_evergreen",
        niche="saglik",
    )

    assert "alakasız piyasa referansları ekleme" in prompt
    assert "enflasyon, kira, maaş baskısı" not in prompt


def test_non_finance_trending_topics_filter_drops_market_topics():
    filtered = content_generator._filter_trending_topics_for_niche(
        [
            "Dolar/TL 2026 sonu tahminleri",
            "Enflasyona karsi en iyi yatirim araclari 2026",
            "Uyku duzenini guclendirme yollari",
        ],
        niche="saglik",
        channel_topics=["beslenme", "uyku", "stres"],
    )

    assert filtered == ["Uyku duzenini guclendirme yollari"]


def test_generate_topic_ideas_filters_finance_trends_for_non_finance_channel(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str):
            self.content = [SimpleNamespace(text=text)]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse("1. Uyku kalitesini artırmanın yolları\n2. Stres yönetimi rutini\n3. Sağlıklı sabah alışkanlıkları")

    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    class FakeConfig:
        anthropic_api_key = "key"
        niche = "saglik"
        persona = "Sen Saglik Pusulasi icin yazan editor-sensin."
        name = "Saglik Pusulasi"
        topics = ["beslenme", "uyku", "stres"]

    monkeypatch.setattr(content_generator.anthropic, "Anthropic", FakeAnthropicClient)
    monkeypatch.setattr(content_generator, "_load_used_titles", lambda: [])
    monkeypatch.setattr(
        "src.content_generator.get_trending_topics",
        lambda niche, count=4: [
            "Dolar/TL 2026 sonu tahminleri",
            "Enflasyona karsi en iyi yatirim araclari 2026",
            "Uyku duzenini guclendirme yollari",
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "src.content_generator.get_seasonal_boost_topics",
        lambda niche: [],
        raising=False,
    )

    generator = content_generator.ContentGenerator(channel_cfg=FakeConfig())
    topics = generator.generate_topic_ideas(count=3)

    assert all("Dolar/TL" not in topic for topic in topics)
    assert all("Enflasyona" not in topic for topic in topics)


def test_generate_topic_ideas_filters_finance_ai_topics_for_non_finance_channel(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str):
            self.content = [SimpleNamespace(text=text)]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse(
                "1. Dolar/TL 2026 sonu tahminleri\n"
                "2. BIST 100 teknik analiz\n"
                "3. Uyku kalitesini artırmanın yolları"
            )

    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    class FakeConfig:
        anthropic_api_key = "key"
        niche = "saglik"
        persona = "Sen Saglik Pusulasi icin yazan editor-sensin."
        name = "Saglik Pusulasi"
        topics = ["beslenme", "uyku", "stres"]

    monkeypatch.setattr(content_generator.anthropic, "Anthropic", FakeAnthropicClient)
    monkeypatch.setattr(content_generator, "_load_used_titles", lambda: [])

    generator = content_generator.ContentGenerator(channel_cfg=FakeConfig())
    topics = generator.generate_topic_ideas(count=3)

    assert all("Dolar/TL" not in topic for topic in topics)
    assert all("BIST" not in topic for topic in topics)
    assert any("Uyku" in topic or "uyku" in topic for topic in topics)


def test_generate_video_content_does_not_fetch_extra_topics(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str):
            self.content = [SimpleNamespace(text=text)]

    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
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
            return FakeResponse(__import__("json").dumps(payload, ensure_ascii=False))

    class FakeAnthropicClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    class FakeConfig:
        anthropic_api_key = "key"
        niche = "saglik"
        persona = "Sen Saglik Pusulasi icin yazan editor-sensin."
        name = "Saglik Pusulasi"
        topics = ["beslenme", "uyku", "stres"]

    monkeypatch.setattr(content_generator.anthropic, "Anthropic", FakeAnthropicClient)
    monkeypatch.setattr(content_generator, "build_prompt_metadata", lambda _prompt: {})
    monkeypatch.setattr(content_generator, "build_channel_dna_metadata", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "build_quality_scores", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "_content_has_niche_mismatch", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(content_generator, "_LAST_ANTHROPIC_CALL_AT", 0.0)

    generator = content_generator.ContentGenerator(channel_cfg=FakeConfig())
    content = generator.generate_video_content("Saglikli uyku duzeni")

    assert content.title == "Title"
    assert generator.client.messages.calls == 1