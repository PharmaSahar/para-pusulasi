from __future__ import annotations

from src.studio_analytics_learning_bridge import build_advisory_recommendations, build_review_payloads


def test_review_payload_contract() -> None:
    signal = {
        "signal_id": "sig_1",
        "channel_id": "chan_1",
        "content_id": "content_1",
        "youtube_video_id": "vid_1",
        "content_type": "LONG_FORM",
        "metric_window": "daily",
        "signal_type": "LOW_CTR_HIGH_RETENTION",
        "evidence_metrics": {"ctr": 0.03, "apv": 0.6},
        "confidence": 0.7,
        "explanation": "explain",
        "affected_component": "title_thumbnail_discovery",
        "recommended_future_action": "review packaging",
        "advisory_only": True,
        "created_at": "2026-07-14T00:00:00+00:00",
        "supporting_metrics": {"ctr": 0.03},
        "alternative_explanations": ["seasonality"],
        "data_limitations": ["small sample"],
    }

    recs = build_advisory_recommendations(signals=[signal])
    payloads = build_review_payloads(signals=[signal], recommendations=recs)

    assert len(payloads) == 1
    p = payloads[0]
    assert p["advisory_only"] is True
    assert p["pipeline_output_changed"] is False
    assert p["auto_submit"] is False
    assert p["signal"]["signal_id"] == "sig_1"
