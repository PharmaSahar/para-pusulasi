from __future__ import annotations

from src.studio_analytics_learning_bridge import build_baselines


def _row(channel: str, ctype: str, ctr: float, apv: float) -> dict:
    return {
        "canonical_channel_id": channel,
        "content_type": ctype,
        "metrics": {
            "impressions_ctr": {"state": "OBSERVED", "value": ctr},
            "average_percentage_viewed": {"state": "OBSERVED", "value": apv},
        },
    }


def test_baselines_per_channel_and_type() -> None:
    rows = [
        _row("chan_1", "LONG_FORM", 0.04, 0.45),
        _row("chan_1", "LONG_FORM", 0.06, 0.55),
        _row("chan_1", "SHORT", 0.08, 0.60),
        _row("chan_2", "LONG_FORM", 0.03, 0.35),
    ]
    baselines = build_baselines(rows)

    assert "chan_1::LONG_FORM" in baselines
    assert "chan_1::SHORT" in baselines
    assert "chan_2::LONG_FORM" in baselines

    lf = baselines["chan_1::LONG_FORM"]
    assert lf["sample_count"] == 2
    assert lf["ctr_median"] == 0.05
    assert lf["apv_median"] == 0.5
