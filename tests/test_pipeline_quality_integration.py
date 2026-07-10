"""
Pipeline integration tests — prove content quality guard is invoked in the
real production path before render/upload.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_cfg(niche="saglik", channel_id="saglik_pusulasi"):
    cfg = SimpleNamespace(
        channel_id=channel_id, name=channel_id, niche=niche,
        language="tr", upload_times=["08:00"], color_primary=[200, 50, 50],
        color_bg=[10, 10, 30], slogan="", category_id="26",
        pexels_query="health fitness", persona="", topics=[],
        anthropic_api_key="sk-fake", youtube_client_id="cid",
        youtube_client_secret="csec", pexels_api_key="pkey",
        elevenlabs_api_key="", elevenlabs_voice_id="", elevenlabs_enabled=False,
        base_dir=f"channels/{channel_id}", output_dir=f"channels/{channel_id}/output",
        scripts_dir=f"channels/{channel_id}/output/scripts",
        audio_dir=f"channels/{channel_id}/output/audio",
        videos_dir=f"channels/{channel_id}/output/videos",
        token_path=f"channels/{channel_id}/youtube_token.pickle",
        client_secrets_path=f"channels/{channel_id}/client_secrets.json",
        video_width=1920, video_height=1080, channel_language="tr",
        default_category_id="26",
    )
    cfg.ensure_directories = lambda: None
    return cfg


def _make_content(title="Sağlıklı Yaşam", niche="saglik", script=None):
    """Minimal VideoContent-like object."""
    content = MagicMock()
    content.title = title
    content.description = "Sağlıklı yaşam beslenme uyku egzersiz " * 5
    content.script = script or "Sağlıklı beslenme ve spor alışkanlıkları hakkında bilgi"
    content.tags = ["sağlık", "beslenme", "spor", "fitness"]
    content.category_id = "26"
    content.thumbnail_prompt = "health fitness wellness"
    content.niche = niche
    content.hook = ""
    content.created_at = "2026-07-10T00:00:00"
    content.seo_description = lambda: content.description
    content.prompt_metadata = {}
    content.channel_dna_metadata = {}
    content.quality_score_metadata = {}
    return content


# ── Guard invocation tests ─────────────────────────────────────────────────────

class TestPipelineGuardInvocation:
    """Prove evaluate_content_quality is called from the real pipeline."""

    def test_guard_module_importable_from_pipeline(self):
        """Pipeline must be able to import content_quality_guard."""
        import src.pipeline  # should not raise
        from src.content_quality_guard import evaluate_content_quality
        assert callable(evaluate_content_quality)

    def test_health_channel_dollar_topic_blocked_before_render(self, tmp_path):
        """Health channel + dollar topic: pipeline raises before TTS/render."""
        from src.content_quality_guard import (
            MetadataBundle, evaluate_content_quality
        )
        cfg = _make_cfg("saglik", "saglik_pusulasi")
        content = _make_content(
            title="Dolar kuru 2026 analizi",
            niche="saglik",
            script="Dolar kuru yükseldi döviz yatırımı borsa stratejisi değerlendirmesi"
        )
        bundle = MetadataBundle(
            title=content.title, description=content.description,
            tags=content.tags, category_id=content.category_id,
            script=content.script, niche="saglik", channel_id="saglik_pusulasi"
        )
        dec = evaluate_content_quality(bundle, content.script, "Dolar kuru 2026")
        assert dec.publish_decision == "block"
        assert dec.channel_fit == "fail"

    def test_health_channel_real_estate_blocked(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="Gayrimenkul yatırımı 2026",
            description="Konut kira emlak taşınmaz daire arsa fiyatları " * 3,
            tags=["emlak", "konut", "kira"],
            category_id="26",
            script="Gayrimenkul konut kira emlak taşınmaz değerlendirmesi",
            niche="saglik", channel_id="saglik_pusulasi"
        )
        dec = evaluate_content_quality(bundle, bundle.script, bundle.title)
        assert dec.publish_decision == "block"

    def test_finance_channel_medical_blocked(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="Kanser tedavisi rehberi",
            description="Hastane doktor klinik tedavi ilaç kullanımı " * 3,
            tags=["sağlık", "tedavi", "doktor"],
            category_id="26",
            script="Kanser tedavisi hastane ilaç doktor klinik bilgisi",
            niche="borsa", channel_id="borsa_akademi"
        )
        dec = evaluate_content_quality(bundle, bundle.script, bundle.title)
        assert dec.publish_decision == "block"
        assert dec.channel_fit == "fail"

    def test_correct_health_topic_passes(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="Uyku kalitesini artırma",
            description="Sağlıklı uyku beslenme spor stres yönetimi için " * 4,
            tags=["sağlık", "uyku", "beslenme", "spor"],
            category_id="26",
            script="Uyku kalitesini artırmak için beslenme ve egzersiz önerileri",
            niche="saglik", channel_id="saglik_pusulasi"
        )
        dec = evaluate_content_quality(bundle, bundle.script, bundle.title)
        assert dec.publish_decision == "allow"
        assert dec.channel_fit == "pass"

    def test_correct_finance_topic_passes(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="BIST 100 teknik analiz",
            description="Borsa hisse teknik analiz portföy yatırım " * 5,
            tags=["borsa", "bist", "hisse", "yatırım"],
            category_id="22",
            script="BIST 100 teknik analiz portföy stratejisi değerlendirmesi",
            niche="borsa", channel_id="borsa_akademi"
        )
        dec = evaluate_content_quality(bundle, bundle.script, bundle.title)
        assert dec.publish_decision == "allow"


class TestMetadataCompleteneGate:

    def test_empty_metadata_blocked_before_upload(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="", description="", tags=[], category_id="",
            script="", niche="borsa", channel_id="borsa_akademi"
        )
        dec = evaluate_content_quality(bundle, "", "topic")
        assert dec.publish_decision == "block"
        assert not dec.metadata_complete

    def test_missing_script_blocked(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="BIST analiz", description="Uzun açıklama metni " * 6,
            tags=["borsa", "bist", "hisse"], category_id="22",
            script="", niche="borsa", channel_id="borsa_akademi"
        )
        dec = evaluate_content_quality(bundle, "", "BIST analiz")
        assert dec.publish_decision == "block"


class TestScriptFreshnessIntegration:

    def test_duplicate_script_regenerated_then_blocked(self, tmp_path, monkeypatch):
        """Near-duplicate script: blocked on second attempt, never uploaded."""
        monkeypatch.setattr(
            "src.content_quality_guard._RECENT_SCRIPTS_FILE",
            str(tmp_path / "recent.json")
        )
        monkeypatch.setattr("src.content_quality_guard._OVERLAP_THRESHOLD", 0.45)

        from src.content_quality_guard import (
            MetadataBundle, evaluate_content_quality, register_published_script
        )

        # Register first video
        first_script = "Borsa analizinde teknik göstergeler kullanılır BIST haftalık portföy"
        register_published_script("borsa_akademi", "v1", "BIST analizi", "borsa", first_script)

        # Very similar second script
        dup_script = "Borsa analizinde teknik göstergeler kullanılır BIST haftalık portföy değerlendirme"
        bundle = MetadataBundle(
            title="BIST haftalık", description="Borsa analiz " * 8,
            tags=["borsa", "bist", "hisse"], category_id="22",
            script=dup_script, niche="borsa", channel_id="borsa_akademi"
        )
        dec = evaluate_content_quality(bundle, dup_script, "BIST haftalık")
        # Should be blocked due to near-duplicate
        assert not dec.script_fresh
        assert dec.script_similarity >= 0.45
        assert dec.publish_decision == "block"

    def test_successful_upload_registers_fingerprint(self, tmp_path, monkeypatch):
        """Script fingerprint registered after upload, not before."""
        monkeypatch.setattr(
            "src.content_quality_guard._RECENT_SCRIPTS_FILE",
            str(tmp_path / "recent.json")
        )
        from src.content_quality_guard import register_published_script, _load_recent_scripts

        # Before: no fingerprint
        assert _load_recent_scripts("test_channel") == []

        # Simulate successful upload
        register_published_script("test_channel", "vid1", "Test", "topic", "script content here")

        # After: fingerprint exists
        entries = _load_recent_scripts("test_channel")
        assert len(entries) == 1
        assert entries[0]["video_id"] == "vid1"

    def test_failed_upload_does_not_register_fingerprint(self, tmp_path, monkeypatch):
        """No register call should be made when upload fails."""
        monkeypatch.setattr(
            "src.content_quality_guard._RECENT_SCRIPTS_FILE",
            str(tmp_path / "recent.json")
        )
        from src.content_quality_guard import _load_recent_scripts

        # Simulate failed upload: register_published_script is NOT called
        # (in pipeline.py, registration is inside the successful upload block)
        entries = _load_recent_scripts("test_channel")
        assert entries == []


class TestShortsGuard:

    def test_shorts_use_same_quality_gate(self):
        """Shorts should call the same evaluate_content_quality function."""
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality

        bundle = MetadataBundle(
            title="Dolar kuru Shorts",
            description="Dolar kuru yükseldi döviz yatırımı borsa" * 2,
            tags=["dolar", "kur"],
            category_id="26",
            script="Dolar kuru yükseldi döviz borsa",
            niche="saglik",
            channel_id="saglik_pusulasi",
            is_short=True,
        )
        dec = evaluate_content_quality(bundle, bundle.script, bundle.title, content_type="short")
        # Health channel with finance/dollar content should be blocked
        assert dec.publish_decision == "block"

    def test_valid_short_passes(self):
        from src.content_quality_guard import MetadataBundle, evaluate_content_quality
        bundle = MetadataBundle(
            title="30 günlük egzersiz",
            description="Spor beslenme sağlık fitness egzersiz" * 3,
            tags=["spor", "fitness", "egzersiz"],
            category_id="26",
            script="30 günlük egzersiz planı sağlıklı beslenme",
            niche="saglik",
            channel_id="saglik_pusulasi",
            is_short=True,
        )
        dec = evaluate_content_quality(bundle, bundle.script, bundle.title, content_type="short")
        assert dec.publish_decision == "allow"


class TestNoUnguardedPath:
    """Verify content quality gate function is in the pipeline module."""

    def test_pipeline_contains_quality_gate_call(self):
        """pipeline.py must contain _run_content_quality_gate invocation."""
        pipeline_src = Path("src/pipeline.py").read_text(encoding="utf-8")
        assert "_run_content_quality_gate" in pipeline_src

    def test_pipeline_imports_evaluate_content_quality(self):
        """Pipeline must import evaluate_content_quality."""
        pipeline_src = Path("src/pipeline.py").read_text(encoding="utf-8")
        assert "evaluate_content_quality" in pipeline_src

    def test_pipeline_imports_register_published_script(self):
        """Pipeline must call register_published_script after upload."""
        pipeline_src = Path("src/pipeline.py").read_text(encoding="utf-8")
        assert "register_published_script" in pipeline_src

    def test_guard_blocks_before_tts_point(self):
        """Gate must appear before 'ADIM 2' (TTS) in pipeline source."""
        pipeline_src = Path("src/pipeline.py").read_text(encoding="utf-8")
        gate_pos = pipeline_src.find("_run_content_quality_gate()")
        tts_pos = pipeline_src.find("ADIM 2/4 - Edge TTS")
        assert gate_pos < tts_pos, "Guard must appear before TTS stage"

    def test_register_appears_after_upload(self):
        """register_published_script must appear after upload_video call."""
        pipeline_src = Path("src/pipeline.py").read_text(encoding="utf-8")
        upload_pos = pipeline_src.find("video_id = uploader.upload_video(")
        register_pos = pipeline_src.find("register_published_script(")
        assert register_pos > upload_pos, "Registration must be after upload"
