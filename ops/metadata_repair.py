#!/usr/bin/env python3
"""Bulk/targeted YouTube metadata repair tool.

Features:
- Bulk mode over channel upload history.
- Targeted mode over explicit video ids.
- Dry-run by default with detailed report.
- Apply mode with optional staged apply limit.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.channel_manager import get_channel
from src.metadata_repair import normalize_metadata, parse_iso8601_duration_seconds
from src.youtube_auth import get_authenticated_service


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _chunk(items: list[str], size: int = 50):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _read_ids_file(path: str) -> list[str]:
    content = Path(path).read_text(encoding="utf-8")
    ids: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line)
    return ids


def _list_upload_video_ids(service, max_videos: int) -> list[str]:
    channels = service.channels().list(part="contentDetails", mine=True).execute()
    items = channels.get("items") or []
    if not items:
        return []
    uploads_playlist = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    if not uploads_playlist:
        return []

    ids: list[str] = []
    page_token = None
    while True:
        req = service.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        )
        res = req.execute()
        for item in res.get("items") or []:
            vid = ((item.get("contentDetails") or {}).get("videoId") or "").strip()
            if vid:
                ids.append(vid)
                if len(ids) >= max_videos:
                    return ids
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_videos]


def _fetch_video_map(service, video_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for batch in _chunk(video_ids, 50):
        res = service.videos().list(part="snippet,contentDetails,status", id=",".join(batch), maxResults=50).execute()
        for item in res.get("items") or []:
            vid = str(item.get("id") or "").strip()
            if vid:
                out[vid] = item
    return out


def _needs_update(assessment: dict, only_problematic: bool) -> bool:
    if not only_problematic:
        return True
    return bool(assessment.get("chapter_issue") or assessment.get("tag_issue") or assessment.get("seo_issue"))


def _build_update_body(video_id: str, original_snippet: dict, new_description: str, new_tags: list[str]) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": str(original_snippet.get("title") or "")[:100],
            "description": str(new_description or "")[:5000],
            "tags": list(new_tags or []),
            "categoryId": str(original_snippet.get("categoryId") or "27"),
            "defaultLanguage": str(original_snippet.get("defaultLanguage") or "tr"),
        },
    }


def run(args) -> int:
    cfg = get_channel(args.channel)
    service = get_authenticated_service(channel_cfg=cfg)

    selected_ids: list[str] = []
    if args.video_ids:
        selected_ids.extend([x.strip() for x in args.video_ids.split(",") if x.strip()])
    if args.video_ids_file:
        selected_ids.extend(_read_ids_file(args.video_ids_file))
    if args.all_videos:
        selected_ids.extend(_list_upload_video_ids(service=service, max_videos=args.max_videos))

    # Stable unique order.
    selected_ids = list(dict.fromkeys(selected_ids))
    if not selected_ids:
        raise SystemExit("No video ids found. Use --all-videos or --video-ids/--video-ids-file")

    videos = _fetch_video_map(service=service, video_ids=selected_ids)

    report = {
        "generated_at": datetime.now().isoformat(),
        "channel": args.channel,
        "apply": bool(args.apply),
        "only_problematic": bool(args.only_problematic),
        "min_tags": int(args.min_tags),
        "min_seo": int(args.min_seo),
        "requested_ids": selected_ids,
        "items": [],
        "summary": {
            "found": len(videos),
            "processed": 0,
            "candidate_updates": 0,
            "applied": 0,
            "skipped": 0,
            "errors": 0,
        },
    }
    problematic_ids: list[str] = []

    apply_left = int(args.apply_limit) if int(args.apply_limit) > 0 else 10**9

    for vid in selected_ids:
        report["summary"]["processed"] += 1
        item = videos.get(vid)
        if not item:
            report["summary"]["errors"] += 1
            report["items"].append({"video_id": vid, "error": "video_not_found"})
            continue

        snippet = dict(item.get("snippet") or {})
        duration_iso = str((item.get("contentDetails") or {}).get("duration") or "")
        duration_sec = parse_iso8601_duration_seconds(duration_iso)

        title = str(snippet.get("title") or "")
        description = str(snippet.get("description") or "")
        tags = list(snippet.get("tags") or [])

        normalized = normalize_metadata(
            title=title,
            description=description,
            tags=tags,
            duration_sec=duration_sec,
            niche=cfg.niche,
            min_tags=int(args.min_tags),
            min_seo=int(args.min_seo),
        )
        assessment = asdict(normalized.assessment)

        changed = (description.strip() != normalized.description.strip()) or (tags != normalized.tags)
        should_update = _needs_update(assessment=assessment, only_problematic=bool(args.only_problematic))
        if should_update and changed:
            report["summary"]["candidate_updates"] += 1
            problematic_ids.append(vid)

        item_report = {
            "video_id": vid,
            "title": title,
            "duration_seconds": duration_sec,
            "assessment": assessment,
            "changed": bool(changed),
            "should_update": bool(should_update),
            "applied": False,
            "error": None,
        }

        if not should_update:
            report["summary"]["skipped"] += 1
            report["items"].append(item_report)
            continue

        if changed and args.apply and apply_left > 0:
            body = _build_update_body(
                video_id=vid,
                original_snippet=snippet,
                new_description=normalized.description,
                new_tags=normalized.tags,
            )
            try:
                service.videos().update(part="snippet", body=body).execute()
                item_report["applied"] = True
                report["summary"]["applied"] += 1
                apply_left -= 1
            except HttpError as e:
                item_report["error"] = str(e)[:500]
                report["summary"]["errors"] += 1
        else:
            if not changed:
                report["summary"]["skipped"] += 1
            elif args.apply and apply_left <= 0:
                item_report["error"] = "apply_limit_reached"
                report["summary"]["skipped"] += 1

        report["items"].append(item_report)

    report["problematic_video_ids"] = problematic_ids

    if args.problematic_ids_out:
        out_path = Path(args.problematic_ids_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(problematic_ids) + ("\n" if problematic_ids else ""), encoding="utf-8")

    report_path = Path(args.report or f"logs/metadata_repair_report_{_now_stamp()}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "report_path": str(report_path),
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["errors"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bulk/targeted YouTube metadata repair")
    parser.add_argument("--channel", required=True, help="channel id from registry")
    parser.add_argument("--all-videos", action="store_true", help="scan upload history and collect video ids")
    parser.add_argument("--max-videos", type=int, default=200, help="max videos when --all-videos is used")
    parser.add_argument("--video-ids", default="", help="comma separated video ids for targeted repair")
    parser.add_argument("--video-ids-file", default="", help="one video id per line")
    parser.add_argument("--only-problematic", action="store_true", help="update only ids failing chapter/tag/seo checks")
    parser.add_argument("--min-tags", type=int, default=8, help="minimum desired tag count")
    parser.add_argument("--min-seo", type=int, default=60, help="minimum seo proxy score")
    parser.add_argument("--apply", action="store_true", help="apply changes (default is dry-run)")
    parser.add_argument("--apply-limit", type=int, default=5, help="max updates per run in apply mode")
    parser.add_argument("--report", default="", help="optional report path")
    parser.add_argument("--problematic-ids-out", default="", help="optional path to write problematic video ids")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Safe default for staged operations.
    if not args.only_problematic:
        args.only_problematic = True

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
