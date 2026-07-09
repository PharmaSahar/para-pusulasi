import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_build_performance_snapshot_includes_quality_and_channel_stats():
    from src.channel_performance import build_performance_snapshot

    snapshot = build_performance_snapshot(
        channel_id="test-channel",
        content_id="content_1",
        run_id="run_1",
        title="2026'da 50.000 TL ile yatirim",
        youtube_url="https://youtube.com/watch?v=v1",
        video_id="v1",
        thumbnail_path="/tmp/thumb.jpg",
        thumbnail_strategy="thumb-a",
        render_metrics={"render_status": "completed", "render_duration_seconds": 42.5, "output_resolution": "1920x1080", "output_fps": 24},
        analytics_join_metadata={"prompt_version": "prompt-v1", "model_version": "model-x"},
        quality_score_metadata={"hook_score": 82, "thumbnail_attention_score": 91, "retention_signal_score": 77, "overall_quality_score": 85},
        youtube_stats={"subscribers": 1200, "total_views": 45000, "video_count": 88},
        youtube_analytics={"impressions": 9000, "click_through_rate": 0.083, "average_view_duration_seconds": 154.2, "average_view_percentage": 62.3, "watch_time_hours": 412.5},
    )

    assert snapshot["performance_schema_version"] == "v1"
    assert snapshot["channel_id"] == "test-channel"
    assert snapshot["thumbnail_attention_score"] == 91
    assert snapshot["retention_signal_score"] == 77
    assert snapshot["channel_subscribers"] == 1200
    assert snapshot["impressions"] == 9000


def test_build_daily_performance_table_groups_by_day_and_channel():
    from src.channel_performance import build_daily_performance_table

    table = build_daily_performance_table(
        [
            {
                "day": "2026-07-09",
                "channel_id": "a",
                "title": "Video 1",
                "youtube_url": "u1",
                "short_url": None,
                "hook_score": 80,
                "thumbnail_attention_score": 90,
                "retention_signal_score": 70,
                "overall_quality_score": 82,
                "render_duration_seconds": 40,
                "click_through_rate": 0.05,
                "average_view_duration_seconds": 120,
                "average_view_percentage": 55,
                "watch_time_hours": 10,
                "impressions": 1000,
                "channel_subscribers": 100,
                "channel_total_views": 5000,
                "channel_video_count": 20,
            },
            {
                "day": "2026-07-09",
                "channel_id": "a",
                "title": "Video 2",
                "youtube_url": "u2",
                "short_url": "s2",
                "hook_score": 70,
                "thumbnail_attention_score": 80,
                "retention_signal_score": 60,
                "overall_quality_score": 75,
                "render_duration_seconds": 60,
                "click_through_rate": 0.07,
                "average_view_duration_seconds": 150,
                "average_view_percentage": 65,
                "watch_time_hours": 12,
                "impressions": 2000,
                "channel_subscribers": 101,
                "channel_total_views": 5100,
                "channel_video_count": 21,
            },
        ]
    )

    assert len(table) == 1
    row = table[0]
    assert row["videos_published"] == 2
    assert row["shorts_published"] == 1
    assert row["avg_thumbnail_attention_score"] == 85.0
    assert row["avg_retention_signal_score"] == 65.0
    assert row["latest_channel_subscribers"] == 101
    assert row["latest_channel_total_views"] == 5100
