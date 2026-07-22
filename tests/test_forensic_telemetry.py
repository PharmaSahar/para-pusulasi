from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from src.forensic_telemetry import (
    FORENSIC_COMPONENT,
    FORENSIC_SCHEMA_VERSION,
    average_hash_8x8,
    compute_record_hash,
    sanitize_url,
    validate_forensic_record,
    write_immutable_forensic_record,
)
from src.production_quality_platform import (
    build_generation_forensic_record,
    write_immutable_generation_forensic_record,
)


def _make_image(path: Path, color: tuple[int, int, int]) -> None:
    img = Image.new("RGB", (64, 64), color=color)
    img.save(path)


def _base_record(tmp_path: Path) -> dict:
    img_path = tmp_path / "frame.jpg"
    _make_image(img_path, (10, 20, 30))
    record = {
        "forensic_schema_version": FORENSIC_SCHEMA_VERSION,
        "timestamp_utc": "2026-07-22T00:00:00+00:00",
        "release_sha": "abc123",
        "run_id": "run_1",
        "content_id": "content_1",
        "channel_id": "channel_a",
        "topic": "topic",
        "provider": "pexels,anthropic,youtube",
        "media_queries": ["q1", "q2"],
        "provider_asset_ids": ["p1"],
        "asset_urls_sanitized": ["https://example.com/a.jpg"],
        "asset_fingerprints": ["a" * 64],
        "perceptual_hashes": [
            {
                "asset_fingerprint": "a" * 64,
                "value": "0000000000000000",
                "status": "ok",
                "algorithm": "average_hash_8x8.v1",
            }
        ],
        "selected_visuals": [str(img_path)],
        "scene_order": [
            {
                "scene_index": 0,
                "asset_fingerprint": "a" * 64,
                "perceptual_hash": "0000000000000000",
                "provider_asset_id": "p1",
                "local_asset_hash": "b" * 64,
                "source_type": "photo",
                "duration": None,
                "role": "intro",
                "perceptual_hash_status": "ok",
                "perceptual_hash_algorithm": "average_hash_8x8.v1",
            }
        ],
        "thumbnail_prompt": "prompt",
        "thumbnail_hash": "c" * 64,
        "render_hash": "d" * 64,
        "video_id": "vid",
        "youtube_url": "https://youtube.com/watch?v=vid",
        "qa_result": {"automatic_qa": {"decision": "allow"}},
        "generation_result": "success",
        "record_hash": "",
        "created_by_component": FORENSIC_COMPONENT,
        "cache_provenance": [],
    }
    record["record_hash"] = compute_record_hash(record)
    return record


def test_atomic_write_and_overwrite_refusal(tmp_path: Path):
    record = _base_record(tmp_path)
    root = tmp_path / "forensics"
    target = write_immutable_forensic_record(root_dir=root, record=record)
    assert target.exists()

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["record_hash"] == record["record_hash"]

    with pytest.raises(FileExistsError):
        write_immutable_forensic_record(root_dir=root, record=record)


def test_record_hash_is_deterministic(tmp_path: Path):
    record = _base_record(tmp_path)
    first = compute_record_hash(record)
    second = compute_record_hash(record)
    assert first == second


def test_url_sanitization_and_secret_rejection(tmp_path: Path):
    assert sanitize_url("https://example.com/file.jpg?token=abc#frag") == "https://example.com/file.jpg"

    record = _base_record(tmp_path)
    record["qa_result"] = {"authorization": "Bearer token"}
    record["record_hash"] = compute_record_hash(record)
    with pytest.raises(ValueError):
        validate_forensic_record(record)


def test_perceptual_hash_supported_and_unsupported(tmp_path: Path):
    image_path = tmp_path / "img.png"
    _make_image(image_path, (240, 120, 10))
    ok = average_hash_8x8(image_path)
    assert ok["status"] == "ok"
    assert isinstance(ok["value"], str)
    assert len(ok["value"]) == 16

    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-video")
    unsupported = average_hash_8x8(video_path)
    assert unsupported["status"] == "unsupported_media_type"
    assert unsupported["value"] is None


def test_build_generation_forensic_record_preserves_media_query_order_and_scene_order(tmp_path: Path):
    img1 = tmp_path / "a.jpg"
    img2 = tmp_path / "b.jpg"
    _make_image(img1, (1, 2, 3))
    _make_image(img2, (9, 8, 7))

    visual_manifest_path = tmp_path / "manifest.json"
    visual_manifest = {
        "assets": [
            {"asset": str(img1), "asset_fingerprint": "1" * 64, "provider_asset_id": "aid1"},
            {"asset": str(img2), "asset_fingerprint": "2" * 64, "provider_asset_id": "aid2"},
        ]
    }
    visual_manifest_path.write_text(json.dumps(visual_manifest), encoding="utf-8")

    result = {
        "final_status": "success",
        "finished_at": "2026-07-22T00:00:00+00:00",
        "build_sha": "sha",
        "run_id": "runx",
        "content_id": "contentx",
        "channel": "channelx",
        "topic": "topicx",
        "title": "titlex",
        "forensic_media_trace": {
            "provider": "pexels",
            "query_attempts": [
                {"attempt": 0, "query": "first query", "media_type": "photo"},
                {"attempt": 1, "query": "second query", "media_type": "photo"},
            ],
            "selected_assets": [
                {"provider_asset_id": "aid1", "source_url": "https://x/y.jpg?sig=abc"},
                {"provider_asset_id": "aid2", "source_url": "https://x/z.jpg?token=abc"},
            ],
            "asset_metadata_by_local_path": {
                str(img1): {"provider_asset_id": "aid1", "source_type": "photo"},
                str(img2): {"provider_asset_id": "aid2", "source_type": "photo"},
            },
            "cache_provenance": [{"cache_key": "k1"}],
        },
        "selected_visuals": [str(img1), str(img2)],
        "thumbnail_path": str(img1),
        "video_path": str(img2),
        "thumbnail_prompt": "tp",
        "video_id": "video123",
        "youtube_url": "https://youtube.com/watch?v=video123",
        "automatic_qa": {"decision": "allow", "blocked_checks": []},
        "content_quality": {"publish_decision": "allow"},
        "script_quality": {"overall_score": 77},
        "thumbnail_intelligence": {"quality": {}},
        "rejection_reasons": [],
        "visual_manifest_path": str(visual_manifest_path),
    }

    record = build_generation_forensic_record(result)
    assert record["media_queries"] == ["first query", "second query"]
    assert record["provider_asset_ids"] == ["aid1", "aid2"]
    assert record["asset_urls_sanitized"] == ["https://x/y.jpg", "https://x/z.jpg"]
    assert [x["scene_index"] for x in record["scene_order"]] == [0, 1]
    assert record["scene_order"][0]["role"] == "thumbnail-source"
    assert record["thumbnail_hash"]
    assert record["render_hash"]
    validate_forensic_record(record)


def test_failed_generation_does_not_create_success_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import src.production_quality_platform as pqp

    monkeypatch.setattr(pqp, "FORENSIC_GENERATION_ROOT", tmp_path / "forensics")
    out = write_immutable_generation_forensic_record({"final_status": "failed"})
    assert out is None
    assert not (tmp_path / "forensics").exists()


def test_channel_run_content_isolation_and_concurrency(tmp_path: Path):
    root = tmp_path / "forensics"
    created: list[Path] = []

    def _writer(channel: str, run_id: str, content_id: str):
        record = _base_record(tmp_path)
        record["channel_id"] = channel
        record["run_id"] = run_id
        record["content_id"] = content_id
        record["record_hash"] = compute_record_hash(record)
        created.append(write_immutable_forensic_record(root_dir=root, record=record))

    threads = [
        threading.Thread(target=_writer, args=("c1", "r1", "x1")),
        threading.Thread(target=_writer, args=("c2", "r2", "x2")),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert len(created) == 2
    assert created[0] != created[1]
    assert created[0].exists() and created[1].exists()
