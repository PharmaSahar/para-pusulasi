import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_derive_channel_optimization_state_prioritizes_thumbnail_and_retention():
    from src.performance_optimizer import derive_channel_optimization_state

    state = derive_channel_optimization_state(
        [
            {
                "click_through_rate": 0.021,
                "average_view_percentage": 41.0,
                "watch_time_hours": 1.2,
                "thumbnail_attention_score": 58,
                "hook_score": 63,
                "impressions": 900,
            },
            {
                "click_through_rate": 0.032,
                "average_view_percentage": 46.0,
                "watch_time_hours": 1.7,
                "thumbnail_attention_score": 61,
                "hook_score": 67,
                "impressions": 900,
            },
            {
                "click_through_rate": 0.029,
                "average_view_percentage": 44.0,
                "watch_time_hours": 1.5,
                "thumbnail_attention_score": 60,
                "hook_score": 66,
                "impressions": 900,
            },
            {
                "click_through_rate": 0.027,
                "average_view_percentage": 45.0,
                "watch_time_hours": 1.4,
                "thumbnail_attention_score": 59,
                "hook_score": 65,
                "impressions": 900,
            },
            {
                "click_through_rate": 0.03,
                "average_view_percentage": 47.0,
                "watch_time_hours": 1.6,
                "thumbnail_attention_score": 62,
                "hook_score": 68,
                "impressions": 900,
            },
        ]
    )

    assert state["mode"] in {"thumbnail", "retention", "balanced", "click"}
    assert "thumbnail" in state["focus"]
    assert "retention" in state["focus"]
    assert "Hook" in state["guidance"] or "Hook:" in state["guidance"]
    assert "Thumbnail" in state["guidance"] or "Thumbnail:" in state["guidance"]


def test_derive_channel_optimization_state_weak_sample_is_observe_only():
    from src.performance_optimizer import derive_channel_optimization_state

    state = derive_channel_optimization_state(
        [
            {
                "click_through_rate": 0.11,
                "average_view_percentage": 73.0,
                "watch_time_hours": 8.2,
                "impressions": 120,
            },
        ]
    )

    assert state["weak_sample"] is True
    assert state["focus"] == ["observe"]


def test_build_optimization_guidance_emits_metric_summary():
    from src.performance_optimizer import build_optimization_guidance

    guidance = build_optimization_guidance(
        {
            "avg_ctr": 0.031,
            "avg_retention": 47.2,
            "avg_watch_time_hours": 1.8,
            "guidance": "Thumbnail: daha spesifik ol. Hook: daha güçlü başla.",
        }
    )

    assert guidance.startswith("CANLI OPTIMIZATION FEEDBACK:")
    assert "CTR ort." in guidance
    assert "izlenme oranı ort." in guidance
