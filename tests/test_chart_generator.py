from __future__ import annotations

from pathlib import Path

from src.chart_generator import _coerce_numeric_value, generate_chart


def test_coerce_numeric_value_accepts_plain_number():
    assert _coerce_numeric_value("42") == 42.0


def test_coerce_numeric_value_accepts_percentage():
    assert _coerce_numeric_value("12.5%") == 12.5


def test_coerce_numeric_value_accepts_turkish_decimal_comma():
    assert _coerce_numeric_value("3,75") == 3.75


def test_coerce_numeric_value_rejects_non_numeric_phrase():
    assert _coerce_numeric_value("+3 saat kayıp") is None


def test_generate_chart_skips_invalid_rows_and_continues(tmp_path: Path):
    out = tmp_path / "chart.png"
    chart_data = {
        "type": "bar",
        "title": "Karma Veri",
        "data": {
            "labels": ["A", "B", "C"],
            "values": ["10", "+3 saat kayıp", "20,5"],
        },
    }

    result = generate_chart(chart_data, str(out))

    assert result == str(out)
    assert out.exists()


def test_generate_chart_returns_none_when_all_rows_invalid(tmp_path: Path):
    out = tmp_path / "chart.png"
    chart_data = {
        "type": "line",
        "title": "Geçersiz Veri",
        "data": {
            "labels": ["A", "B"],
            "values": ["+3 saat kayıp", "n/a"],
        },
    }

    result = generate_chart(chart_data, str(out))

    assert result is None
    assert not out.exists()
