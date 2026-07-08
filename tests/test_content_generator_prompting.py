from __future__ import annotations

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