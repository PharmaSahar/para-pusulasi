from __future__ import annotations

from src.studio_analytics_learning_bridge import (
    build_advisory_recommendations,
    build_baselines,
    build_review_payloads,
    derive_learning_signals,
)


def _mk(
    *,
    rid: str,
    ctype: str,
    ctr: float,
    apv: float,
    r30: float,
    search: float,
    browse: float,
    suggested: float,
    swipe: float,
    viewed_ratio: float,
    cards: float,
    card_rate: float,
    end_impr: float,
    end_rate: float,
    playlist_watch: float,
    subs_gained: float,
    views: float,
    join_outcome: str,
) -> dict:
    return {
        "schema_version": "v1",
        "analytics_record_id": rid,
        "provider": "StudioExportProvider",
        "source_file_hash": "h",
        "source_row_number": 2,
        "canonical_channel_id": "chan_1",
        "content_id": f"content_{rid}",
        "youtube_video_id": f"video_{rid}",
        "content_type": ctype,
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
        "imported_at": "2026-07-14T00:00:00+00:00",
        "metrics_version": "v1",
        "provenance": {"join_outcome": join_outcome},
        "advisory_only": True,
        "pipeline_output_changed": False,
        "metrics": {
            "impressions_ctr": {"state": "OBSERVED", "value": ctr},
            "average_percentage_viewed": {"state": "OBSERVED", "value": apv},
            "first_30_second_retention": {"state": "OBSERVED", "value": r30},
            "youtube_search": {"state": "OBSERVED", "value": search},
            "browse_features": {"state": "OBSERVED", "value": browse},
            "suggested_videos": {"state": "OBSERVED", "value": suggested},
            "swiped_away": {"state": "OBSERVED", "value": swipe},
            "viewed_vs_swiped_away": {"state": "OBSERVED", "value": viewed_ratio},
            "cards_shown": {"state": "OBSERVED", "value": cards},
            "card_click_rate": {"state": "OBSERVED", "value": card_rate},
            "end_screen_impressions": {"state": "OBSERVED", "value": end_impr},
            "end_screen_click_rate": {"state": "OBSERVED", "value": end_rate},
            "playlist_watch_time": {"state": "OBSERVED", "value": playlist_watch},
            "subscribers_gained": {"state": "OBSERVED", "value": subs_gained},
            "views": {"state": "OBSERVED", "value": views},
        },
    }


def test_20_local_evidence_scenarios() -> None:
    rows = [
        _mk(rid="1", ctype="LONG_FORM", ctr=0.07, apv=0.65, r30=0.55, search=0.2, browse=0.2, suggested=0.2, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=30, views=1000, join_outcome="LINKED"),
        _mk(rid="2", ctype="LONG_FORM", ctr=0.02, apv=0.65, r30=0.50, search=0.2, browse=0.2, suggested=0.2, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=2, views=1000, join_outcome="LINKED"),
        _mk(rid="3", ctype="LONG_FORM", ctr=0.09, apv=0.20, r30=0.20, search=0.2, browse=0.2, suggested=0.2, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=2, views=1000, join_outcome="LINKED"),
        _mk(rid="4", ctype="LONG_FORM", ctr=0.02, apv=0.20, r30=0.25, search=0.2, browse=0.2, suggested=0.2, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=1, views=1000, join_outcome="LINKED"),
        _mk(rid="5", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.5, browse=0.1, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="6", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.1, browse=0.5, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="7", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.02, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="8", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.30, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="9", ctype="SHORT", ctr=0.04, apv=0.45, r30=0.35, search=0.1, browse=0.1, suggested=0.1, swipe=0.8, viewed_ratio=0.2, cards=0, card_rate=0.0, end_impr=0, end_rate=0.0, playlist_watch=0, subs_gained=1, views=500, join_outcome="LINKED"),
        _mk(rid="10", ctype="SHORT", ctr=0.04, apv=0.65, r30=0.45, search=0.1, browse=0.1, suggested=0.1, swipe=0.2, viewed_ratio=0.8, cards=0, card_rate=0.0, end_impr=0, end_rate=0.0, playlist_watch=0, subs_gained=2, views=500, join_outcome="LINKED"),
        _mk(rid="11", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.005, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="12", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.005, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="13", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=5, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="14", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=40, views=1000, join_outcome="LINKED"),
        _mk(rid="15", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=1, views=1000, join_outcome="LINKED"),
        _mk(rid="16", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="UNRESOLVED"),
        _mk(rid="17", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="LINKED"),
        _mk(rid="18", ctype="LONG_FORM", ctr=0.05, apv=0.50, r30=0.40, search=0.2, browse=0.2, suggested=0.1, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=1000, join_outcome="INVALID"),
        _mk(rid="19", ctype="SHORT", ctr=0.06, apv=0.55, r30=0.42, search=0.1, browse=0.2, suggested=0.12, swipe=0.25, viewed_ratio=0.65, cards=0, card_rate=0.0, end_impr=0, end_rate=0.0, playlist_watch=0, subs_gained=4, views=700, join_outcome="LINKED"),
        _mk(rid="20", ctype="LONG_FORM", ctr=0.05, apv=0.52, r30=0.44, search=0.15, browse=0.20, suggested=0.11, swipe=0.1, viewed_ratio=0.8, cards=200, card_rate=0.02, end_impr=200, end_rate=0.02, playlist_watch=0, subs_gained=3, views=900, join_outcome="LINKED"),
    ]

    baselines = build_baselines(rows)
    signals = derive_learning_signals(rows=rows, baselines=baselines)
    recs = build_advisory_recommendations(signals=signals)
    payloads = build_review_payloads(signals=signals, recommendations=recs)

    assert len(rows) == 20
    assert len(signals) > 0
    assert len(recs) == len(signals)
    assert len(payloads) == len(signals)

    kinds = {s["signal_type"] for s in signals}
    assert "SHORTS_HIGH_SWIPE_AWAY" in kinds
    assert "PLAYLIST_OPPORTUNITY" in kinds
    assert "CARD_UNDERPERFORMANCE" in kinds
    assert "END_SCREEN_UNDERPERFORMANCE" in kinds
    assert all(r["advisory_only"] is True for r in recs)
    assert all(r["applied"] is False for r in recs)
