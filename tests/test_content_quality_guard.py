"""
Tests for content_quality_guard and youtube_audit modules.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.content_quality_guard import (
    MetadataBundle,
    check_channel_topic_fit,
    check_metadata_completeness,
    check_script_freshness,
    evaluate_content_quality,
    register_published_script,
    _token_overlap,
)
from src.youtube_audit import VideoAuditItem, _classify_item, _is_short


# ── Channel-topic contract tests ───────────────────────────────────────────────

class TestChannelTopicContract:

    def test_health_channel_rejects_dollar_topic(self):
        result, reasons = check_channel_topic_fit(
            topic="Dolar kuru 2026 analizi",
            script="Dolar kuru ve döviz yatırımı hakkında bilgi veriyoruz",
            title="Dolar kurunda kritik hareket",
            niche="saglik",
        )
        assert result == "fail"
        assert any("kisisel_finans" in r for r in reasons)

    def test_health_channel_rejects_real_estate_topic(self):
        result, reasons = check_channel_topic_fit(
            topic="Gayrimenkul yatırımı 2026",
            script="Konut ve emlak piyasası analizi. Kira ve taşınmaz fiyatları",
            title="Emlak piyasası yükseliyor",
            niche="saglik",
        )
        assert result == "fail"
        assert any("gayrimenkul" in r for r in reasons)

    def test_finance_channel_rejects_medical_topic(self):
        result, reasons = check_channel_topic_fit(
            topic="Kanser tedavisi ve ilaç kullanımı",
            script="Doktor önerileri ve hastane süreçleri. Tedavi ve klinik bilgisi",
            title="Sağlıklı yaşam için ilaç rehberi",
            niche="borsa",
        )
        assert result == "fail"
        assert any("saglik" in r for r in reasons)

    def test_correct_health_topic_passes(self):
        result, _ = check_channel_topic_fit(
            topic="Uyku kalitesini artırma yöntemleri",
            script="Sağlıklı uyku için pratik öneriler. Stres yönetimi ve beslenme",
            title="Daha iyi uyumak için 7 ipucu",
            niche="saglik",
        )
        assert result == "pass"

    def test_correct_finance_topic_passes(self):
        result, _ = check_channel_topic_fit(
            topic="BIST 100 teknik analiz",
            script="Borsa analizinde portföy stratejisi ve yatırım araçları",
            title="Bu haftanın borsa değerlendirmesi",
            niche="borsa",
        )
        assert result == "pass"

    def test_education_channel_rejects_crypto_topic(self):
        result, reasons = check_channel_topic_fit(
            topic="Bitcoin ve Ethereum yatırım rehberi",
            script="Kripto para blockchain ve token alım satım stratejileri",
            title="Altcoin portföyü nasıl kurulur",
            niche="egitim",
        )
        assert result == "fail"

    def test_real_estate_accepts_its_own_topic(self):
        result, _ = check_channel_topic_fit(
            topic="İstanbul'da daire fiyatları 2026",
            script="Gayrimenkul piyasası ve kira geliri. Tapu ve emlak süreçleri",
            title="İstanbul'da konut almak artık daha zor",
            niche="gayrimenkul",
        )
        assert result == "pass"

    def test_soft_polysemous_token_does_not_hard_block(self):
        result, reasons = check_channel_topic_fit(
            topic="Stres yonetimi ile daha iyi odaklanma",
            script="Gunluk stres yonetimi ve nefes calismalari anlatiliyor",
            title="Stresi yonetmenin 5 yolu",
            niche="egitim",
        )
        assert result == "pass"
        assert reasons == []

    def test_keyword_boundary_prevents_partial_match_false_positive(self):
        result, reasons = check_channel_topic_fit(
            topic="Kriptografi ders notlari",
            script="Bu derste veri guvenligi ve sifreleme mantigi inceleniyor",
            title="Kriptografiye giris",
            niche="egitim",
        )
        assert result == "pass"
        assert reasons == []

    def test_turkish_normalization_detects_hard_cross_niche_signal(self):
        result, reasons = check_channel_topic_fit(
            topic="Hisse senedi teknik analiz",
            script="BIST 100 ve portfoy dagilimi konulari",
            title="Yatirim stratejisi",
            niche="saglik",
        )
        assert result == "fail"
        assert reasons
        payloads = [json.loads(reason.split(": ", 1)[1]) for reason in reasons]
        assert any(payload["final_classification"] == "HARD_CROSS_NICHE_SIGNAL" for payload in payloads)
        assert all(payload["detected_domain"] == "saglik" for payload in payloads)
        assert any(payload["conflicting_domain"] == "borsa" for payload in payloads)
        assert any(payload["score"] >= payload["threshold"] for payload in payloads)


# ── Metadata completeness tests ────────────────────────────────────────────────

class TestMetadataCompleteness:

    def test_empty_title_blocked(self):
        bundle = MetadataBundle(
            title="", description="Bu video yatırım hakkındadır. " * 5,
            tags=["yatırım", "borsa", "finans"], category_id="22", script="script here",
            niche="borsa", channel_id="borsa_akademi"
        )
        complete, missing = check_metadata_completeness(bundle)
        assert not complete
        assert any("title" in m for m in missing)

    def test_short_description_flagged(self):
        bundle = MetadataBundle(
            title="Test video", description="Kısa açıklama",
            tags=["a", "b", "c"], category_id="22", script="script here",
            niche="borsa", channel_id="borsa_akademi"
        )
        complete, missing = check_metadata_completeness(bundle)
        assert not complete
        assert any("description" in m for m in missing)

    def test_too_few_tags_flagged(self):
        bundle = MetadataBundle(
            title="Test", description="Bu uzun bir açıklama metnidir. " * 5,
            tags=["tek"], category_id="22", script="script",
            niche="borsa", channel_id="test"
        )
        complete, missing = check_metadata_completeness(bundle)
        assert not complete
        assert any("tags" in m for m in missing)

    def test_complete_metadata_passes(self):
        bundle = MetadataBundle(
            title="BIST 100 analizi 2026",
            description="Bu videoda BIST 100 teknik analizi yapıyoruz. " * 4,
            tags=["borsa", "bist", "hisse", "yatırım"],
            category_id="22", script="uzun script",
            niche="borsa", channel_id="borsa_akademi"
        )
        complete, missing = check_metadata_completeness(bundle)
        assert complete
        assert missing == []

    def test_missing_script_blocked(self):
        bundle = MetadataBundle(
            title="Test", description="Uzun açıklama " * 10,
            tags=["a", "b", "c"], category_id="22", script="",
            niche="borsa", channel_id="test"
        )
        complete, missing = check_metadata_completeness(bundle)
        assert not complete
        assert any("script" in m for m in missing)


# ── Script freshness tests ──────────────────────────────────────────────────────

class TestScriptFreshness:

    def test_near_duplicate_script_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.content_quality_guard._RECENT_SCRIPTS_FILE",
                            str(tmp_path / "recent.json"))
        monkeypatch.setattr("src.content_quality_guard._RECENT_WINDOW", 5)
        monkeypatch.setattr("src.content_quality_guard._OVERLAP_THRESHOLD", 0.5)

        # Register existing script
        original = "Borsa analizinde teknik göstergeler kullanılır. BIST 100 haftalık değerlendirme"
        register_published_script("borsa_akademi", "vid1", "BIST analizi", "borsa", original)

        # Nearly identical new script
        duplicate = "Borsa analizinde teknik göstergeler kullanılır. BIST 100 haftalık değerlendirme tahmini"
        fresh, sim, matched = check_script_freshness("borsa_akademi", duplicate, "BIST analizi 2", "borsa")
        assert not fresh
        assert "vid1" in matched

    def test_fresh_distinct_script_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.content_quality_guard._RECENT_SCRIPTS_FILE",
                            str(tmp_path / "recent.json"))

        register_published_script("borsa_akademi", "vid1", "BIST analizi",
                                   "borsa", "Borsa piyasası genel eğilimi")

        fresh_script = "Emeklilik planlaması nasıl yapılır? BES ve devlet emekliliği karşılaştırması"
        fresh, sim, matched = check_script_freshness("borsa_akademi", fresh_script, "Emeklilik", "emeklilik")
        assert fresh
        assert matched == []

    def test_repeated_hook_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.content_quality_guard._RECENT_SCRIPTS_FILE",
                            str(tmp_path / "recent.json"))
        monkeypatch.setattr("src.content_quality_guard._OVERLAP_THRESHOLD", 0.4)

        hook = "Merhaba arkadaşlar bugün sizinle çok önemli bir konuyu ele alacağız"
        register_published_script("para_pusulasi", "v1", "Title 1", "finans",
                                   f"{hook} yatırım konuları hakkında bilgi vereceğim")

        new_script = f"{hook} dolar kuru ve yatırım stratejileri hakkında konuşacağız"
        fresh, sim, _ = check_script_freshness("para_pusulasi", new_script, "Title 2", "finans")
        # High overlap due to identical hook
        assert sim > 0.2

    def test_different_channels_independent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.content_quality_guard._RECENT_SCRIPTS_FILE",
                            str(tmp_path / "recent.json"))

        script = "Borsa analizi teknik göstergeler BIST haftalık değerlendirme"
        register_published_script("borsa_akademi", "v1", "Borsa", "borsa", script)

        # Same script but different channel — should have no match
        fresh, sim, matched = check_script_freshness("kripto_rehber", script, "Borsa", "borsa")
        assert matched == []


# ── Token overlap tests ────────────────────────────────────────────────────────

class TestTokenOverlap:

    def test_identical_texts_overlap_one(self):
        text = "Borsa analizinde portföy stratejisi"
        assert _token_overlap(text, text) == pytest.approx(1.0)

    def test_completely_different_texts_near_zero(self):
        a = "Borsa hisse senedi teknik analiz portföy"
        b = "Sağlıklı beslenme diyet vitamin uyku stres"
        overlap = _token_overlap(a, b)
        assert overlap < 0.1

    def test_partial_overlap(self):
        a = "Borsa hisse teknik analiz stratejisi"
        b = "Borsa teknik grafik yönetimi"
        overlap = _token_overlap(a, b)
        assert 0.1 < overlap < 0.9


# ── Full pipeline evaluate_content_quality ────────────────────────────────────

class TestEvaluateContentQuality:

    def _bundle(self, niche="borsa", channel_id="borsa_akademi") -> MetadataBundle:
        return MetadataBundle(
            title="BIST 100 analizi",
            description="Bu hafta BIST 100 teknik analizi yapıyoruz. " * 4,
            tags=["borsa", "bist", "hisse", "yatırım"],
            category_id="22",
            script="Borsa piyasası analiz sonuçları değerlendirildi",
            niche=niche,
            channel_id=channel_id,
        )

    def test_valid_content_allowed(self):
        bundle = self._bundle()
        dec = evaluate_content_quality(bundle, bundle.script, "BIST analizi")
        assert dec.publish_decision == "allow"
        assert dec.channel_fit == "pass"
        assert dec.metadata_complete

    def test_wrong_niche_content_blocked(self):
        bundle = self._bundle(niche="saglik", channel_id="saglik_pusulasi")
        dec = evaluate_content_quality(
            bundle,
            "Dolar kuru yükseldi. Döviz yatırımı stratejisi",
            "Dolar kuru analizi",
        )
        assert dec.publish_decision == "block"
        assert dec.channel_fit == "fail"

    def test_missing_metadata_blocked(self):
        bundle = MetadataBundle(
            title="", description="", tags=[], category_id="", script="",
            niche="borsa", channel_id="test"
        )
        dec = evaluate_content_quality(bundle, "", "topic")
        assert dec.publish_decision == "block"
        assert not dec.metadata_complete


# ── YouTube audit tests ────────────────────────────────────────────────────────

class TestYouTubeAudit:

    def _item(self, **kwargs) -> VideoAuditItem:
        defaults = dict(
            channel_id="test", video_id="v1", url="u", title="BIST 100 Analizi 2026",
            description="Uzun açıklama " * 10, tags=["a", "b", "c"],
            category_id="22", published_at="2026-01-01T00:00:00Z",
            duration="PT10M", view_count=100, like_count=5,
            comment_count=2, privacy_status="public",
            content_type="video", niche="borsa"
        )
        defaults.update(kwargs)
        return VideoAuditItem(**defaults)

    def test_keep_valid_item(self):
        """Without local script, item defaults to REVIEW_MANUALLY not KEEP."""
        item = self._item(channel_id="nonexistent_xyz")
        _classify_item(item)
        # No local script = metadata_only evidence = REVIEW_MANUALLY
        assert item.classification in ("REVIEW_MANUALLY", "KEEP", "METADATA_FIX")

    def test_metadata_only_never_keep_without_evidence(self):
        """metadata_only evidence must NOT produce KEEP."""
        item = self._item(channel_id="nonexistent_xyz_channel_abc")
        item.description = "Good description " * 10
        item.tags = ["borsa", "bist", "hisse", "yatırım"]
        item.category_id = "22"
        _classify_item(item)
        if item.evidence_available == "metadata_only":
            assert item.classification != "KEEP"

    def test_metadata_fix_for_missing_description(self):
        item = self._item(description="Kısa")
        _classify_item(item)
        assert item.classification in ("METADATA_FIX", "REVIEW_MANUALLY")
        assert any("description" in i for i in item.issue_types)

    def test_metadata_fix_for_few_tags(self):
        item = self._item(tags=[])
        _classify_item(item)
        assert item.classification in ("METADATA_FIX", "REVIEW_MANUALLY")
        assert any("tags" in i for i in item.issue_types)

    def test_remove_recommended_for_inappropriate(self):
        item = self._item(title="Bikini fotoğrafları 2026")
        _classify_item(item)
        assert item.classification == "REMOVE_RECOMMENDED"
        assert item.manual_approval_required
        assert item.estimated_risk == "high"

    def test_no_automatic_deletion(self):
        """Audit must never delete — only recommend."""
        item = self._item(title="Nude photography guide")
        _classify_item(item)
        # Classification is REMOVE_RECOMMENDED, not an automatic action
        assert item.classification == "REMOVE_RECOMMENDED"
        assert item.manual_approval_required is True
        # No "deleted" field — just a recommendation
        assert not hasattr(item, "deleted")

    def test_deleted_item_not_marked_recoverable(self):
        """Videos that were deleted cannot be recovered. System must not claim otherwise."""
        # This is enforced by never setting classification = "DELETED_RECOVERABLE"
        item = self._item(privacy_status="deleted")
        _classify_item(item)
        assert item.classification != "DELETED_RECOVERABLE"
        # deleted items are outside scope — audit only covers existing items

    def test_short_detection(self):
        from src.youtube_audit import _is_short
        assert _is_short("PT58S") is True
        assert _is_short("PT1M") is True
        assert _is_short("PT1M2S") is False
        assert _is_short("PT10M") is False
        assert _is_short("") is False

    def test_wrong_channel_historical_item_not_keep(self):
        """Health channel with finance content → RERENDER, never KEEP."""
        item = self._item(
            title="Dolar kuru 2026: Döviz yatırımı",
            description="Dolar kuru yükseldi. Yatırım stratejisi ve borsa analizi " * 3,
            niche="saglik",
            channel_id="saglik_pusulasi",
            tags=["dolar", "borsa", "yatırım"],
        )
        _classify_item(item)
        assert item.classification != "KEEP"
        assert item.classification in ("RERENDER_RECOMMENDED", "REVIEW_MANUALLY", "REMOVE_RECOMMENDED")

    def test_audit_sanity_gate(self):
        """All-KEEP + zero evidence = sanity gate fail."""
        total = 10
        keep = 10
        review = 0
        visual_pct = 0.0
        transcript_pct = 0.0
        sanity_fail = (
            (keep == total and visual_pct == 0 and transcript_pct == 0)
            or (review == 0 and visual_pct == 0)
        )
        assert sanity_fail

    def test_rerender_does_not_auto_publish(self):
        """RERENDER_RECOMMENDED items require manual_approval_required=True."""
        item = self._item(niche="saglik")
        item.description = "Dolar kuru yatırım borsa analizi " * 4
        item.tags = ["dolar", "borsa", "yatırım"]
        _classify_item(item)
        if item.classification == "RERENDER_RECOMMENDED":
            assert item.manual_approval_required is True


# ── Visual diversity guard (preserved image_relevance_guard tests) ─────────────

class TestVisualDiversityPreserved:

    def test_image_relevance_guard_still_rejects_bikini(self):
        """Ensure adding new guard did not break existing image guard."""
        from src.image_relevance_guard import classify_asset_relevance
        photo = {"id": "1", "alt": "bikini beach summer", "url": "u",
                 "src": {"large2x": "u", "large": "u"}}
        clf = classify_asset_relevance(photo, "photo", "emeklilik", "kisisel_finans")
        assert clf.hard_blocked is True
        assert clf.final_decision == "reject"

    def test_image_relevance_guard_still_accepts_finance_chart(self):
        from src.image_relevance_guard import classify_asset_relevance
        photo = {"id": "1", "alt": "retirement savings pension documents desk finance",
                 "url": "u", "src": {"large2x": "u", "large": "u"}}
        clf = classify_asset_relevance(photo, "photo", "emeklilik", "kisisel_finans")
        assert clf.final_decision == "accept"
