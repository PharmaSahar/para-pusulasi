from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HIGH_CONFIDENCE_UNSAFE_RE = re.compile(
    r"\b("
    r"bikini|bikinili|swimsuit|swimwear|beachwear|lingerie|underwear|bra|"
    r"cleavage|sexy|sensual|glamour|woman on beach|attractive woman|"
    r"curves|scantily clad|pin-up|topless|nude|nudity|naked|erotic|pornographic"
    r")\b",
    re.IGNORECASE,
)
SEMANTIC_REVIEW_RE = re.compile(
    r"\b(fashion model|glamour model|fitness woman|body transformation|revealing clothing|revealing outfit|model on beach)\b",
    re.IGNORECASE,
)
BENIGN_FALSE_POSITIVE_RE = re.compile(
    r"\b("
    r"business model|ai model|data model|model apartment|apartment model|financial model|"
    r"body of evidence|body of a document|body text|governing body|revealing a result|"
    r"revealing results|revealing quarterly results"
    r")\b",
    re.IGNORECASE,
)

EVIDENCE_SUFFIXES = {".json", ".jsonl", ".csv", ".txt", ".log", ".md"}


def _read_text(path: Path, limit_bytes: int = 2_000_000) -> str:
    try:
        with path.open("rb") as fh:
            data = fh.read(limit_bytes)
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _iter_files(roots: list[Path]):
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in EVIDENCE_SUFFIXES:
                yield path


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"status": "MISSING_EVIDENCE", "raw_line_preview": line[:300]})
    except Exception:
        return []
    return rows


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _matches(pattern: re.Pattern[str], text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in pattern.finditer(text)})


def _visual_confirmation(node: dict[str, Any]) -> list[str]:
    evidence = []
    moderation = _safe_str(node.get("moderation_result") or node.get("visual_moderation") or node.get("safety_result")).lower()
    if moderation and moderation not in {"safe", "allowed", "pass", "passed"}:
        evidence.append(f"moderation_result:{moderation}")
    if node.get("approved") is False:
        evidence.append("approved:false")
    return evidence


def _classify_text_evidence(text: str, node: dict[str, Any] | None = None) -> tuple[str | None, list[str]]:
    node = node or {}
    visual_evidence = _visual_confirmation(node)
    high_confidence = _matches(HIGH_CONFIDENCE_UNSAFE_RE, text)
    review = _matches(SEMANTIC_REVIEW_RE, text)
    benign = _matches(BENIGN_FALSE_POSITIVE_RE, text)
    if visual_evidence:
        return "VISUALLY_CONFIRMED_UNSAFE", visual_evidence + high_confidence + review
    if high_confidence:
        return "TEXT_CONFIRMED_HIGH_CONFIDENCE", high_confidence
    if review:
        return "REVIEW_REQUIRED", review
    if benign:
        return "BENIGN_FALSE_POSITIVE", benign
    if _safe_str(node.get("status")) == "MISSING_EVIDENCE":
        return "MISSING_EVIDENCE", ["malformed_or_unreadable_evidence"]
    return None, []


def _extract_channel(value: dict[str, Any], path: Path) -> str:
    for key in ("channel_id", "channel", "expected_channel", "detected_channel"):
        if _safe_str(value.get(key)):
            return _safe_str(value.get(key))
    parts = path.parts
    if "channels" in parts:
        idx = parts.index("channels")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return "unknown"


def _flatten_json_records(payload: Any, path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def walk(node: Any, parent: dict[str, Any] | None = None):
        if isinstance(node, dict):
            combined_text = " ".join(_safe_str(v) for v in node.values() if isinstance(v, (str, int, float, bool)))
            evidence_classification, matches = _classify_text_evidence(combined_text, node)
            if evidence_classification:
                records.append(
                    {
                        "channel_id": _extract_channel(node, path),
                        "channel_name": _safe_str(node.get("channel_name") or node.get("channel")),
                        "content_id": _safe_str(node.get("content_id")),
                        "run_id": _safe_str(node.get("run_id")),
                        "video_or_short_id": _safe_str(node.get("video_id") or node.get("short_video_id") or node.get("youtube_video_id")),
                        "publication_status": _safe_str(node.get("status") or node.get("final_status") or "REVIEW_REQUIRED"),
                        "title_or_topic": _safe_str(node.get("title") or node.get("topic") or node.get("selected_topic")),
                        "selected_asset": _safe_str(node.get("asset") or node.get("asset_url") or node.get("thumbnail_path") or node.get("video_path")),
                        "prompt_or_query": _safe_str(node.get("query") or node.get("query_used") or node.get("original_query") or node.get("effective_query") or node.get("thumbnail_prompt")),
                        "provider": _safe_str(node.get("provider") or node.get("source")),
                        "fallback_or_cache_status": _safe_str(node.get("fallback_reason") or node.get("fallback_used") or node.get("cache_status")),
                        "unsafe_content_reason": ",".join(matches),
                        "evidence_classification": evidence_classification,
                        "confidence": evidence_classification.lower(),
                        "evidence_path": str(path),
                    }
                )
            for value in node.values():
                walk(value, node)
        elif isinstance(node, list):
            for value in node:
                walk(value, parent)

    walk(payload)
    return records


def scan_roots(roots: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _iter_files(roots):
        if path.suffix.lower() == ".json":
            payload = _load_json(path)
            if payload is not None:
                records.extend(_flatten_json_records(payload, path))
                continue
        if path.suffix.lower() == ".jsonl":
            payload = _load_jsonl(path)
            if payload:
                records.extend(_flatten_json_records(payload, path))
                continue
        text = _read_text(path)
        if not text:
            continue
        evidence_classification, matches = _classify_text_evidence(text)
        if not evidence_classification:
            continue
        records.append(
            {
                "channel_id": "unknown",
                "channel_name": "",
                "content_id": "",
                "run_id": "",
                "video_or_short_id": "",
                "publication_status": "REVIEW_REQUIRED",
                "title_or_topic": "",
                "selected_asset": "",
                "prompt_or_query": "",
                "provider": "",
                "fallback_or_cache_status": "",
                "unsafe_content_reason": ",".join(matches),
                "evidence_classification": evidence_classification,
                "confidence": evidence_classification.lower(),
                "evidence_path": str(path),
            }
        )
    return records


def _classify(record: dict[str, Any]) -> str:
    evidence_classification = _safe_str(record.get("evidence_classification"))
    if evidence_classification == "BENIGN_FALSE_POSITIVE":
        return "BENIGN_FALSE_POSITIVE"
    if evidence_classification == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    if evidence_classification == "MISSING_EVIDENCE" or not evidence_classification:
        return "MISSING_EVIDENCE"
    status = _safe_str(record.get("publication_status")).lower()
    video_id = _safe_str(record.get("video_or_short_id"))
    if video_id or "published" in status or "success" in status:
        return "UNSAFE_PUBLISHED"
    if "quarantined" in status:
        return "UNSAFE_UNPUBLISHED"
    return "REVIEW_REQUIRED"


def write_outputs(records: list[dict[str, Any]], output_dir: Path) -> dict[str, str | int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    inventory = []
    high_confidence = []
    review_required = []
    false_positive = []
    published_review = []
    unpublished_quarantine = []
    for record in records:
        row = dict(record)
        row["classification"] = _classify(row)
        row["generated_at"] = generated_at
        inventory.append(row)
        if row.get("evidence_classification") in {"TEXT_CONFIRMED_HIGH_CONFIDENCE", "VISUALLY_CONFIRMED_UNSAFE"}:
            high_confidence.append(row)
        elif row.get("evidence_classification") in {"REVIEW_REQUIRED", "MISSING_EVIDENCE"}:
            review_required.append(row)
        elif row.get("evidence_classification") == "BENIGN_FALSE_POSITIVE":
            false_positive.append(row)
        else:
            review_required.append({**row, "classification": "MISSING_EVIDENCE"})

        if row["classification"] == "UNSAFE_PUBLISHED":
            published_review.append(
                {
                    "channel_id": row.get("channel_id", ""),
                    "video_or_short_id": row.get("video_or_short_id", ""),
                    "title": row.get("title_or_topic", ""),
                    "timestamp": generated_at,
                    "location": "thumbnail_or_video_body_review_required",
                    "unsafe_asset_evidence": row.get("selected_asset") or row.get("evidence_path"),
                    "recommended_remediation": "operator_review_thumbnail_replacement_or_video_edit_reupload_required",
                    "evidence_path": row.get("evidence_path", ""),
                    "unsafe_content_reason": row.get("unsafe_content_reason", ""),
                }
            )
        elif row["classification"] == "UNSAFE_UNPUBLISHED":
            unpublished_quarantine.append(row)

    inventory_path = output_dir / "visual_safety_incident_inventory.json"
    high_confidence_path = output_dir / "high_confidence_unsafe_visuals.json"
    review_required_path = output_dir / "review_required_visuals.json"
    false_positive_path = output_dir / "false_positive_visual_terms.json"
    published_review_path = output_dir / "published_visual_safety_review.json"
    unpublished_quarantine_path = output_dir / "unpublished_visual_quarantine_inventory.json"
    csv_path = output_dir / "visual_safety_incident_inventory.csv"
    inventory_path.write_text(json.dumps({"generated_at": generated_at, "items": inventory}, ensure_ascii=False, indent=2), encoding="utf-8")
    high_confidence_path.write_text(json.dumps({"generated_at": generated_at, "items": high_confidence}, ensure_ascii=False, indent=2), encoding="utf-8")
    review_required_path.write_text(json.dumps({"generated_at": generated_at, "items": review_required}, ensure_ascii=False, indent=2), encoding="utf-8")
    false_positive_path.write_text(json.dumps({"generated_at": generated_at, "items": false_positive}, ensure_ascii=False, indent=2), encoding="utf-8")
    published_review_path.write_text(json.dumps({"generated_at": generated_at, "items": published_review}, ensure_ascii=False, indent=2), encoding="utf-8")
    unpublished_quarantine_path.write_text(json.dumps({"generated_at": generated_at, "items": unpublished_quarantine}, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = sorted({key for row in inventory for key in row.keys()}) or ["generated_at"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(inventory)
    return {
        "inventory_path": str(inventory_path),
        "high_confidence_unsafe_path": str(high_confidence_path),
        "review_required_path": str(review_required_path),
        "false_positive_path": str(false_positive_path),
        "published_review_path": str(published_review_path),
        "unpublished_quarantine_path": str(unpublished_quarantine_path),
        "csv_path": str(csv_path),
        "inventory_count": len(inventory),
        "high_confidence_unsafe_count": len(high_confidence),
        "review_required_count": len(review_required),
        "false_positive_count": len(false_positive),
        "published_review_count": len(published_review),
        "unpublished_quarantine_count": len(unpublished_quarantine),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    roots = [Path(item) for item in args.root]
    records = scan_roots(roots)
    summary = write_outputs(records, Path(args.output_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())