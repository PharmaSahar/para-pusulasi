from __future__ import annotations

import json
from pathlib import Path

from src.upload_precheck import evaluate_upload_precheck, persist_ownership_manifest
from src.visual_safety_policy import build_visual_manifest


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_manifest(*, channel_id: str, content_id: str, run_id: str, niche: str, title: str, topic: str, script: str, script_path: Path, video_path: Path, thumbnail_path: Path | None = None):
    visual_assets = [str(thumbnail_path or video_path)]
    visual_manifest_path = build_visual_manifest(
        channel_id=channel_id,
        content_id=content_id,
        run_id=run_id,
        niche=niche,
        topic=topic,
        assets=visual_assets,
        output_path=video_path.with_suffix(".visual_manifest.json"),
    )
    return persist_ownership_manifest(
        channel_id=channel_id,
        content_id=content_id,
        run_id=run_id,
        niche=niche,
        title=title,
        topic=topic,
        script=script,
        script_path=str(script_path),
        video_path=str(video_path),
        thumbnail_path=str(thumbnail_path) if thumbnail_path is not None else None,
        visual_manifest_path=str(visual_manifest_path),
    )


def _build_precheck_result(
    tmp_path,
    monkeypatch,
    *,
    niche: str = "saglik",
    title: str,
    topic: str,
    script_text: str,
    description: str,
    tags: list[str],
):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche=niche,
        title=title,
        topic=topic,
        script=script_text,
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    return evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche=niche,
        title=title,
        topic=topic,
        script=script_text,
        description=description,
        tags=tags,
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )


def test_upload_precheck_allows_valid_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam Rehberi",
        topic="Saglikli yasam",
        script="Beslenme ve uyku duzeni",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam Rehberi",
        topic="Saglikli yasam",
        script="Beslenme ve uyku duzeni",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "allow"
    assert res["guard_reason_codes"] == []


def test_upload_precheck_blocks_missing_visual_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = persist_ownership_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam Rehberi",
        topic="Saglikli yasam",
        script="Beslenme ve uyku duzeni",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
    )

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam Rehberi",
        topic="Saglikli yasam",
        script="Beslenme ve uyku duzeni",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "visual_manifest_missing" in res["guard_reason_codes"]
    assert res["details"]["visual_quarantine"]["prevent_upload"] is True


def test_upload_precheck_blocks_tuple_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_other",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert res["quarantine_reason"] == "upload_precheck_tuple_mismatch"
    assert res["recoverable"] is False
    assert "upload_precheck_tuple_mismatch" in res["guard_reason_codes"]


def test_upload_precheck_blocks_hash_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    # Mutate the file after manifest write to force hash mismatch.
    video.write_bytes(b"video-content-mutated")

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_video_hash_mismatch" in res["guard_reason_codes"]


def test_upload_precheck_blocks_cross_domain_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    policy_path = tmp_path / "config" / "content_domain_policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "v1",
                "niches": {
                    "saglik": {
                        "forbidden_keywords": ["bitcoin", "borsa"]
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikta Bitcoin Etkisi",
        topic="Saglik",
        script="Bitcoin ve borsa yorumu",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikta Bitcoin Etkisi",
        topic="Saglik",
        script="Bitcoin ve borsa yorumu",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "domain_policy_forbidden_keyword" in res["guard_reason_codes"]


def test_upload_precheck_blocks_missing_script_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "missing.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    script.unlink()

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_script_missing" in res["guard_reason_codes"]


def test_upload_precheck_blocks_missing_video_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    video.unlink()

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_video_missing" in res["guard_reason_codes"]


def test_upload_precheck_allows_missing_final_video_in_observation_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRODUCTION_OBSERVATION_MODE", "true")

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    missing_video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "blocked.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(thumb, b"thumb-content")
    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_obs",
        run_id="run_obs",
        niche="saglik",
        title="Saglikli Yasam Rehberi",
        topic="Saglikli yasam",
        script="Beslenme ve uyku duzeni",
        script_path=script,
        video_path=missing_video,
        thumbnail_path=thumb,
    )

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_obs",
        run_id="run_obs",
        niche="saglik",
        title="Saglikli Yasam Rehberi",
        topic="Saglikli yasam",
        script="Beslenme ve uyku duzeni",
        script_path=str(script),
        video_path=str(missing_video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert "upload_precheck_video_missing" not in res["guard_reason_codes"]
    assert "upload_precheck_video_empty" not in res["guard_reason_codes"]
    assert res["details"]["production_observation_mode"] is True


def test_upload_precheck_blocks_missing_thumbnail_when_required(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    thumb.unlink()

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_thumbnail_missing" in res["guard_reason_codes"]


def test_upload_precheck_blocks_unreadable_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    script = tmp_path / "channels" / "saglik_pusulasi" / "scripts" / "ok.json"
    video = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.mp4"
    thumb = tmp_path / "channels" / "saglik_pusulasi" / "output" / "videos" / "ok.jpg"
    _write_file(script, b"script-content")
    _write_file(video, b"video-content")
    _write_file(thumb, b"thumb-content")

    manifest = _make_manifest(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=script,
        video_path=video,
        thumbnail_path=thumb,
    )

    original_sha256 = getattr(__import__("src.upload_precheck", fromlist=["_sha256_file"]), "_sha256_file")

    def _broken_sha256(path):
        if str(path) == str(script):
            raise PermissionError("script unreadable")
        return original_sha256(path)

    monkeypatch.setattr("src.upload_precheck._sha256_file", _broken_sha256)

    res = evaluate_upload_precheck(
        channel_id="saglik_pusulasi",
        content_id="content_ok",
        run_id="run_ok",
        niche="saglik",
        title="Saglikli Yasam",
        topic="Saglik",
        script="Saglik script",
        script_path=str(script),
        video_path=str(video),
        thumbnail_path=str(thumb),
        manifest_path=manifest,
        enabled=True,
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_script_hash_unavailable" in res["guard_reason_codes"]


def test_upload_precheck_allows_slash_space_equivalent_tags(tmp_path, monkeypatch):
    res = _build_precheck_result(
        tmp_path,
        monkeypatch,
        niche="kisisel_finans",
        title="Dolar/TL 2026 Rehberi",
        topic="Dolar/TL 2026 Rehberi",
        script_text="Dolar/TL 2026 icin temel riskleri anlatiyoruz.",
        description="Dolar/TL 2026 gorunumu ve risk yonetimi.",
        tags=["dolar tl 2026"],
    )

    assert res["status"] == "allow"
    assert "upload_precheck_metadata_consistency_failed" not in res["guard_reason_codes"]


def test_upload_precheck_allows_repeated_whitespace_equivalent_tags(tmp_path, monkeypatch):
    res = _build_precheck_result(
        tmp_path,
        monkeypatch,
        title="abc def rehberi",
        topic="abc def rehberi",
        script_text="abc def ifadesi bu senaryoda geciyor.",
        description="abc def metadatasi korunur.",
        tags=["abc   def"],
    )

    assert res["status"] == "allow"
    assert "upload_precheck_metadata_consistency_failed" not in res["guard_reason_codes"]


def test_upload_precheck_blocks_english_tag_without_turkish_metadata_match(tmp_path, monkeypatch):
    res = _build_precheck_result(
        tmp_path,
        monkeypatch,
        niche="kisisel_finans",
        title="Dolar kuru analizi",
        topic="Dolar kuru analizi",
        script_text="Bu videoda doviz kuru riskini anlatiyoruz.",
        description="Tamamen Turkce bir aciklama.",
        tags=["usd try forecast"],
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_metadata_consistency_failed" in res["guard_reason_codes"]


def test_upload_precheck_blocks_unrelated_exact_phrase_after_canonicalization(tmp_path, monkeypatch):
    res = _build_precheck_result(
        tmp_path,
        monkeypatch,
        niche="kisisel_finans",
        title="Euro tahmini",
        topic="Euro tahmini",
        script_text="Bu videoda euro tahmini uzerinden riskleri anlatiyoruz.",
        description="Euro tahmini odakli Turkce aciklama.",
        tags=["dolar tahmini"],
    )

    assert res["status"] == "blocked"
    assert "upload_precheck_metadata_consistency_failed" in res["guard_reason_codes"]
