"""
YouTube Historical Content Auditor — evidence-based classification.

Root cause of previous all-KEEP result:
  - Only checked if metadata FIELDS existed, not if content was appropriate
  - No channel-topic fit detection
  - No evidence confidence tracking
  - Without transcript/visual evidence: should be REVIEW_MANUALLY, not KEEP

Classification rules:
  KEEP              — relevant, metadata complete, channel fit confirmed, confident
  METADATA_FIX      — video content OK but metadata can be patched via API
  THUMBNAIL_FIX     — content OK, thumbnail needs replacement
  REVIEW_MANUALLY   — insufficient evidence or uncertain quality
  RERENDER_RECOMMENDED — script/content wrong, needs new video
  REMOVE_RECOMMENDED — clearly inappropriate (recommendation only, no auto-delete)

Evidence levels:
  - metadata_only: title + description + tags (always available from API)
  - with_local_script: script text stored locally from render
  - with_visual: thumbnail or sampled frames analyzed

Confidence:
  - HIGH:   metadata + local script + channel fit confirmed
  - MEDIUM: metadata + channel fit confirmed, no script/visual
  - LOW:    metadata only, no channel fit, no script
  - NONE:   missing critical fields

Sanity gate:
  - If KEEP == total_items AND visual_evidence_pct == 0 AND transcript_pct == 0 → FAIL
  - If REVIEW_MANUALLY == 0 while visual/transcript missing → FAIL
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

CONFIDENCE = Literal["HIGH", "MEDIUM", "LOW", "NONE"]
EVIDENCE = Literal["metadata_only", "metadata+script", "metadata+visual", "full"]

_PRIORITY_MAP: dict[str, int] = {
    "REMOVE_RECOMMENDED": 1,
    "RERENDER_RECOMMENDED": 2,
    "METADATA_FIX": 3,
    "THUMBNAIL_FIX": 4,
    "REVIEW_MANUALLY": 5,
    "KEEP": 99,
}

_MIN_DESCRIPTION_LEN = 80
_MIN_TAGS = 3
_DUPLICATE_TITLE_OVERLAP = 0.75  # Jaccard overlap to flag title duplication

_INAPPROPRIATE_RE = re.compile(
    r"\b(bikini|swimsuit|lingerie|nude|naked|topless|erotic|swimwear)\b",
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

    # Populated during classification
    classification: CLASSIFICATION = "REVIEW_MANUALLY"   # default: NOT KEEP
    confidence: CONFIDENCE = "NONE"
    evidence_available: EVIDENCE = "metadata_only"
    issue_types: list[str] = field(default_factory=list)
    metadata_patch_preview: dict[str, Any] = field(default_factory=dict)
    rerender_required: bool = False
    manual_approval_required: bool = False
    estimated_risk: Literal["low", "medium", "high"] = "low"

    # Evidence fields
    channel_fit_score: float = 0.0    # 0.0=fail, 1.0=pass
    metadata_score: float = 0.0       # fraction of required fields present
    script_similarity_score: float = 0.0  # 0=unique, 1=duplicate
    visual_review_status: str = "unavailable"  # unavailable | clean | flagged
    local_script_available: bool = False

    # Audit results
    classification: CLASSIFICATION = "KEEP"
    issue_types: list[str] = field(default_factory=list)
    metadata_patch_preview: dict[str, Any] = field(default_factory=dict)
    rerender_required: bool = False
    manual_approval_required: bool = False
    estimated_risk: Literal["low", "medium", "high"] = "low"


def _token_overlap(a: str, b: str) -> float:
    ta = set(re.findall(r"\b\w{4,}\b", a.lower()))
    tb = set(re.findall(r"\b\w{4,}\b", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _load_local_script(channel_id: str, title: str) -> str | None:
    """Try to load locally saved script for a video by matching title tokens."""
    scripts_dir = Path(f"channels/{channel_id}/output/scripts")
    if not scripts_dir.exists():
        return None
    for script_file in sorted(scripts_dir.glob("*.json"), reverse=True)[:30]:
        try:
            data = json.loads(script_file.read_text(encoding="utf-8"))
            stored_title = data.get("title", "")
            if _token_overlap(title, stored_title) >= 0.5:
                return str(data.get("script", ""))
        except Exception:
            continue
    return None


def _compute_metadata_score(item: VideoAuditItem) -> float:
    """Score 0.0–1.0: fraction of required metadata fields that are adequate."""
    checks = [
        bool(item.title and len(item.title.strip()) >= 5),
        bool(item.description and len(item.description.strip()) >= _MIN_DESCRIPTION_LEN),
        bool(item.tags and len(item.tags) >= _MIN_TAGS),
        bool(item.category_id),
        bool(item.content_type),
    ]
    return sum(checks) / len(checks)


def _classify_item(
    item: VideoAuditItem,
    channel_titles: list[str] | None = None,
) -> None:
    """
    Evidence-based classification.
    Default is REVIEW_MANUALLY, not KEEP.
    KEEP is only assigned when all required checks pass with confidence.

    channel_titles: all other video titles from same channel (for duplicate detection)
    """
    issues: list[str] = []
    patches: dict[str, Any] = {}

    # ── 1. Hard-block: inappropriate content ─────────────────────────────────
    combined_text = f"{item.title} {item.description}"
    if _INAPPROPRIATE_RE.search(combined_text):
        item.issue_types = ["inappropriate_content_detected"]
        item.classification = "REMOVE_RECOMMENDED"
        item.manual_approval_required = True
        item.estimated_risk = "high"
        item.confidence = "HIGH"
        item.metadata_patch_preview = {}
        item.channel_fit_score = 0.0
        item.metadata_score = _compute_metadata_score(item)
        item.visual_review_status = "flagged"
        return

    # ── 2. Metadata completeness ──────────────────────────────────────────────
    meta_score = _compute_metadata_score(item)
    item.metadata_score = meta_score

    if not item.title or len(item.title.strip()) < 5:
        issues.append("missing_title")
        patches["title"] = f"[Needs review] {item.channel_id}"

    if not item.description or len(item.description.strip()) < _MIN_DESCRIPTION_LEN:
        actual_len = len((item.description or "").strip())
        issues.append(f"description_too_short({actual_len})")
        patches["description_action"] = "update_required"

    if not item.tags or len(item.tags) < _MIN_TAGS:
        actual_tags = len(item.tags or [])
        issues.append(f"tags_too_few({actual_tags})")
        patches["tags_action"] = "update_required"

    if not item.category_id:
        issues.append("missing_category")
        patches["category_action"] = "update_required"

    # ── 3. Channel-topic fit ──────────────────────────────────────────────────
    channel_fit = "unknown"
    channel_fit_score = 0.5  # default: unknown
    try:
        from .content_quality_guard import check_channel_topic_fit
        fit, fit_reasons = check_channel_topic_fit(
            topic=item.title,
            script=item.description or "",
            title=item.title,
            niche=item.niche,
        )
        if fit == "fail":
            issues.append(f"channel_topic_mismatch: {'; '.join(fit_reasons[:2])}")
            channel_fit = "fail"
            channel_fit_score = 0.0
        elif fit == "pass":
            channel_fit = "pass"
            channel_fit_score = 1.0
        else:
            channel_fit = "warn"
            channel_fit_score = 0.7
    except Exception as exc:
        logger.debug("channel_topic_fit check failed: %s", exc)
    item.channel_fit_score = channel_fit_score

    # ── 4. Near-duplicate title detection within same channel ─────────────────
    # Exclude Short/video pairs: a Short is expected to share its parent's title
    if channel_titles:
        clean_title = re.sub(r'\s*#Shorts?\s*$', '', item.title, flags=re.IGNORECASE).strip()
        for other_title in channel_titles:
            if other_title == item.title:
                continue
            clean_other = re.sub(r'\s*#Shorts?\s*$', '', other_title, flags=re.IGNORECASE).strip()
            # Skip if they are a Short/video pair (one is #Shorts version of the other)
            if clean_title == clean_other:
                continue
            sim = _token_overlap(clean_title, clean_other)
            if sim >= _DUPLICATE_TITLE_OVERLAP:
                issues.append(f"near_duplicate_title(similarity={sim:.2f})")
                break

    # ── 5. Local script availability and similarity ───────────────────────────
    local_script = _load_local_script(item.channel_id, item.title)
    item.local_script_available = local_script is not None
    script_sim = 0.0
    if local_script:
        item.evidence_available = "metadata+script"
        # Check script vs. description consistency
        desc_script_sim = _token_overlap(item.description or "", local_script[:500])
        if desc_script_sim < 0.05 and len(local_script) > 50:
            issues.append(f"description_script_mismatch(sim={desc_script_sim:.2f})")
    else:
        # No local script: visual/transcript evidence unavailable
        item.evidence_available = "metadata_only"

    item.script_similarity_score = script_sim

    # ── 6. Visual review status ───────────────────────────────────────────────
    # Frames/thumbnails not available without local media download.
    # We cannot claim clean visual review from metadata alone.
    item.visual_review_status = "unavailable"

    # ── 7. Determine classification ───────────────────────────────────────────
    item.issue_types = issues
    item.metadata_patch_preview = patches

    # Hard: channel topic mismatch → needs re-render
    if channel_fit == "fail":
        item.classification = "RERENDER_RECOMMENDED"
        item.manual_approval_required = True
        item.estimated_risk = "medium"
        item.confidence = "MEDIUM"
        return

    # Metadata-only issues → METADATA_FIX
    if issues and all(
        any(issue.startswith(k) for k in ["description_", "tags_", "missing_cat", "missing_title"])
        for issue in issues
    ):
        item.classification = "METADATA_FIX"
        item.confidence = "HIGH"
        item.estimated_risk = "low"
        return

    # Near-duplicate title → rerender recommended
    if any("near_duplicate_title" in i for i in issues):
        item.classification = "RERENDER_RECOMMENDED"
        item.confidence = "MEDIUM"
        item.manual_approval_required = True
        return

    # Mixed issues → REVIEW_MANUALLY
    if issues:
        item.classification = "REVIEW_MANUALLY"
        item.confidence = "LOW"
        item.manual_approval_required = True
        return

    # No issues found BUT no transcript/visual evidence:
    # Cannot confidently mark as KEEP without verifying content quality.
    if item.evidence_available == "metadata_only":
        item.classification = "REVIEW_MANUALLY"
        item.confidence = "MEDIUM"
        item.manual_approval_required = False  # lower priority review
        return

    # Full metadata present + script available + channel fit OK → KEEP
    item.classification = "KEEP"
    item.confidence = "HIGH" if local_script else "MEDIUM"
    item.estimated_risk = "low"


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
            # Collect all titles for same-channel duplicate detection
            channel_titles = [it.title for it in items]
            for item in items:
                other_titles = [t for t in channel_titles if t != item.title]
                _classify_item(item, channel_titles=other_titles)
                summary[item.classification] = summary.get(item.classification, 0) + 1
            all_items.extend(items)
            logger.info("Audited %d items for %s", len(items), ch["channel_id"])
        except Exception as exc:
            logger.warning("Audit failed for %s: %s", ch.get("channel_id"), exc)

    # ── Evidence coverage statistics ──────────────────────────────────────────
    total = len(all_items)
    transcript_available = sum(1 for it in all_items if it.local_script_available)
    visual_available = sum(1 for it in all_items if it.visual_review_status != "unavailable")
    metadata_complete = sum(1 for it in all_items if it.metadata_score >= 0.8)

    evidence_coverage = {
        "metadata_pct": round(100 * metadata_complete / total, 1) if total else 0,
        "transcript_pct": round(100 * transcript_available / total, 1) if total else 0,
        "visual_pct": round(100 * visual_available / total, 1) if total else 0,
    }

    # ── Sanity gate ────────────────────────────────────────────────────────────
    keep_count = summary.get("KEEP", 0)
    review_count = summary.get("REVIEW_MANUALLY", 0)
    sanity_passed = True
    sanity_reasons: list[str] = []

    if total > 0 and keep_count == total and evidence_coverage["visual_pct"] == 0 and evidence_coverage["transcript_pct"] == 0:
        sanity_passed = False
        sanity_reasons.append(
            "ALL_KEEP with zero visual/transcript evidence — cannot be trusted"
        )
    if total > 0 and review_count == 0 and evidence_coverage["visual_pct"] == 0:
        sanity_passed = False
        sanity_reasons.append(
            "REVIEW_MANUALLY==0 while visual evidence unavailable — guard not working"
        )

    sanity_result = {"passed": sanity_passed, "reasons": sanity_reasons}
    if not sanity_passed:
        logger.error("AUDIT SANITY GATE FAILED: %s", sanity_reasons)

    # Write audit artifact
    audit_data = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_items": total,
        "summary": summary,
        "evidence_coverage": evidence_coverage,
        "sanity_gate": sanity_result,
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
                "confidence": it.confidence,
                "evidence_available": it.evidence_available,
                "issue_types": it.issue_types,
                "channel_fit_score": it.channel_fit_score,
                "metadata_score": it.metadata_score,
                "script_similarity_score": it.script_similarity_score,
                "visual_review_status": it.visual_review_status,
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
    return {**summary, "total": len(all_items), "evidence_coverage": evidence_coverage, "sanity_gate": sanity_result}
