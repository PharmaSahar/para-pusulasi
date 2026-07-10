from src.metadata_repair import (
    build_normalized_description,
    build_duration_safe_chapters,
    chapter_rule_ok,
    ensure_minimum_tags,
    normalize_metadata,
    parse_iso8601_duration_seconds,
    strip_existing_chapters,
)
from src.chapter_validator import validate_and_fix_chapters


def test_parse_iso8601_duration_seconds_basic():
    assert parse_iso8601_duration_seconds("PT12M34S") == 754
    assert parse_iso8601_duration_seconds("PT1H2M3S") == 3723
    assert parse_iso8601_duration_seconds("P1DT2H") == 93600


def test_strip_existing_chapters_removes_timestamp_lines():
    raw = """Baslik satiri\n\nBOLUMLER:\n00:00 Giris\n00:05 Kisa\n00:30 Devam\n\nEk aciklama"""
    out = strip_existing_chapters(raw)
    assert "BOLUMLER" not in out
    assert "00:00" not in out
    assert "Ek aciklama" in out


def test_build_duration_safe_chapters_have_min_gap_10_seconds():
    chapters = build_duration_safe_chapters(720)
    assert len(chapters) >= 3
    seconds = [sec for sec, _title in chapters]
    assert seconds[0] == 0
    assert all((seconds[i + 1] - seconds[i]) >= 10 for i in range(len(seconds) - 1))


def test_ensure_minimum_tags_backfills_when_missing():
    tags = ensure_minimum_tags(title="Borsa 2026 risk yonetimi", tags=["borsa"], niche="borsa", min_tags=8)
    assert len(tags) >= 8
    assert "borsa" in [t.lower() for t in tags]


def test_normalize_metadata_improves_chapter_and_seo_signals():
    original = """Kisa aciklama\n\nBOLUMLER:\n00:00 Giris\n00:05 Hizli gecis\n00:08 Son"""
    normalized = normalize_metadata(
        title="Risk yonetimi rehberi 2026",
        description=original,
        tags=["risk"],
        duration_sec=900,
        niche="kisisel_finans",
        min_tags=8,
        min_seo=60,
    )

    ok, chapter_count, min_gap_ok = chapter_rule_ok(normalized.description)
    assert ok is True
    assert chapter_count >= 3
    assert min_gap_ok is True
    assert len(normalized.tags) >= 8
    assert normalized.assessment.seo_score_after >= normalized.assessment.seo_score_before


def test_metadata_repair_output_matches_shared_chapter_validator_contract():
    description = build_normalized_description(
        title="Risk yonetimi rehberi",
        base_description="Aciklama\n\nBOLUMLER:\n00:00 Giris\n00:04 Kisa\n00:09 Outro",
        tags=["risk", "yonetim", "borsa", "egitim", "strateji", "finans", "analiz", "plan"],
        duration_sec=130,
    )

    result = validate_and_fix_chapters(
        description=description,
        video_duration_seconds=130,
        is_short=False,
    )

    assert result["valid_after"] is True
    assert result["auto_fix_actions"] == []
