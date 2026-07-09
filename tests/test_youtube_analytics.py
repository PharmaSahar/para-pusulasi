import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_fetch_video_analytics_maps_report_rows(monkeypatch):
    import src.youtube_analytics as ya

    class FakeQuery:
        def execute(self):
            return {
                "columnHeaders": [
                    {"name": "video"},
                    {"name": "views"},
                    {"name": "estimatedMinutesWatched"},
                    {"name": "averageViewDuration"},
                    {"name": "averageViewPercentage"},
                    {"name": "impressions"},
                    {"name": "impressionClickThroughRate"},
                    {"name": "subscribersGained"},
                    {"name": "subscribersLost"},
                    {"name": "likes"},
                    {"name": "comments"},
                    {"name": "shares"},
                ],
                "rows": [["video123", 1200, 1800.0, 95.5, 61.2, 9000, 0.083, 10, 2, 44, 8, 5]],
            }

    class FakeReports:
        def query(self, **kwargs):
            assert kwargs["filters"] == "video==video123"
            return FakeQuery()

    class FakeService:
        def reports(self):
            return FakeReports()

    monkeypatch.setattr(ya, "get_authenticated_analytics_service", lambda channel_cfg=None: FakeService())

    report = ya.fetch_video_analytics(video_id="video123", start_date="2026-07-01", end_date="2026-07-09")

    assert report["video_id"] == "video123"
    assert report["views"] == 1200
    assert report["watch_time_hours"] == 30.0
    assert report["average_view_duration_seconds"] == 95.5
    assert report["impressions"] == 9000
    assert report["click_through_rate"] == 0.083
