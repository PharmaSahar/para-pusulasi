from __future__ import annotations

from src.chapter_validator import chapter_entries_from_description, validate_and_fix_chapters


def test_valid_chapter_block_stays_unchanged():
    text = """Aciklama satiri

⏱️ BOLUMLER:
00:00 Giris
00:20 Temel Kavramlar
00:40 Ornekler
01:00 Ozet"""
    result = validate_and_fix_chapters(text, video_duration_seconds=80)

    assert result["valid_before"] is True
    assert result["valid_after"] is True
    assert result["auto_fix_actions"] == []
    assert result["schema_version"] == "2.0"
    assert result["validator_version"] == "1.1.0"
    assert result["normalized_description"].strip() == text.strip()


def test_short_segments_are_merged():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:05 Kisa
00:20 Devam
00:40 Ozet"""
    result = validate_and_fix_chapters(text, video_duration_seconds=80)

    assert "merge_short_segments" in result["auto_fix_actions"]
    secs = [item["seconds"] for item in result["final_chapters"]]
    assert all((secs[i + 1] - secs[i]) >= 10 for i in range(len(secs) - 1))


def test_cta_chapter_removed():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:20 Analiz
00:40 Abone Ol
01:00 Sonuc"""
    result = validate_and_fix_chapters(text, video_duration_seconds=90)

    titles = [item["title"].lower() for item in result["final_chapters"]]
    assert all("abone" not in title for title in titles)
    assert all("sonuc" not in title for title in titles)
    assert result["cta_removed_count"] >= 1


def test_ending_guard_drops_near_end_chapter():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:20 Analiz
01:15 Kapanis"""
    result = validate_and_fix_chapters(text, video_duration_seconds=80)

    assert result["ending_guard_pass"] is False
    assert all(item["seconds"] <= 70 for item in result["final_chapters"])


def test_duplicate_timestamp_removed():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:20 Analiz
00:20 Tekrar
00:40 Ozet"""
    result = validate_and_fix_chapters(text, video_duration_seconds=90)

    secs = [item["seconds"] for item in result["final_chapters"]]
    assert len(secs) == len(set(secs))
    assert "remove_duplicate_timestamps" in result["auto_fix_actions"]
    assert result["duplicate_removed_count"] >= 1


def test_unsorted_timestamp_sorted():
    text = """Aciklama

BOLUMLER:
00:20 Analiz
00:00 Giris
00:40 Ozet"""
    result = validate_and_fix_chapters(text, video_duration_seconds=90)

    secs = [item["seconds"] for item in result["final_chapters"]]
    assert secs == sorted(secs)
    assert "sort_timestamps" in result["auto_fix_actions"]


def test_timestamp_beyond_duration_dropped():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:20 Analiz
01:50 Fazla"""
    result = validate_and_fix_chapters(text, video_duration_seconds=80)

    assert all(item["seconds"] <= 80 for item in result["final_chapters"])
    assert "drop_beyond_duration" in result["auto_fix_actions"]


def test_missing_start_00_00_is_added():
    text = """Aciklama

BOLUMLER:
00:20 Analiz
00:40 Ozet
01:00 Kapanis"""
    result = validate_and_fix_chapters(text, video_duration_seconds=100)

    assert result["final_chapters"][0]["seconds"] == 0
    assert "add_start_00_00" in result["auto_fix_actions"]


def test_shorts_bypass_enabled():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:10 Analiz"""
    result = validate_and_fix_chapters(text, video_duration_seconds=30, is_short=True)

    assert result["shorts_bypassed"] is True
    assert result["final_chapters"] == []


def test_unknown_duration_fail_open_no_destructive_fix():
    text = """Aciklama

BOLUMLER:
00:00 Giris
00:05 Kisa
00:20 Analiz"""
    result = validate_and_fix_chapters(text, video_duration_seconds=None)

    assert "CH008" in result["issue_codes"]
    assert any(item["seconds"] == 5 for item in result["final_chapters"])


def test_description_prose_is_preserved():
    prose = "Bu videoda stratejiyi adim adim anlatiyoruz."
    text = f"{prose}\n\nBOLUMLER:\n00:00 Giris\n00:20 Analiz\n00:40 Ozet"
    result = validate_and_fix_chapters(text, video_duration_seconds=80)

    assert prose in result["normalized_description"]


def test_validator_idempotent_second_pass():
    text = """Aciklama

BOLUMLER:
00:20 Analiz
00:00 Giris
00:05 Kisa
00:40 Takip Et"""
    once = validate_and_fix_chapters(text, video_duration_seconds=90)
    twice = validate_and_fix_chapters(once["normalized_description"], video_duration_seconds=90)

    assert once["normalized_description"] == twice["normalized_description"]


def test_chapter_entries_extract_only_timestamp_lines():
    entries = chapter_entries_from_description("Metin\n00:00 Giris\nAra\n00:12 Devam")

    assert [item["seconds"] for item in entries] == [0, 12]
