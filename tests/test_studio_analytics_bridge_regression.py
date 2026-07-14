from __future__ import annotations

from src.studio_analytics_learning_bridge import FutureOfficialYouTubeProvider, provider_priority


def test_provider_priority_order() -> None:
    order = provider_priority()
    assert order[0] == "FutureOfficialYouTubeProvider"
    assert order[1] == "StudioExportProvider"
    assert order[2] == "ExistingLocalAnalyticsProvider"


def test_future_official_provider_is_interface_only() -> None:
    provider = FutureOfficialYouTubeProvider()
    raised = False
    try:
        provider.collect_records()
    except NotImplementedError:
        raised = True
    assert raised is True


def test_no_automatic_application_flags() -> None:
    # Regression guard: this phase must stay advisory-only and never auto-apply actions.
    from src.studio_analytics_learning_bridge import build_advisory_recommendations

    recs = build_advisory_recommendations(
        signals=[
            {
                "signal_id": "sig_1",
                "signal_type": "LOW_CTR_HIGH_RETENTION",
                "affected_component": "title_thumbnail_discovery",
                "evidence_metrics": {},
                "confidence": 0.7,
            }
        ]
    )
    assert recs[0]["advisory_only"] is True
    assert recs[0]["pipeline_output_changed"] is False
    assert recs[0]["applied"] is False
