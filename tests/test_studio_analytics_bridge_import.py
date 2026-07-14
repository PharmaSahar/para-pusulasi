from __future__ import annotations

from pathlib import Path

from src.studio_analytics_learning_bridge import MetricState, parse_studio_export_file


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_english_headers_parse(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "english.csv",
        "Video ID,Content Type,Date,Views,Impressions CTR\n"
        "abc123,Video,2026-07-10,1200,4.5%\n",
    )
    rows, inv = parse_studio_export_file(f)
    assert inv["rows_kept"] == 1
    assert rows[0]["youtube_video_id"] == "abc123"
    assert rows[0]["content_type"] == "LONG_FORM"
    assert rows[0]["metrics"]["views"]["state"] == MetricState.OBSERVED.value


def test_turkish_headers_parse(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "turkish.csv",
        "Video Kimliği,İçerik Türü,Tarih,İzlenme,Gösterim Tıklama Oranı\n"
        "xyz987,Shorts,10.07.2026,1.250,\"6,5%\"\n",
    )
    rows, inv = parse_studio_export_file(f)
    assert inv["rows_kept"] == 1
    assert rows[0]["youtube_video_id"] == "xyz987"
    assert rows[0]["content_type"] == "SHORT"


def test_comma_decimal_and_percentage(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "comma.csv",
        "Video ID,Date,Average Percentage Viewed,Impressions CTR\n"
        "v1,2026-07-10,62,5%,4,2%\n",
    )
    rows, _ = parse_studio_export_file(f)
    apv = rows[0]["metrics"]["average_percentage_viewed"]
    ctr = rows[0]["metrics"]["impressions_ctr"]
    assert apv["state"] == MetricState.OBSERVED.value
    assert ctr["state"] == MetricState.OBSERVED.value


def test_missing_columns_do_not_become_zero(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "missing.csv",
        "Video ID,Date\n"
        "v2,2026-07-10\n",
    )
    rows, _ = parse_studio_export_file(f)
    assert rows[0]["metrics"]["views"]["state"] == MetricState.UNKNOWN.value
    assert rows[0]["metrics"]["views"]["value"] is None


def test_total_row_excluded(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "totals.csv",
        "Video ID,Title,Date,Views\n"
        ",Total,2026-07-10,10000\n"
        "v3,Normal,2026-07-10,10\n",
    )
    rows, inv = parse_studio_export_file(f)
    assert inv["rows_aggregate_excluded"] == 1
    assert len(rows) == 1
    assert rows[0]["youtube_video_id"] == "v3"


def test_malformed_numeric_becomes_invalid(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "bad.csv",
        "Video ID,Date,Views\n"
        "v4,2026-07-10,not-a-number\n",
    )
    rows, _ = parse_studio_export_file(f)
    assert rows[0]["metrics"]["views"]["state"] == MetricState.INVALID.value


def test_short_and_long_rows(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "mixed.csv",
        "Video ID,Content Type,Date,Views,Shown in Feed\n"
        "v5,Video,2026-07-10,120,\n"
        "v6,Shorts,2026-07-10,200,500\n",
    )
    rows, _ = parse_studio_export_file(f)
    types = {rows[0]["content_type"], rows[1]["content_type"]}
    assert "LONG_FORM" in types
    assert "SHORT" in types
