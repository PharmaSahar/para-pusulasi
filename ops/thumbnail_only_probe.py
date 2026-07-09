#!/usr/bin/env python3
"""Run a controlled thumbnail-only probe on an existing video.

This does not upload a new video. It only calls thumbnails.set against an existing
video_id and records auth/channel/error evidence for root-cause analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.channel_manager import get_channel
from src.youtube_auth import get_authenticated_service

CACHE_PATH = ROOT / "logs" / "thumbnail_permission_cache.json"
REQUIRED_STREAK_FOR_RESOLVED = 3


def _classify_403(detail: str) -> str:
    text = (detail or "").lower()
    if "insufficientpermissions" in text or ("forbidden" in text and "permission" in text):
        return "ownership_or_brand_permission"
    if "channel" in text and "not found" in text:
        return "token_channel_mismatch"
    if "thumbnail" in text and "disabled" in text:
        return "custom_thumbnail_eligibility"
    if "policy" in text or "verification" in text:
        return "api_policy_or_verification"
    return "forbidden_unknown"


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {"channels": {}}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"channels": {}}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_cache(channel_id: str, ok: bool, reason: str | None, evidence: dict) -> dict:
    cache = _load_cache()
    channels = dict(cache.get("channels") or {})
    prev = channels.get(channel_id, {})
    prev_streak = int(prev.get("success_streak", 0) or 0)
    streak = (prev_streak + 1) if ok else 0
    channels[channel_id] = {
        "can_upload_thumbnail": bool(ok),
        "success_streak": streak,
        "last_reason": reason,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "last_probe": evidence,
    }
    cache["channels"] = channels
    _save_cache(cache)
    return channels[channel_id]


def _resolve_thumbnail_path(channel_id: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"thumbnail not found: {p}")
        return p

    videos_dir = ROOT / "channels" / channel_id / "output" / "videos"
    candidates = sorted(videos_dir.glob("*_thumbnail.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"no thumbnail candidate found in {videos_dir}")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled thumbnail-only probe")
    parser.add_argument("--channel", required=True, help="Channel ID (e.g. egitim_rehberi)")
    parser.add_argument("--video-id", required=True, help="Existing YouTube video ID")
    parser.add_argument("--thumbnail", default=None, help="Path to thumbnail image (jpg). If omitted, latest channel thumbnail is used")
    args = parser.parse_args()

    cfg = get_channel(args.channel)
    thumb_path = _resolve_thumbnail_path(args.channel, args.thumbnail)

    service = get_authenticated_service(channel_cfg=cfg)
    mine = service.channels().list(part="id,snippet,status", mine=True).execute()
    mine_items = mine.get("items", [])
    auth_channel = mine_items[0] if mine_items else {}

    base = {
        "channel_id": args.channel,
        "token_path": cfg.token_path,
        "video_id": args.video_id,
        "thumbnail_path": str(thumb_path),
        "authenticated_channel_id": auth_channel.get("id"),
        "authenticated_channel_title": (auth_channel.get("snippet") or {}).get("title"),
    }

    try:
        service.thumbnails().set(
            videoId=args.video_id,
            media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
        ).execute()
        cache_state = _update_cache(args.channel, ok=True, reason=None, evidence={**base, "status": 200})
        result = {
            **base,
            "http_status": 200,
            "ok": True,
            "classification": "success",
            "cache_state": cache_state,
            "resolved_ready": cache_state.get("success_streak", 0) >= REQUIRED_STREAK_FOR_RESOLVED,
            "required_streak": REQUIRED_STREAK_FOR_RESOLVED,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except HttpError as e:
        status = int(getattr(getattr(e, "resp", None), "status", 0) or 0)
        content = getattr(e, "content", b"")
        detail = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
        reason = _classify_403(detail) if status == 403 else "http_error"
        cache_state = _update_cache(args.channel, ok=False, reason=reason, evidence={**base, "status": status, "detail": detail[:800]})
        result = {
            **base,
            "http_status": status,
            "ok": False,
            "classification": reason,
            "error_body": detail[:1200],
            "cache_state": cache_state,
            "resolved_ready": False,
            "required_streak": REQUIRED_STREAK_FOR_RESOLVED,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
