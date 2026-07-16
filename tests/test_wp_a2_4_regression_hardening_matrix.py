from __future__ import annotations

from types import SimpleNamespace

from src.channel_manager import resolve_allow_market_language
from src.content_generator import ContentGenerator, VideoContent, _build_content_prompt
from src.metadata_repair import ensure_minimum_tags
from src.playlist_manager import PlaylistManager
from src.premium_services import _is_explicit_finance_thumbnail_context
from src.scheduler_utils import notify_startup
from src.youtube_uploader import YouTubeUploader


class _FakePlaylistsInsert:
    def execute(self):
        return {"id": "playlist-123"}


class _FakePlaylists:
    def insert(self, **_kwargs):
        return _FakePlaylistsInsert()


class _FakePlaylistItemsInsert:
    def execute(self):
        return {"ok": True}


class _FakePlaylistItems:
    def insert(self, **_kwargs):
        return _FakePlaylistItemsInsert()


class _FakeYoutubeService:
    def playlists(self):
        return _FakePlaylists()

    def playlistItems(self):
        return _FakePlaylistItems()


def test_market_language_policy_matrix_is_explicit_and_centralized():
    allowed = {"kisisel_finans", "borsa", "kripto", "gayrimenkul"}
    neutral = {"saglik", "kariyer", "egitim", "teknoloji", "girisimcilik", "general", "legacy_unknown"}

    for niche in allowed:
        assert resolve_allow_market_language(niche=niche, explicit_value=None) is True

    for niche in neutral:
        assert resolve_allow_market_language(niche=niche, explicit_value=None) is False

    # Explicit override always wins over niche fallback.
    assert resolve_allow_market_language(niche="saglik", explicit_value=True) is True
    assert resolve_allow_market_language(niche="borsa", explicit_value=False) is False


def test_free_text_hints_cannot_authorize_market_language_for_legacy_record(monkeypatch):
    class _FakeAnthropicClient:
        def __init__(self, api_key=None, max_retries=None):
            self.messages = object()

    monkeypatch.setattr("src.content_generator.anthropic.Anthropic", _FakeAnthropicClient)

    cfg = SimpleNamespace(
        anthropic_api_key="key",
        niche="legacy_unknown",
        allow_market_language=None,
        persona="Legacy channel persona",
        name="Legacy Channel",
        topics=["borsa", "kripto", "yatirim"],
        tone="piyasa odakli",
    )

    generator = ContentGenerator(channel_cfg=cfg)
    assert generator._active_channel_allows_market_language(topic_hint="BIST 100 dolar bitcoin") is False


def test_content_prompt_matrix_finance_vs_non_finance():
    # Finance classes: explicit finance language remains available.
    for niche in ("kisisel_finans", "borsa", "kripto", "gayrimenkul"):
        prompt = _build_content_prompt(
            topic="Piyasa analizi",
            prev_title=None,
            next_topic_hint="Portfoy dagilimi",
            content_type="semi_evergreen",
            niche=niche,
        )
        assert "Türk finans YouTube kanalı" in prompt

    # Non-market classes: remain neutral by default.
    for niche in ("saglik", "kariyer", "egitim", "teknoloji", "girisimcilik"):
        prompt = _build_content_prompt(
            topic="Alan odakli pratik rehber",
            prev_title=None,
            next_topic_hint="Sonraki adim",
            content_type="semi_evergreen",
            niche=niche,
        )
        assert "Türk finans YouTube kanalı" not in prompt
        assert "alakasız piyasa referansları ekleme" in prompt

    # Entrepreneurship may allow finance only with explicit policy.
    prompt_override = _build_content_prompt(
        topic="Pazar analizi",
        prev_title=None,
        next_topic_hint="Nakit akisi",
        content_type="semi_evergreen",
        niche="girisimcilik",
        allow_market_language=True,
    )
    assert "Türk finans YouTube kanalı" in prompt_override


def test_metadata_and_uploader_fallback_matrix():
    # Neutral channels keep neutral fallback tags.
    neutral_tags = ensure_minimum_tags(title="Uyku duzeni rehberi", tags=["uyku"], niche="saglik", min_tags=8)
    neutral_lower = [t.lower() for t in neutral_tags]
    assert "finans" not in neutral_lower
    assert "yatirim" not in neutral_lower

    uploader = YouTubeUploader()
    neutral_content = VideoContent(
        title="Saglikli rutin",
        description="desc",
        tags=[],
        script="script",
        thumbnail_prompt="prompt",
        category_id="27",
        niche="saglik",
    )
    uploader_neutral = [t.lower() for t in uploader._fallback_tags_from_content(neutral_content)]  # noqa: SLF001
    assert "finans" not in uploader_neutral
    assert "yatirim" not in uploader_neutral

    # Finance channels preserve explicit finance behavior.
    finance_tags = ensure_minimum_tags(title="Borsa trend analizi", tags=["borsa"], niche="finans", min_tags=8)
    finance_lower = [t.lower() for t in finance_tags]
    assert "finans" in finance_lower

    finance_content = VideoContent(
        title="Piyasa yorumu",
        description="desc",
        tags=[],
        script="script",
        thumbnail_prompt="prompt",
        category_id="27",
        niche="finans",
    )
    uploader_finance = [t.lower() for t in uploader._fallback_tags_from_content(finance_content)]  # noqa: SLF001
    assert "finans" in uploader_finance


def test_playlist_and_premium_matrix():
    manager = PlaylistManager(_FakeYoutubeService())

    # Neutral fallback playlist remains neutral.
    assert manager._match_playlist("Uyku hijyeni notlari") == "Genel Bilgi Rehberi 2026"  # noqa: SLF001

    # Explicit market routing remains available.
    assert manager._match_playlist("Borsa portfoy yonetimi") == "Yatirim Rehberi 2026"  # noqa: SLF001
    assert manager._match_playlist("Bitcoin blockchain giris") == "Kripto Para"  # noqa: SLF001
    assert manager._match_playlist("Konut kira analiz") == "Gayrimenkul Yatirimi"  # noqa: SLF001

    # Premium defaults stay neutral unless explicit finance context exists.
    assert _is_explicit_finance_thumbnail_context(niche="saglik") is False
    assert _is_explicit_finance_thumbnail_context(niche="kariyer") is False
    assert _is_explicit_finance_thumbnail_context(niche="kisisel_finans") is True
    assert _is_explicit_finance_thumbnail_context(niche="borsa") is True
    assert _is_explicit_finance_thumbnail_context(niche="kripto") is True
    assert _is_explicit_finance_thumbnail_context(niche="gayrimenkul") is True
    assert _is_explicit_finance_thumbnail_context(style_context="finance_channel") is True


def test_scheduler_startup_presentation_remains_neutral(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr("src.scheduler_utils.send_telegram", lambda message: captured.append(message))
    monkeypatch.setattr("src.scheduler_utils.get_free_disk_gb", lambda: 11.5)

    notify_startup(7)

    assert len(captured) == 1
    msg = captured[0]
    assert "Parapusulasi Scheduler Basladi" in msg
    lowered = msg.lower()
    for token in ("para pusulasi", "finance", "finans", "investment", "borsa", "crypto", "kripto"):
        assert token not in lowered