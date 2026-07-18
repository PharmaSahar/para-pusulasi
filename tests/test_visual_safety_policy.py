from __future__ import annotations

import json
from pathlib import Path

from src.upload_precheck import evaluate_upload_precheck, persist_ownership_manifest
from src.visual_safety_policy import (
    MODERATION_VERSION,
    POLICY_VERSION,
    build_visual_manifest,
    evaluate_external_moderation,
    evaluate_visual_candidate,
    evaluate_visual_query,
    validate_cache_provenance,
)


def _write(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_unsafe_query_blocked_before_provider_call():
    decision = evaluate_visual_query(
        query="fit sexy woman beach body",
        channel_id="saglik_pusulasi",
        niche="saglik",
        topic="egzersiz",
    )

    assert decision.allowed is False
    assert "visual_query_unsafe_terms" in decision.failed_rules
    assert decision.rewritten_query == "health medical clinic equipment nutrition"


def test_neutral_query_with_unsafe_provider_result_rejected():
    decision = evaluate_visual_candidate(
        candidate={"id": "p1", "alt": "Woman in bikini on beach", "url": "https://pexels.example/p1"},
        media_type="photo",
        channel_id="para_pusulasi",
        niche="kisisel_finans",
        topic="emeklilik",
        query="retirement planning documents",
    )

    assert decision.allowed is False
    assert "visual_candidate_unsafe_terms" in decision.failed_rules


def test_safe_provider_result_accepted_without_gender_ban():
    decision = evaluate_visual_candidate(
        candidate={"id": "p2", "alt": "Female financial advisor reviewing investment chart", "url": "https://pexels.example/p2"},
        media_type="photo",
        channel_id="para_pusulasi",
        niche="kisisel_finans",
        topic="yatirim",
        query="investment chart office",
    )

    assert decision.allowed is True


def test_missing_metadata_fails_closed():
    decision = evaluate_visual_candidate(
        candidate={"id": "p3"},
        media_type="photo",
        channel_id="egitim_rehberi",
        niche="egitim",
        topic="ders calisma",
    )

    assert decision.allowed is False
    assert "visual_candidate_metadata_missing" in decision.failed_rules


def test_cross_channel_cache_reuse_rejected():
    decision = validate_cache_provenance(
        entry={
            "channel_id": "saglik_pusulasi",
            "policy_version": POLICY_VERSION,
            "moderation_version": MODERATION_VERSION,
            "moderation_result": "safe",
            "provider": "pexels",
            "topic_domain": "saglik",
            "asset_fingerprint": "abc",
        },
        channel_id="para_pusulasi",
        niche="kisisel_finans",
        topic_domain="kisisel_finans",
        provider="pexels",
    )

    assert decision.allowed is False
    assert "visual_cache_channel_mismatch" in decision.failed_rules


def test_legacy_cache_without_safety_provenance_rejected():
    decision = validate_cache_provenance(
        entry={"channel_id": "para_pusulasi", "provider": "pexels"},
        channel_id="para_pusulasi",
        niche="kisisel_finans",
        topic_domain="kisisel_finans",
        provider="pexels",
    )

    assert decision.allowed is False
    assert "visual_cache_policy_version_missing" in decision.failed_rules
    assert "visual_cache_moderation_missing" in decision.failed_rules


def test_upload_precheck_blocks_unsafe_final_asset_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "channels" / "para_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "para_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "para_pusulasi" / "output" / "videos" / "ok.jpg"
    _write(script, b"script")
    _write(video, b"video")
    _write(thumb, b"thumb")
    visual_manifest = tmp_path / "channels" / "para_pusulasi" / "output" / "videos" / "ok.visual_manifest.json"
    visual_manifest.write_text(
        json.dumps(
            {
                "policy_version": POLICY_VERSION,
                "channel_id": "para_pusulasi",
                "content_id": "content_ok",
                "run_id": "run_ok",
                "assets": [
                    {
                        "asset": str(thumb),
                        "channel_id": "para_pusulasi",
                        "policy_version": POLICY_VERSION,
                        "moderation_result": "unsafe",
                        "moderation_version": MODERATION_VERSION,
                        "approved": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = persist_ownership_manifest(
        channel_id="para_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="kisisel_finans",
        title="Emeklilik Plani",
        topic="Emeklilik",
        script="Finans script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        visual_manifest_path=str(visual_manifest),
    )

    res = evaluate_upload_precheck(
        channel_id="para_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="kisisel_finans",
        title="Emeklilik Plani",
        topic="Emeklilik",
        script="Finans script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        visual_manifest_path=visual_manifest,
        final_visual_assets=[str(thumb)],
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "visual_asset_not_approved" in res["guard_reason_codes"]
    assert res["details"]["visual_quarantine"]["prevent_upload"] is True


def test_final_manifest_mismatch_blocks_upload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "channels" / "teknoloji_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "teknoloji_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "teknoloji_pusulasi" / "output" / "videos" / "ok.jpg"
    other = tmp_path / "channels" / "teknoloji_pusulasi" / "output" / "videos" / "other.jpg"
    for path in (script, video, thumb, other):
        _write(path, path.name.encode())
    visual_manifest = build_visual_manifest(
        channel_id="teknoloji_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="teknoloji",
        topic="AI araclari",
        assets=[str(thumb)],
        output_path=tmp_path / "visual.json",
    )
    manifest = persist_ownership_manifest(
        channel_id="teknoloji_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="teknoloji",
        title="AI Araclari",
        topic="AI araclari",
        script="Teknoloji script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        visual_manifest_path=str(visual_manifest),
    )

    res = evaluate_upload_precheck(
        channel_id="teknoloji_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="teknoloji",
        title="AI Araclari",
        topic="AI araclari",
        script="Teknoloji script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        visual_manifest_path=visual_manifest,
        final_visual_assets=[str(other)],
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "visual_final_asset_manifest_mismatch" in res["guard_reason_codes"]


def test_safe_visual_manifest_passes_upload_precheck(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "channels" / "egitim_rehberi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "egitim_rehberi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "egitim_rehberi" / "output" / "videos" / "ok.jpg"
    for path in (script, video, thumb):
        _write(path, path.name.encode())
    visual_manifest = build_visual_manifest(
        channel_id="egitim_rehberi",
        content_id="content_ok",
        run_id="run_ok",
        niche="egitim",
        topic="Ders calisma",
        assets=[str(thumb)],
        output_path=tmp_path / "safe.visual.json",
    )
    manifest = persist_ownership_manifest(
        channel_id="egitim_rehberi",
        content_id="content_ok",
        run_id="run_ok",
        niche="egitim",
        title="Ders Calisma Plani",
        topic="Ders calisma",
        script="Egitim script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        visual_manifest_path=str(visual_manifest),
    )

    res = evaluate_upload_precheck(
        channel_id="egitim_rehberi",
        content_id="content_ok",
        run_id="run_ok",
        niche="egitim",
        title="Ders Calisma Plani",
        topic="Ders calisma",
        script="Egitim script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        visual_manifest_path=visual_manifest,
        final_visual_assets=[str(thumb)],
        enabled=True,
    )

    assert res["status"] == "allow"


def test_unsafe_video_body_asset_blocks_upload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "channels" / "kariyer_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "kariyer_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "kariyer_pusulasi" / "output" / "videos" / "ok.jpg"
    body_asset = tmp_path / "channels" / "kariyer_pusulasi" / "output" / "clips" / "unsafe.mp4"
    for path in (script, video, thumb, body_asset):
        _write(path, path.name.encode())
    visual_manifest = tmp_path / "unsafe_body.visual.json"
    visual_manifest.write_text(
        json.dumps(
            {
                "policy_version": POLICY_VERSION,
                "channel_id": "kariyer_pusulasi",
                "content_id": "content_ok",
                "run_id": "run_ok",
                "assets": [
                    {
                        "asset": str(body_asset),
                        "channel_id": "kariyer_pusulasi",
                        "policy_version": POLICY_VERSION,
                        "moderation_result": "unsafe",
                        "moderation_version": MODERATION_VERSION,
                        "approved": False,
                        "asset_fingerprint": "fp",
                    },
                    {
                        "asset": str(thumb),
                        "channel_id": "kariyer_pusulasi",
                        "policy_version": POLICY_VERSION,
                        "moderation_result": "safe",
                        "moderation_version": MODERATION_VERSION,
                        "approved": True,
                        "asset_fingerprint": "fp2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = persist_ownership_manifest(
        channel_id="kariyer_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="kariyer",
        title="Kariyer Plani",
        topic="Kariyer",
        script="Kariyer script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        visual_manifest_path=str(visual_manifest),
    )

    res = evaluate_upload_precheck(
        channel_id="kariyer_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="kariyer",
        title="Kariyer Plani",
        topic="Kariyer",
        script="Kariyer script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        visual_manifest_path=visual_manifest,
        final_visual_assets=[str(body_asset), str(thumb)],
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "visual_asset_not_approved" in res["guard_reason_codes"]


def test_safe_exercise_sportswear_accepted():
    decision = evaluate_visual_candidate(
        candidate={"id": "fit1", "alt": "Adult demonstrating squat exercise in standard athletic clothing", "url": "https://pexels.example/fit1"},
        media_type="photo",
        channel_id="saglik_pusulasi",
        niche="saglik",
        topic="squat formu",
        query="exercise demonstration athletic clothing",
    )

    assert decision.allowed is True


def test_no_upload_multi_channel_dry_run_matrix():
    channels = [
        ("saglik_pusulasi", "saglik"),
        ("para_pusulasi", "kisisel_finans"),
        ("girisim_okulu", "girisim"),
        ("egitim_rehberi", "egitim"),
        ("teknoloji_pusulasi", "teknoloji"),
        ("kripto_rehber", "kripto"),
        ("kariyer_pusulasi", "kariyer"),
        ("gayrimenkul_tv", "gayrimenkul"),
    ]

    for channel_id, niche in channels:
        normal = evaluate_visual_query(
            query="professional office desk planning documents",
            channel_id=channel_id,
            niche=niche,
            topic="normal topic",
        )
        risky = evaluate_visual_query(
            query="sexy woman bikini beach model",
            channel_id=channel_id,
            niche=niche,
            topic="body/model-attracting topic",
        )
        unsafe_provider = evaluate_visual_candidate(
            candidate={"id": "unsafe", "alt": "Woman in bikini on beach", "url": "https://example.invalid/unsafe"},
            media_type="photo",
            channel_id=channel_id,
            niche=niche,
            topic="neutral provider query",
            query="office planning",
        )
        safe_provider = evaluate_visual_candidate(
            candidate={"id": "safe", "alt": "Professional adult in office reviewing documents", "url": "https://example.invalid/safe"},
            media_type="photo",
            channel_id=channel_id,
            niche=niche,
            topic="normal topic",
            query="office planning",
        )
        cache = validate_cache_provenance(
            entry={
                "channel_id": "other_channel",
                "policy_version": POLICY_VERSION,
                "moderation_version": MODERATION_VERSION,
                "moderation_result": "safe",
                "provider": "pexels",
                "topic_domain": niche,
                "asset_fingerprint": "fp",
            },
            channel_id=channel_id,
            niche=niche,
            topic_domain=niche,
            provider="pexels",
        )

        assert normal.allowed is True
        assert risky.allowed is False
        assert unsafe_provider.allowed is False
        assert safe_provider.allowed is True
        assert cache.allowed is False


def test_benign_model_body_and_revealing_phrases_are_accepted():
    for query in [
        "business model canvas office planning",
        "AI model architecture computer screen",
        "body of evidence documents on desk",
        "apartment building model architecture office",
        "revealing quarterly results chart presentation",
    ]:
        decision = evaluate_visual_query(
            query=query,
            channel_id="girisim_okulu",
            niche="girisim",
            topic="benign context",
        )
        assert decision.allowed is True, query


def test_unrelated_glamour_image_rejected_for_finance():
    decision = evaluate_visual_candidate(
        candidate={"id": "g1", "alt": "Glamour model posing in luxury resort", "url": "https://example.invalid/g1"},
        media_type="photo",
        channel_id="para_pusulasi",
        niche="kisisel_finans",
        topic="emeklilik",
        query="retirement planning documents",
    )

    assert decision.allowed is False
    assert "visual_candidate_unsafe_terms" in decision.failed_rules


def test_classifier_timeout_and_exception_fail_closed():
    timeout_decision = evaluate_external_moderation(
        classifier=lambda _asset: (_ for _ in ()).throw(TimeoutError()),
        asset="asset.jpg",
        channel_id="saglik_pusulasi",
        source="generated_image",
    )
    exception_decision = evaluate_external_moderation(
        classifier=lambda _asset: (_ for _ in ()).throw(RuntimeError("boom")),
        asset="asset.jpg",
        channel_id="saglik_pusulasi",
        source="generated_image",
    )

    assert timeout_decision.allowed is False
    assert "visual_classifier_timeout" in timeout_decision.failed_rules
    assert exception_decision.allowed is False
    assert "visual_classifier_exception" in exception_decision.failed_rules


def test_missing_and_low_confidence_moderation_fail_closed():
    missing = evaluate_external_moderation(
        classifier=lambda _asset: None,
        asset="asset.jpg",
        channel_id="saglik_pusulasi",
        source="stock_image",
    )
    low_confidence = evaluate_external_moderation(
        classifier=lambda _asset: {"status": "safe", "confidence": "low"},
        asset="asset.jpg",
        channel_id="saglik_pusulasi",
        source="stock_image",
    )

    assert missing.allowed is False
    assert "visual_moderation_missing" in missing.failed_rules
    assert low_confidence.allowed is False
    assert "visual_moderation_low_confidence" in low_confidence.failed_rules


def test_fallback_retry_short_and_longform_unsafe_candidates_cannot_bypass():
    for source, media_type in [
        ("fallback", "photo"),
        ("retry", "photo"),
        ("short", "video"),
        ("longform", "video"),
    ]:
        decision = evaluate_visual_candidate(
            candidate={"id": source, "alt": "Woman in bikini on beach", "url": f"https://example.invalid/{source}"},
            media_type=media_type,
            channel_id="teknoloji_pusulasi",
            niche="teknoloji",
            topic="AI tools",
            query="software office workspace",
            source=source,
        )
        assert decision.allowed is False, source