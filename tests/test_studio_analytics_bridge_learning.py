from __future__ import annotations

from src.studio_analytics_learning_bridge import build_baselines, derive_learning_signals


def _record(*, cid: str, ctype: str, ctr: float, apv: float, r30: float, search: float, browse: float, suggested: float, swipe: float, viewed_ratio: float) -> dict:
    return {
        "schema_version": "v1",
        "analytics_record_id": f"car_{cid}_{ctr}",
        "provider": "StudioExportProvider",
        "source_file_hash": "hash",
        "source_row_number": 1,
        "canonical_channel_id": "chan_1",
        "content_id": cid,
        "youtube_video_id": f"vid_{cid}",
        "content_type": ctype,
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
        "imported_at": "2026-07-14T00:00:00+00:00",
        "metrics_version": "v1",
        "provenance": {"join_outcome": "LINKED"},
        "advisory_only": True,
        "pipeline_output_changed": False,
        "metrics": {
            "impressions_ctr": {"state": "OBSERVED", "value": ctr, "raw_name": "ctr"},
            "average_percentage_viewed": {"state": "OBSERVED", "value": apv, "raw_name": "apv"},
            "first_30_second_retention": {"state": "OBSERVED", "value": r30, "raw_name": "r30"},
            "youtube_search": {"state": "OBSERVED", "value": search, "raw_name": "search"},
            "browse_features": {"state": "OBSERVED", "value": browse, "raw_name": "browse"},
            "suggested_videos": {"state": "OBSERVED", "value": suggested, "raw_name": "suggested"},
            "swiped_away": {"state": "OBSERVED", "value": swipe, "raw_name": "swipe"},
            "viewed_vs_swiped_away": {"state": "OBSERVED", "value": viewed_ratio, "raw_name": "viewed_ratio"},
            "cards_shown": {"state": "OBSERVED", "value": 200, "raw_name": "cards"},
            "card_click_rate": {"state": "OBSERVED", "value": 0.005, "raw_name": "card_rate"},
            "end_screen_impressions": {"state": "OBSERVED", "value": 250, "raw_name": "end_impr"},
            "end_screen_click_rate": {"state": "OBSERVED", "value": 0.006, "raw_name": "end_rate"},
            "playlist_watch_time": {"state": "OBSERVED", "value": 12, "raw_name": "playlist"},
            "subscribers_gained": {"state": "OBSERVED", "value": 30, "raw_name": "subs"},
            "views": {"state": "OBSERVED", "value": 1000, "raw_name": "views"},
        },
    }


def test_learning_signal_generation_core_patterns() -> None:
    rows = [
        _record(cid="a", ctype="LONG_FORM", ctr=0.03, apv=0.60, r30=0.50, search=0.40, browse=0.10, suggested=0.03, swipe=0.20, viewed_ratio=0.80),
        _record(cid="b", ctype="LONG_FORM", ctr=0.08, apv=0.20, r30=0.20, search=0.05, browse=0.30, suggested=0.30, swipe=0.10, viewed_ratio=0.90),
        _record(cid="c", ctype="LONG_FORM", ctr=0.06, apv=0.45, r30=0.40, search=0.10, browse=0.15, suggested=0.10, swipe=0.10, viewed_ratio=0.60),
        _record(cid="s1", ctype="SHORT", ctr=0.05, apv=0.50, r30=0.30, search=0.10, browse=0.10, suggested=0.10, swipe=0.70, viewed_ratio=0.20),
        _record(cid="s2", ctype="SHORT", ctr=0.05, apv=0.55, r30=0.45, search=0.10, browse=0.10, suggested=0.10, swipe=0.20, viewed_ratio=0.80),
        _record(cid="s3", ctype="SHORT", ctr=0.04, apv=0.50, r30=0.40, search=0.10, browse=0.10, suggested=0.10, swipe=0.30, viewed_ratio=0.70),
    ]

    baselines = build_baselines(rows)
    signals = derive_learning_signals(rows=rows, baselines=baselines)
    kinds = {s["signal_type"] for s in signals}

    assert "LOW_CTR_HIGH_RETENTION" in kinds
    assert "HIGH_CTR_LOW_RETENTION" in kinds
    assert "EARLY_RETENTION_DROP" in kinds
    assert "STRONG_SEARCH_WEAK_BROWSE" in kinds
    assert "STRONG_BROWSE_WEAK_SEARCH" in kinds
    assert "WEAK_SUGGESTED_TRAFFIC" in kinds
    assert "STRONG_SUGGESTED_TRAFFIC" in kinds
    assert "SHORTS_HIGH_SWIPE_AWAY" in kinds
    assert "SHORTS_STRONG_HOOK" in kinds
    assert "CARD_UNDERPERFORMANCE" in kinds
    assert "END_SCREEN_UNDERPERFORMANCE" in kinds
    assert "PLAYLIST_OPPORTUNITY" in kinds
    assert "SUBSCRIBER_CONVERSION_STRENGTH" in kinds


def test_insufficient_data_signal() -> None:
    rows = [_record(cid="x", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.1, browse=0.1, suggested=0.1, swipe=0.1, viewed_ratio=0.5)]
    baselines = build_baselines(rows)
    signals = derive_learning_signals(rows=rows, baselines=baselines)
    assert any(s["signal_type"] == "INSUFFICIENT_DATA" for s in signals)
