from types import SimpleNamespace

from src.image_fetcher import ImageFetcher


def test_sanitize_query_rejects_risky_visual_terms_for_education_channel():
    cfg = SimpleNamespace(
        niche="egitim",
        pexels_query="education learning study books",
        pexels_api_key="demo-key",
    )

    fetcher = ImageFetcher(channel_cfg=cfg)

    query = fetcher._sanitize_query("bikini beach sunset luxury", "Surec Kontrol Listesi")

    assert query == "education learning study books"


def test_sanitize_query_rejects_off_niche_override_for_education_channel():
    cfg = SimpleNamespace(
        niche="egitim",
        pexels_query="education learning study books",
        pexels_api_key="demo-key",
    )

    fetcher = ImageFetcher(channel_cfg=cfg)

    query = fetcher._sanitize_query("startup founders office pitch deck", "Surec Kontrol Listesi")

    assert query == "education learning study books"


def test_sanitize_query_keeps_relevant_education_search_terms():
    cfg = SimpleNamespace(
        niche="egitim",
        pexels_query="education learning study books",
        pexels_api_key="demo-key",
    )

    fetcher = ImageFetcher(channel_cfg=cfg)

    query = fetcher._sanitize_query("student studying library desk", "Surec Kontrol Listesi")

    assert query == "student studying library desk"


def test_sanitize_query_uses_canonical_safe_fallback_when_channel_default_is_off_niche():
    cfg = SimpleNamespace(
        niche="teknoloji",
        pexels_query="money management tips",
        pexels_api_key="demo-key",
    )

    fetcher = ImageFetcher(channel_cfg=cfg)

    query = fetcher._sanitize_query("bikini beach sunset luxury", "AI Notetaking")

    assert query == "technology software digital workspace screens"


def test_sanitize_query_supports_girisimcilik_niche_alias():
    cfg = SimpleNamespace(
        niche="girisimcilik",
        pexels_query="startup entrepreneur business success",
        pexels_api_key="demo-key",
    )

    fetcher = ImageFetcher(channel_cfg=cfg)

    query = fetcher._sanitize_query("startup founders pitch deck office", "Girisim Dersi")

    assert query == "startup founders pitch deck office"


def test_sanitize_query_supports_psikoloji_channel_queries():
    cfg = SimpleNamespace(
        niche="psikoloji",
        pexels_query="psychology mind mental health meditation",
        pexels_api_key="demo-key",
    )

    fetcher = ImageFetcher(channel_cfg=cfg)

    query = fetcher._sanitize_query("mental wellness reflection journal", "Stres Yonetimi")

    assert query == "mental wellness reflection journal"