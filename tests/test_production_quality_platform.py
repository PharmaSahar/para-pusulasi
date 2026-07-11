from __future__ import annotations

import json
from pathlib import Path


def test_record_event_writes_observability_and_dashboard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from src.production_quality_platform import (
        PRODUCTION_DASHBOARD_JSON_PATH,
        PRODUCTION_DASHBOARD_MD_PATH,
        PRODUCTION_EVENTS_PATH,
        PRODUCTION_OBSERVABILITY_LATEST_PATH,
        record_production_event,
        update_production_dashboard,
    )

    record_production_event(
        {
            "channel": "ch1",
            "topic": "Topic",
            "generation_id": "g1",
            "final_status": "success",
            "upload_result": {"video_id": "abc"},
            "content_type": "video",
        }
    )

    assert PRODUCTION_EVENTS_PATH.exists()
    assert PRODUCTION_OBSERVABILITY_LATEST_PATH.exists()

    payload = update_production_dashboard(
        scheduler_status="active",
        build_sha="deadbee",
        scheduler_pid=123,
        last_error=None,
    )

    assert payload["scheduler_status"] == "active"
    assert PRODUCTION_DASHBOARD_JSON_PATH.exists()
    assert PRODUCTION_DASHBOARD_MD_PATH.exists()


def test_script_quality_and_automatic_qa_contract():
    from src.production_quality_platform import evaluate_automatic_qa, score_script_quality

    sq = score_script_quality(
        title="Borsa stratejisi 2026?",
        script="Giris. Neden. Adim 1. Adim 2. Sonuc. Abone ol ve yorum yaz.",
        description="Detayli aciklama metni ve plan.",
        topic="Borsa stratejisi",
        cta_text="Abone ol ve yorum yap",
        recent_scripts=["Farkli bir script"],
    )
    assert "overall_score" in sq
    assert "metrics" in sq

    qa = evaluate_automatic_qa(
        {
            "channel": "borsa_akademi",
            "niche": "borsa",
            "topic": "Borsa stratejisi",
            "title": "Borsa stratejisi 2026?",
            "script": "Borsa stratejisi ve risk yonetimi",
            "description": "Borsa stratejisi aciklama",
            "tags": ["borsa", "strateji", "risk"],
            "thumbnail_prompt": "borsa chart dramatic contrast",
            "selected_visuals": ["a.jpg", "b.jpg"],
            "rejection_reasons": [],
            "script_similarity": 0.2,
            "shorts_enabled": True,
        }
    )

    assert qa["decision"] in {"allow", "block"}
    assert "checks" in qa


def test_upload_registry_and_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from src.production_quality_platform import (
        build_idempotency_key,
        get_registered_upload,
        register_upload,
        write_production_evidence,
    )

    idem = build_idempotency_key(
        channel="ch1",
        generation_id="g1",
        publish_at="2026-07-11T10:00:00+00:00",
        title="Title",
    )
    assert isinstance(idem, str)

    register_upload(idem, {"video_id": "vid123", "channel": "ch1", "title": "Title"})
    found = get_registered_upload(idem)
    assert found is not None
    assert found["video_id"] == "vid123"

    evidence_path = write_production_evidence(
        {
            "content_id": "g1",
            "channel": "ch1",
            "title": "Title",
            "topic": "Topic",
            "script": "Script text",
            "description": "Desc",
            "tags": ["a", "b", "c"],
            "selected_visuals": ["a.jpg"],
            "render_metrics": {"render_status": "completed"},
            "video_id": "vid123",
            "youtube_url": "https://youtube.com/watch?v=vid123",
            "final_status": "success",
        }
    )

    assert evidence_path.exists()
    payload = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    assert payload["generation_id"] == "g1"


def test_canary_gate_decision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRODUCTION_CANARY_ENABLED", "true")
    monkeypatch.setenv("PRODUCTION_CANARY_CHANNEL", "ch_canary")

    from src.production_quality_platform import canary_gate_decision

    blocked = canary_gate_decision("other_channel")
    assert blocked["allow"] is False

    allowed = canary_gate_decision("ch_canary")
    assert allowed["allow"] is True
