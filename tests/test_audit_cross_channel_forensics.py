from __future__ import annotations

from tools.audit_cross_channel_forensics import build_report


def _record(
    *,
    channel: str,
    run_id: str,
    content_id: str,
    provider_ids: list[str] | None = None,
    fps: list[str] | None = None,
    phashes: list[str] | None = None,
    thumb_hash: str = "",
    render_hash: str = "",
    media_queries: list[str] | None = None,
    thumbnail_prompt: str = "",
    scene: list[str] | None = None,
):
    return {
        "channel_id": channel,
        "run_id": run_id,
        "content_id": content_id,
        "provider_asset_ids": provider_ids or [],
        "asset_fingerprints": fps or [],
        "perceptual_hashes": [
            {"value": x, "status": "ok", "asset_fingerprint": "f", "algorithm": "average_hash_8x8.v1"}
            for x in (phashes or [])
        ],
        "thumbnail_hash": thumb_hash,
        "render_hash": render_hash,
        "media_queries": media_queries or [],
        "thumbnail_prompt": thumbnail_prompt,
        "cache_provenance": [],
        "scene_order": [
            {"scene_index": i, "asset_fingerprint": fp, "perceptual_hash": "", "provider_asset_id": "", "local_asset_hash": "", "source_type": "photo", "duration": None, "role": "body", "perceptual_hash_status": "ok", "perceptual_hash_algorithm": "average_hash_8x8.v1"}
            for i, fp in enumerate(scene or [])
        ],
        "_path": f"/tmp/{channel}_{run_id}_{content_id}.forensic.v1.json",
    }


def test_exact_duplicate_cross_channel_classification():
    a = _record(channel="a", run_id="1", content_id="x", provider_ids=["pid-1"], fps=["f1"])
    b = _record(channel="b", run_id="2", content_id="y", provider_ids=["pid-1"], fps=["f1"])

    report = build_report([a, b], phash_distance_threshold=6)
    finding = report["findings"][0]
    assert finding["classification"] == "exact_duplicate"
    assert finding["severity"] == "high"
    assert finding["confidence"] == "high"


def test_perceptual_near_duplicate_classification():
    a = _record(channel="a", run_id="1", content_id="x", phashes=["0000000000000000"])
    b = _record(channel="b", run_id="2", content_id="y", phashes=["0000000000000001"])

    report = build_report([a, b], phash_distance_threshold=2)
    finding = report["findings"][0]
    assert finding["classification"] == "perceptual_near_duplicate"
    assert finding["severity"] == "medium"
    assert finding["confidence"] == "medium"


def test_same_channel_reuse_is_marked_expected():
    a = _record(channel="same", run_id="1", content_id="x", provider_ids=["pid-1"])
    b = _record(channel="same", run_id="2", content_id="y", provider_ids=["pid-1"])

    report = build_report([a, b], phash_distance_threshold=6)
    finding = report["findings"][0]
    assert finding["same_channel"] is True
    assert finding["classification"] == "expected_same_channel_reuse"


def test_insufficient_evidence_classification():
    a = _record(channel="a", run_id="1", content_id="x", media_queries=["market update"], thumbnail_prompt="prompt")
    b = _record(channel="b", run_id="2", content_id="y", media_queries=["market update"], thumbnail_prompt="prompt")

    report = build_report([a, b], phash_distance_threshold=6)
    finding = report["findings"][0]
    assert finding["classification"] == "insufficient_evidence"
    assert finding["severity"] == "low"


def test_scene_sequence_overlap_high_without_exact():
    a = _record(channel="a", run_id="1", content_id="x", scene=["f1", "f2", "f3", "f4"])
    b = _record(channel="b", run_id="2", content_id="y", scene=["f1", "f2", "f3", "f5"])

    report = build_report([a, b], phash_distance_threshold=6)
    finding = report["findings"][0]
    assert finding["high_scene_sequence_overlap"] is True
    assert finding["classification"] == "perceptual_near_duplicate"
