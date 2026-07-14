from __future__ import annotations

import json
from pathlib import Path

from src.studio_analytics_learning_bridge import JoinMethod, JoinOutcome, join_canonical_record_identity


def _runtime(path: Path, *, content_id: str, run_id: str, video_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "content_id": content_id,
                "run_id": run_id,
                "channel": "chan_1",
                "video_id": video_id,
                "upload_metadata": {"video_id": video_id, "ownership_manifest_path": "output/state/content_ownership/content_a_run_a.json"},
            }
        ),
        encoding="utf-8",
    )


def _ownership(path: Path, *, content_id: str, run_id: str) -> None:
    path.write_text(json.dumps({"content_id": content_id, "run_id": run_id, "channel_id": "chan_1"}), encoding="utf-8")


def test_exact_video_id_join(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    own = tmp_path / "own"
    runtime.mkdir()
    own.mkdir()
    _runtime(runtime / "r1.json", content_id="content_a", run_id="run_a", video_id="vid_a")

    row = {"provider": "StudioExportProvider", "youtube_video_id": "vid_a", "content_id": None, "canonical_channel_id": "chan_1"}
    out = join_canonical_record_identity(record=row, runtime_dir=runtime, ownership_dir=own)
    assert out["join_outcome"] == JoinOutcome.LINKED.value
    assert out["join_method"] == JoinMethod.BY_VIDEO_ID.value
    assert out["content_id"] == "content_a"


def test_upload_result_join(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    own = tmp_path / "own"
    runtime.mkdir()
    own.mkdir()
    _runtime(runtime / "r1.json", content_id="content_b", run_id="run_b", video_id="vid_b")

    row = {"provider": "StudioExportProvider", "youtube_video_id": "vid_b", "content_id": None, "canonical_channel_id": "chan_1"}
    out = join_canonical_record_identity(record=row, runtime_dir=runtime, ownership_dir=own)
    assert out["join_outcome"] == JoinOutcome.LINKED.value


def test_unresolved_row(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    own = tmp_path / "own"
    runtime.mkdir()
    own.mkdir()

    row = {"provider": "StudioExportProvider", "youtube_video_id": "missing", "content_id": None, "canonical_channel_id": "chan_1"}
    out = join_canonical_record_identity(record=row, runtime_dir=runtime, ownership_dir=own)
    assert out["join_outcome"] == JoinOutcome.UNRESOLVED.value


def test_ambiguous_row(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    own = tmp_path / "own"
    runtime.mkdir()
    own.mkdir()
    _runtime(runtime / "r1.json", content_id="content_x", run_id="run_x", video_id="vid_same")
    _runtime(runtime / "r2.json", content_id="content_y", run_id="run_y", video_id="vid_same")

    row = {"provider": "StudioExportProvider", "youtube_video_id": "vid_same", "content_id": None, "canonical_channel_id": "chan_1"}
    out = join_canonical_record_identity(record=row, runtime_dir=runtime, ownership_dir=own)
    assert out["join_outcome"] == JoinOutcome.AMBIGUOUS.value


def test_forbidden_title_join_not_used(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    own = tmp_path / "own"
    runtime.mkdir()
    own.mkdir()
    _runtime(runtime / "r1.json", content_id="content_a", run_id="run_a", video_id="vid_a")

    row = {
        "provider": "StudioExportProvider",
        "youtube_video_id": None,
        "content_id": None,
        "canonical_channel_id": "chan_1",
        "provenance": {"title": "same title"},
    }
    out = join_canonical_record_identity(record=row, runtime_dir=runtime, ownership_dir=own)
    assert out["join_outcome"] == JoinOutcome.UNRESOLVED.value


def test_no_timestamp_only_join(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    own = tmp_path / "own"
    runtime.mkdir()
    own.mkdir()
    _runtime(runtime / "r1.json", content_id="content_a", run_id="run_a", video_id="vid_a")

    row = {
        "provider": "StudioExportProvider",
        "youtube_video_id": None,
        "content_id": None,
        "canonical_channel_id": "chan_1",
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
    }
    out = join_canonical_record_identity(record=row, runtime_dir=runtime, ownership_dir=own)
    assert out["join_outcome"] == JoinOutcome.UNRESOLVED.value
