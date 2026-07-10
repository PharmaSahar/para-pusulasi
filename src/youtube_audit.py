"""
YouTube Historical Content Auditor.

Queries all published videos/Shorts from managed channels via YouTube Data API.
Classifies each item without modifying or deleting content.

Classifications:
  KEEP              — relevant and acceptable
  METADATA_FIX      — content OK, metadata needs update (API can patch)
  THUMBNAIL_FIX     — content OK, thumbnail should be replaced
  REVIEW_MANUALLY   — uncertain issue, human judgment needed
  RERENDER_RECOMMENDED — script/audio/video wrong, needs new video
  REMOVE_RECOMMENDED — severely inappropriate (recommendation only, no auto-delete)

Limitations:
  - Deleted YouTube videos CANNOT be recovered. Never claim otherwise.
  - The actual video file cannot be replaced while keeping the same video ID.
  - Only title, description, tags, category, and thumbnail can be patched via API.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

_AUDIT_PATH = Path("logs/historical_content_audit_latest.json")
_REMEDIATION_PATH = Path("logs/historical_content_remediation_queue.json")

CLASSIFICATION = Literal[
    "KEEP",
    "METADATA_FIX",
    "THUMBNAIL_FIX",
    "REVIEW_MANUALLY",
    "RERENDER_RECOMMENDED",
    "REMOVE_RECOMMENDED",
]

_PRIORITY_MAP: dict[str, int] = {
    "REMOVE_RECOMMENDED": 1,
    "RERENDER_RECOMMENDED": 2,
    "METADATA_FIX": 3,
    "THUMBNAIL_FIX": 4,
    "REVIEW_MANUALLY": 5,
    "KEEP": 99,
}

# ── Audit signals ─────────────────────────────────────────────────────────────

_MIN_DESCRIPTION_LEN = 60
_MIN_TAGS = 2

_INAPPROPRIATE_ALT_RE = re.compile(
    r"\b(bikini|swimsuit|lingerie|nude|naked|topless|erotic)\b",
    re.IGNORECASE,
)


@dataclass
class VideoAuditItem:
    channel_id: str
    video_id: str
    url: str
    title: str
    description: str
    tags: list[str]
    category_id: str
    published_at: str
    duration: str
    view_count: int
    like_count: int
    comment_count: int
    privacy_status: str
    content_type: Literal["video", "short"]
    niche: str

    # Audit results
    classification: CLASSIFICATION = "KEEP"
    issue_types: list[str] = field(default_factory=list)
    metadata_patch_preview: dict[str, Any] = field(default_factory=dict)
    rerender_required: bool = False
    manual_approval_required: bool = False
    estimated_risk: Literal["low", "medium", "high"] = "low"


def _classify_item(item: VideoAuditItem) -> None:
    """Classify a video item in-place based on its metadata."""
    issues: list[str] = []
    patches: dict[str, Any] = {}

    # 1. Check title
    if not item.title or len(item.title.strip()) < 5:
        issues.append("missing_title")
        patches["title"] = f"[Needs review] {item.channel_id}"

    # 2. Check description
    if not item.description or len(item.description.strip()) < _MIN_DESCRIPTION_LEN:
        issues.append(f"description_too_short({len(item.description or '')})")
        patches["description_action"] = "update_required"

    # 3. Check tags
    if len(item.tags) < _MIN_TAGS:
        issues.append(f"tags_too_few({len(item.tags)})")
        patches["tags_action"] = "update_required"

    # 4. Check category
    if not item.category_id:
        issues.append("missing_category")

    # 5. Inappropriate content signal in title/description
    combined = f"{item.title} {item.description}"
    if _INAPPROPRIATE_ALT_RE.search(combined):
        issues.append("potentially_inappropriate_content")
        item.estimated_risk = "high"

    # 6. Determine classification
    if "potentially_inappropriate_content" in issues:
        item.classification = "REMOVE_RECOMMENDED"
        item.manual_approval_required = True
        item.estimated_risk = "high"
    elif any(i.startswith("missing_title") for i in issues):
        item.classification = "METADATA_FIX"
    elif issues and not item.rerender_required:
        item.classification = "METADATA_FIX"
    elif item.rerender_required:
        item.classification = "RERENDER_RECOMMENDED"
        item.manual_approval_required = True
    else:
        item.classification = "KEEP"

    item.issue_types = issues
    item.metadata_patch_preview = patches


def _is_short(duration: str) -> bool:
    """Estimate if a video is a Short based on ISO 8601 duration (< 61 seconds)."""
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return False
    minutes = int(m.group(1) or 0)
    seconds = int(m.group(2) or 0)
    total = minutes * 60 + seconds
    return total <= 61


def fetch_channel_videos(
    service: Any,
    youtube_channel_id: str,
    channel_id: str,
    niche: str,
    max_results: int = 50,
) -> list[VideoAuditItem]:
    """
    Fetch all videos from a channel using YouTube Data API.
    Returns list of VideoAuditItem (unclassified).
    """
    items: list[VideoAuditItem] = []

    try:
        # Get uploads playlist ID
        ch_resp = service.channels().list(
            part="contentDetails",
            id=youtube_channel_id,
        ).execute()
        channel_data = ch_resp.get("items", [])
        if not channel_data:
            logger.warning("Channel not found: %s", youtube_channel_id)
            return []
        uploads_playlist = (
            channel_data[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        )

        # List playlist items
        page_token = None
        video_ids: list[str] = []
        while True:
            pl_resp = service.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist,
                maxResults=50,
                pageToken=page_token,
            ).execute()
            for pl_item in pl_resp.get("items", []):
                video_ids.append(pl_item["contentDetails"]["videoId"])
            page_token = pl_resp.get("nextPageToken")
            if not page_token or len(video_ids) >= max_results:
                break

        if not video_ids:
            return []

        # Batch fetch video details (50 per call)
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            v_resp = service.videos().list(
                part="snippet,statistics,contentDetails,status",
                id=",".join(batch),
            ).execute()
            for v in v_resp.get("items", []):
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                content_details = v.get("contentDetails", {})
                status = v.get("status", {})
                duration = content_details.get("duration", "")
                vid_id = v["id"]
                items.append(
                    VideoAuditItem(
                        channel_id=channel_id,
                        video_id=vid_id,
                        url=f"https://youtube.com/watch?v={vid_id}",
                        title=snippet.get("title", ""),
                        description=snippet.get("description", ""),
                        tags=snippet.get("tags", []),
                        category_id=snippet.get("categoryId", ""),
                        published_at=snippet.get("publishedAt", ""),
                        duration=duration,
                        view_count=int(stats.get("viewCount", 0)),
                        like_count=int(stats.get("likeCount", 0)),
                        comment_count=int(stats.get("commentCount", 0)),
                        privacy_status=status.get("privacyStatus", "unknown"),
                        content_type="short" if _is_short(duration) else "video",
                        niche=niche,
                    )
                )
    except Exception as exc:
        logger.warning("Error fetching channel %s: %s", channel_id, exc)

    return items


def run_historical_audit(channels: list[dict]) -> dict:
    """
    Run historical audit for all provided channels.
    Each entry in `channels` must have: channel_id, youtube_channel_id, niche, service.
    Returns audit summary.
    """
    all_items: list[VideoAuditItem] = []
    summary: dict[str, int] = {
        "KEEP": 0,
        "METADATA_FIX": 0,
        "THUMBNAIL_FIX": 0,
        "REVIEW_MANUALLY": 0,
        "RERENDER_RECOMMENDED": 0,
        "REMOVE_RECOMMENDED": 0,
        "DELETED_CONTENT_RECOVERY": 0,
    }

    for ch in channels:
        try:
            items = fetch_channel_videos(
                service=ch["service"],
                youtube_channel_id=ch["youtube_channel_id"],
                channel_id=ch["channel_id"],
                niche=ch["niche"],
            )
            for item in items:
                _classify_item(item)
                summary[item.classification] = summary.get(item.classification, 0) + 1
            all_items.extend(items)
            logger.info("Audited %d items for %s", len(items), ch["channel_id"])
        except Exception as exc:
            logger.warning("Audit failed for %s: %s", ch.get("channel_id"), exc)

    # Write audit artifact
    audit_data = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_items": len(all_items),
        "summary": summary,
        "deleted_content_recovery": "NOT_POSSIBLE",
        "items": [
            {
                "channel_id": it.channel_id,
                "video_id": it.video_id,
                "url": it.url,
                "title": it.title,
                "content_type": it.content_type,
                "privacy_status": it.privacy_status,
                "view_count": it.view_count,
                "like_count": it.like_count,
                "classification": it.classification,
                "issue_types": it.issue_types,
                "metadata_patch_preview": it.metadata_patch_preview,
                "rerender_required": it.rerender_required,
                "manual_approval_required": it.manual_approval_required,
                "estimated_risk": it.estimated_risk,
            }
            for it in all_items
        ],
    }
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _AUDIT_PATH.write_text(json.dumps(audit_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write remediation queue (sorted by priority, excluding KEEP)
    queue = [
        {
            "priority": _PRIORITY_MAP.get(it.classification, 99),
            "channel": it.channel_id,
            "video_id": it.video_id,
            "url": it.url,
            "title": it.title,
            "issue_types": it.issue_types,
            "recommended_action": it.classification,
            "metadata_patch_preview": it.metadata_patch_preview,
            "rerender_required": it.rerender_required,
            "manual_approval_required": it.manual_approval_required,
            "estimated_risk": it.estimated_risk,
            "view_count": it.view_count,
            "like_count": it.like_count,
        }
        for it in all_items
        if it.classification != "KEEP"
    ]
    queue.sort(key=lambda x: x["priority"])
    _REMEDIATION_PATH.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "items": queue},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    logger.info("Historical audit complete: %d items, %s", len(all_items), summary)
    return {**summary, "total": len(all_items)}
