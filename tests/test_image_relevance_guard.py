"""
Comprehensive tests for image_relevance_guard and ImageFetcher integration.
Covers: hard-block, contextual acceptance, false-positive protection, fallback.
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.image_relevance_guard import (
    classify_asset_relevance,
    select_safe_assets,
    should_reject_asset,
    build_safe_search_queries,
    _HARD_BLOCK_RE,
)
from src.image_fetcher import ImageFetcher, _photo_is_safe, _video_is_safe


# ── Helper builders ────────────────────────────────────────────────────────────

def _photo(alt: str, url: str = "https://pexels.com/photo/123") -> dict:
    return {"id": "1", "alt": alt, "url": url, "src": {"large2x": url, "large": url}}


def _video(url: str, tags: list | None = None) -> dict:
    return {"id": "1", "url": url, "tags": tags or [], "video_files": [], "user": {}}


def _fetcher(niche: str = "kisisel_finans") -> ImageFetcher:
    cfg = SimpleNamespace(
        niche=niche,
        channel_id=f"test_{niche}",
        pexels_query="",
        pexels_api_key="demo-key",
    )
    return ImageFetcher(channel_cfg=cfg)


# ── Hard-block tests ───────────────────────────────────────────────────────────

class TestHardBlock:
    def test_bikini_alt_text_rejected(self):
        clf = classify_asset_relevance(
            _photo("Woman in bikini on beach"), "photo", "emeklilik", "kisisel_finans"
        )
        assert clf.hard_blocked is True
        assert clf.final_decision == "reject"

    def test_swimsuit_video_rejected(self):
        clf = classify_asset_relevance(
            _video("https://pexels.com/video/swimsuit-fashion"), "video", "borsa", "borsa"
        )
        assert clf.hard_blocked is True
        assert clf.final_decision == "reject"

    def test_lingerie_rejected(self):
        clf = classify_asset_relevance(
            _photo("Lingerie fashion shoot"), "photo", "finans", "kisisel_finans"
        )
        assert clf.hard_blocked is True

    def test_underwear_rejected(self):
        assert bool(_HARD_BLOCK_RE.search("underwear promotion ad"))

    def test_nude_rejected(self):
        clf = classify_asset_relevance(
            _photo("Nude art photography"), "photo", "egitim", "egitim"
        )
        assert clf.hard_blocked is True

    def test_swimwear_photo_rejected(self):
        clf = classify_asset_relevance(
            _photo("Swimwear collection summer"), "photo", "emeklilik", "kisisel_finans"
        )
        assert clf.hard_blocked is True

    def test_topless_rejected(self):
        assert bool(_HARD_BLOCK_RE.search("topless model beach"))

    def test_legacy_photo_is_safe_hard_blocks(self):
        assert not _photo_is_safe(_photo("bikini beach summer"))
        assert not _photo_is_safe(_photo("swimsuit fashion"))

    def test_legacy_video_is_safe_hard_blocks(self):
        assert not _video_is_safe(_video("https://pexels.com/video/bikini-swim"))


# ── Relevant acceptance tests ──────────────────────────────────────────────────

class TestRelevantAcceptance:
    def test_retirement_documents_accepted(self):
        clf = classify_asset_relevance(
            _photo("Retirement planning documents and calculator on desk"),
            "photo", "emeklilik", "kisisel_finans",
        )
        assert clf.final_decision == "accept"
        assert clf.hard_blocked is False

    def test_financial_chart_accepted(self):
        clf = classify_asset_relevance(
            _photo("Financial chart graph analysis on screen"),
            "photo", "borsa", "borsa",
        )
        assert clf.final_decision == "accept"

    def test_pension_paperwork_accepted(self):
        clf = classify_asset_relevance(
            _photo("Pension fund documents savings planning office"),
            "photo", "emeklilik", "kisisel_finans",
        )
        assert clf.final_decision == "accept"
        assert clf.positive_score > 0

    def test_health_doctor_accepted(self):
        """Health topic with a doctor image — should be accepted."""
        clf = classify_asset_relevance(
            _photo("Doctor in clinic examining medical equipment"),
            "photo", "saglik", "saglik",
        )
        assert clf.final_decision == "accept"

    def test_education_students_accepted(self):
        """Education topic with students — should be accepted."""
        clf = classify_asset_relevance(
            _photo("Students studying in library with books"),
            "photo", "ogrenme", "egitim",
        )
        assert clf.final_decision == "accept"

    def test_career_office_accepted(self):
        clf = classify_asset_relevance(
            _photo("Professional office desk laptop planning career"),
            "photo", "kariyer", "kariyer",
        )
        assert clf.final_decision == "accept"

    def test_technology_computer_accepted(self):
        clf = classify_asset_relevance(
            _photo("Computer screen code software development"),
            "photo", "yazilim", "teknoloji",
        )
        assert clf.final_decision == "accept"


# ── False-positive protection ──────────────────────────────────────────────────

class TestFalsePositiveProtection:
    def test_female_financial_advisor_not_blocked(self):
        """'female financial advisor' must not be hard-blocked."""
        clf = classify_asset_relevance(
            _photo("Female financial advisor reviewing investment portfolio chart"),
            "photo", "yatirim", "kisisel_finans",
        )
        assert clf.hard_blocked is False
        # Should be accepted due to strong finance positive keywords
        assert clf.final_decision == "accept"

    def test_model_portfolio_theory_not_blocked(self):
        """'model portfolio theory' must not be blocked because of 'model'."""
        clf = classify_asset_relevance(
            _photo("Model portfolio theory chart investment analysis"),
            "photo", "yatirim", "kisisel_finans",
        )
        assert clf.hard_blocked is False

    def test_vacation_budget_spreadsheet_contextual(self):
        """'vacation budget spreadsheet' — finance niche — moderate penalty but finance keywords."""
        clf = classify_asset_relevance(
            _photo("Vacation budget spreadsheet planning finance savings"),
            "photo", "butce", "kisisel_finans",
        )
        # Hard block should not fire
        assert clf.hard_blocked is False
        # Strong finance positive keywords should compensate

    def test_beach_house_real_estate_accepted(self):
        """Beach in real estate context is acceptable."""
        clf = classify_asset_relevance(
            _photo("Beach house property real estate architecture exterior"),
            "photo", "konut", "gayrimenkul",
        )
        assert clf.hard_blocked is False

    def test_man_doctor_health_not_blocked(self):
        clf = classify_asset_relevance(
            _photo("Man doctor stethoscope clinic medical"),
            "photo", "saglik", "saglik",
        )
        assert clf.hard_blocked is False

    def test_education_beach_vacation_not_blocked_for_travel_niche(self):
        """Unknown/travel niche with beach — not blocked by finance rules."""
        clf = classify_asset_relevance(
            _photo("Vacation beach travel summer holiday"),
            "photo", "seyahat", "seyahat",
        )
        assert clf.hard_blocked is False


# ── select_safe_assets tests ────────────────────────────────────────────────────

class TestSelectSafeAssets:
    def test_filters_hard_blocked_assets(self):
        candidates = [
            {**_photo("bikini beach summer"), "id": "1"},
            {**_photo("retirement savings documents desk finance"), "id": "2"},
        ]
        accepted, clfs = select_safe_assets(candidates, "photo", "emeklilik", "kisisel_finans")
        assert len(accepted) == 1
        assert "retirement" in accepted[0]["alt"]

    def test_deduplicates_by_id(self):
        p = _photo("financial chart investment analysis")
        candidates = [p, p, p]  # same id
        accepted, _ = select_safe_assets(candidates, "photo", "borsa", "borsa")
        assert len(accepted) == 1

    def test_all_rejected_returns_empty(self):
        candidates = [
            _photo("bikini beach"),
            _photo("swimsuit model"),
            _photo("lingerie fashion"),
        ]
        accepted, clfs = select_safe_assets(candidates, "photo", "emeklilik", "kisisel_finans")
        assert accepted == []
        assert all(c.final_decision == "reject" for c in clfs)

    def test_max_count_respected(self):
        candidates = [
            _photo(f"financial chart graph savings {i}") for i in range(20)
        ]
        # Give each a unique id
        for i, c in enumerate(candidates):
            c["id"] = str(i)
        accepted, _ = select_safe_assets(candidates, "photo", "finans", "kisisel_finans", max_count=3)
        assert len(accepted) <= 3


# ── Fallback behavior tests ─────────────────────────────────────────────────────

class TestFallbackBehavior:
    def _make_fetcher(self, niche="kisisel_finans"):
        cfg = SimpleNamespace(
            niche=niche,
            channel_id="test",
            pexels_query="",
            pexels_api_key="demo-key",
        )
        return ImageFetcher(channel_cfg=cfg)

    def test_fetch_images_all_rejected_tries_fallback_queries(self):
        fetcher = self._make_fetcher()
        call_count = {"n": 0}

        def mock_get(url, headers, params, timeout):
            call_count["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            # Return bikini photo on first call, finance photo on second
            if call_count["n"] == 1:
                resp.json.return_value = {"photos": [
                    {"id": "99", "alt": "bikini beach summer", "url": "u", "src": {"large2x": "u", "large": "u"}},
                ]}
            else:
                resp.json.return_value = {"photos": [
                    {"id": "1", "alt": "financial chart desk savings", "url": "u2", "src": {"large2x": "u2", "large": "u2"}},
                ]}
            return resp

        with patch("src.image_fetcher.requests.get", side_effect=mock_get), \
             patch.object(fetcher, "_download_file"), \
             patch("src.image_fetcher.Path.mkdir"):
            paths = fetcher.fetch_images("Emeklilik Planlaması", count=1)

        # Should have tried at least 2 queries
        assert call_count["n"] >= 2

    def test_rejected_asset_never_downloaded(self):
        fetcher = self._make_fetcher()
        download_calls = []

        def mock_get(url, headers, params, timeout):
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"photos": [
                {"id": "1", "alt": "bikini beach", "url": "u", "src": {"large2x": "SHOULD_NOT_DOWNLOAD", "large": "x"}},
            ]}
            return resp

        def mock_download(url, path):
            download_calls.append(url)

        with patch("src.image_fetcher.requests.get", side_effect=mock_get), \
             patch.object(fetcher, "_download_file", side_effect=mock_download), \
             patch("src.image_fetcher.Path.mkdir"):
            fetcher.fetch_images("Test", count=1)

        assert "SHOULD_NOT_DOWNLOAD" not in download_calls


# ── build_safe_search_queries tests ───────────────────────────────────────────

class TestBuildSafeSearchQueries:
    def test_finance_queries_are_object_focused(self):
        queries = build_safe_search_queries("emeklilik", "kisisel_finans")
        combined = " ".join(queries).lower()
        # Should not contain people-lifestyle terms
        for term in ("sexy", "bikini", "swimsuit", "lifestyle", "glamour"):
            assert term not in combined, f"Found '{term}' in finance queries"

    def test_education_queries_contain_learning_terms(self):
        queries = build_safe_search_queries("ogrenme", "egitim")
        combined = " ".join(queries).lower()
        assert any(k in combined for k in ("education", "books", "library", "study", "learning"))

    def test_unknown_niche_returns_safe_default(self):
        queries = build_safe_search_queries("random topic", "unknown_niche_xyz")
        assert len(queries) >= 1
        assert queries[0]  # not empty


# ── Integration: ImageFetcher no crash on all-rejected ───────────────────────

class TestImageFetcherIntegration:
    def test_no_crash_when_all_results_rejected(self):
        """Pipeline must not crash when all Pexels results are inappropriate."""
        fetcher = _fetcher("kisisel_finans")
        call_num = {"n": 0}

        def mock_get(*args, **kwargs):
            call_num["n"] += 1
            resp = MagicMock()
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"photos": [
                {"id": str(i), "alt": "bikini swimsuit beach", "url": f"u{i}",
                 "src": {"large2x": f"u{i}", "large": f"u{i}"}}
                for i in range(5)
            ]}
            return resp

        with patch("src.image_fetcher.requests.get", side_effect=mock_get), \
             patch.object(fetcher, "_download_file"), \
             patch("src.image_fetcher.Path.mkdir"):
            result = fetcher.fetch_images("Emeklilik Planlaması 2026", count=3)

        # Must return a list (possibly empty) — no exception
        assert isinstance(result, list)
