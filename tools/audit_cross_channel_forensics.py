from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any


DEFAULT_PHASH_DISTANCE_THRESHOLD = 6
_SHORT_SHA_MIN_LEN = 7
_HEX_RE = re.compile(r"^[0-9a-f]+$")


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def classify_release_sha(record_sha: str, target_sha: str) -> str:
    """Classify forensic record release SHA against the deployment target SHA.

    Contract:
    - Forensic records may store short SHA (e.g. 7 chars) or full 40-char SHA.
    - Empty record SHA is UNKNOWN_RELEASE.
    - Malformed SHA is INVALID_SHA_FORMAT.
    - Full SHA must match exactly.
    - Short SHA matches when it equals target prefix of equal length.
    """

    record = str(record_sha or "").strip().lower()
    target = str(target_sha or "").strip().lower()

    if not record:
        return "UNKNOWN_RELEASE"

    # Prevent false positives from tiny prefixes and reject non-hex strings.
    if not _HEX_RE.fullmatch(record) or len(record) < _SHORT_SHA_MIN_LEN or len(record) > 40:
        return "INVALID_SHA_FORMAT"

    if not _HEX_RE.fullmatch(target) or len(target) != 40:
        return "UNKNOWN_RELEASE"

    if len(record) == 40:
        return "CURRENT_RELEASE" if record == target else "OLDER_RELEASE"

    # Short SHA contract: compare with same-length target prefix.
    return "CURRENT_RELEASE" if record == target[: len(record)] else "OLDER_RELEASE"


def build_release_identity_report(records: list[dict[str, Any]], *, target_sha: str) -> dict[str, Any]:
    classified: list[dict[str, Any]] = []
    counts = {
        "CURRENT_RELEASE": 0,
        "OLDER_RELEASE": 0,
        "UNKNOWN_RELEASE": 0,
        "INVALID_SHA_FORMAT": 0,
    }

    for record in records:
        release_sha = str(record.get("release_sha") or "")
        classification = classify_release_sha(release_sha, target_sha)
        counts[classification] = counts.get(classification, 0) + 1
        classified.append(
            {
                "path": str(record.get("_path") or ""),
                "channel_id": str(record.get("channel_id") or ""),
                "run_id": str(record.get("run_id") or ""),
                "content_id": str(record.get("content_id") or ""),
                "release_sha": release_sha,
                "release_sha_length": len(release_sha),
                "release_classification": classification,
            }
        )

    return {
        "target_sha": str(target_sha or ""),
        "summary": {
            "records_analyzed": len(records),
            "current_release_records": counts["CURRENT_RELEASE"],
            "older_release_records": counts["OLDER_RELEASE"],
            "unknown_release_records": counts["UNKNOWN_RELEASE"],
            "invalid_sha_format_records": counts["INVALID_SHA_FORMAT"],
            "any_current_release_record": counts["CURRENT_RELEASE"] > 0,
        },
        "records": classified,
    }


def _iter_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for path in sorted(root.rglob("*.forensic.v1.json")):
        payload = _safe_read_json(path)
        if not payload:
            continue
        payload["_path"] = str(path)
        records.append(payload)
    return records


def _to_set(values: Any) -> set[str]:
    return {str(v) for v in (values or []) if str(v).strip()}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _hamming_distance_hex(a: str, b: str) -> int:
    try:
        ai = int(a, 16)
        bi = int(b, 16)
    except Exception:
        return 1_000_000
    return (ai ^ bi).bit_count()


def _extract_first_scene_fingerprint(record: dict[str, Any]) -> str | None:
    scenes = list(record.get("scene_order") or [])
    if not scenes:
        return None
    first = scenes[0]
    if not isinstance(first, dict):
        return None
    value = str(first.get("asset_fingerprint") or "").strip()
    return value or None


def _scene_sequence(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in list(record.get("scene_order") or []):
        if not isinstance(item, dict):
            continue
        fp = str(item.get("asset_fingerprint") or "").strip()
        out.append(fp)
    return out


def _sequence_overlap_ratio(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    pairs = list(zip(a, b))
    if not pairs:
        return 0.0
    comparable = [1 for left, right in pairs if left or right]
    if not comparable:
        return 0.0
    same = sum(1 for left, right in pairs if left and right and left == right)
    return same / len(comparable)


@dataclass
class PairFinding:
    channel_a: str
    channel_b: str
    same_channel: bool
    affected_records: list[dict[str, str]]
    shared_provider_asset_ids: list[str]
    shared_asset_fingerprints: list[str]
    shared_perceptual_hashes_exact: list[str]
    shared_perceptual_hashes_near: list[dict[str, Any]]
    shared_thumbnail_hashes: list[str]
    shared_render_hashes: list[str]
    shared_first_scene_fingerprints: list[str]
    shared_exact_scene_sequences: bool
    high_scene_sequence_overlap: bool
    scene_sequence_overlap_ratio: float
    shared_media_queries: list[str]
    shared_thumbnail_prompts: list[str]
    shared_cache_provenance_keys: list[str]
    severity: str
    confidence: str
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_a": self.channel_a,
            "channel_b": self.channel_b,
            "same_channel": self.same_channel,
            "affected_records": self.affected_records,
            "shared_provider_asset_ids": self.shared_provider_asset_ids,
            "shared_asset_fingerprints": self.shared_asset_fingerprints,
            "shared_perceptual_hashes_exact": self.shared_perceptual_hashes_exact,
            "shared_perceptual_hashes_near": self.shared_perceptual_hashes_near,
            "shared_thumbnail_hashes": self.shared_thumbnail_hashes,
            "shared_render_hashes": self.shared_render_hashes,
            "shared_first_scene_fingerprints": self.shared_first_scene_fingerprints,
            "shared_exact_scene_sequences": self.shared_exact_scene_sequences,
            "high_scene_sequence_overlap": self.high_scene_sequence_overlap,
            "scene_sequence_overlap_ratio": round(self.scene_sequence_overlap_ratio, 4),
            "shared_media_queries": self.shared_media_queries,
            "shared_thumbnail_prompts": self.shared_thumbnail_prompts,
            "shared_cache_provenance_keys": self.shared_cache_provenance_keys,
            "severity": self.severity,
            "confidence": self.confidence,
            "classification": self.classification,
        }


def _pair_compare(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    phash_distance_threshold: int,
) -> PairFinding:
    channel_a = str(a.get("channel_id") or "")
    channel_b = str(b.get("channel_id") or "")
    same_channel = channel_a == channel_b

    provider_a = _to_set(a.get("provider_asset_ids"))
    provider_b = _to_set(b.get("provider_asset_ids"))
    shared_provider = sorted(provider_a & provider_b)

    fp_a = _to_set(a.get("asset_fingerprints"))
    fp_b = _to_set(b.get("asset_fingerprints"))
    shared_fingerprints = sorted(fp_a & fp_b)

    phash_a = {
        str(item.get("value") or "").strip()
        for item in list(a.get("perceptual_hashes") or [])
        if isinstance(item, dict) and str(item.get("status") or "") == "ok" and str(item.get("value") or "").strip()
    }
    phash_b = {
        str(item.get("value") or "").strip()
        for item in list(b.get("perceptual_hashes") or [])
        if isinstance(item, dict) and str(item.get("status") or "") == "ok" and str(item.get("value") or "").strip()
    }
    shared_phash_exact = sorted(phash_a & phash_b)

    shared_phash_near: list[dict[str, Any]] = []
    for pa in sorted(phash_a):
        for pb in sorted(phash_b):
            if pa == pb:
                continue
            dist = _hamming_distance_hex(pa, pb)
            if dist <= phash_distance_threshold:
                shared_phash_near.append({"a": pa, "b": pb, "distance": int(dist)})

    thumb_a = str(a.get("thumbnail_hash") or "").strip()
    thumb_b = str(b.get("thumbnail_hash") or "").strip()
    shared_thumbnails = [thumb_a] if thumb_a and thumb_a == thumb_b else []

    render_a = str(a.get("render_hash") or "").strip()
    render_b = str(b.get("render_hash") or "").strip()
    shared_renders = [render_a] if render_a and render_a == render_b else []

    first_a = _extract_first_scene_fingerprint(a)
    first_b = _extract_first_scene_fingerprint(b)
    shared_first_scene = [first_a] if first_a and first_a == first_b else []

    seq_a = _scene_sequence(a)
    seq_b = _scene_sequence(b)
    same_sequence = bool(seq_a and seq_b and seq_a == seq_b)
    overlap_ratio = _sequence_overlap_ratio(seq_a, seq_b)
    high_overlap = overlap_ratio >= 0.75

    media_a = {_normalize_text(x) for x in list(a.get("media_queries") or []) if str(x).strip()}
    media_b = {_normalize_text(x) for x in list(b.get("media_queries") or []) if str(x).strip()}
    shared_media_queries = sorted(x for x in (media_a & media_b) if x)

    prompt_a = _normalize_text(a.get("thumbnail_prompt") or "")
    prompt_b = _normalize_text(b.get("thumbnail_prompt") or "")
    shared_prompts = [prompt_a] if prompt_a and prompt_a == prompt_b else []

    cache_a = {json.dumps(item, sort_keys=True) for item in list(a.get("cache_provenance") or []) if isinstance(item, dict)}
    cache_b = {json.dumps(item, sort_keys=True) for item in list(b.get("cache_provenance") or []) if isinstance(item, dict)}
    shared_cache = sorted(cache_a & cache_b)

    strong_exact = bool(
        shared_provider
        or shared_fingerprints
        or shared_phash_exact
        or shared_thumbnails
        or shared_renders
        or same_sequence
    )

    near_duplicate = bool(shared_phash_near)

    if strong_exact:
        severity = "high"
        confidence = "high"
        classification = "exact_duplicate"
    elif near_duplicate or high_overlap:
        severity = "medium"
        confidence = "medium"
        classification = "perceptual_near_duplicate"
    elif shared_media_queries or shared_prompts or shared_cache:
        severity = "low"
        confidence = "low"
        classification = "insufficient_evidence"
    else:
        severity = "none"
        confidence = "low"
        classification = "insufficient_evidence"

    if same_channel and classification != "insufficient_evidence":
        classification = "expected_same_channel_reuse"

    affected_records = [
        {
            "channel_id": channel_a,
            "run_id": str(a.get("run_id") or ""),
            "content_id": str(a.get("content_id") or ""),
            "path": str(a.get("_path") or ""),
        },
        {
            "channel_id": channel_b,
            "run_id": str(b.get("run_id") or ""),
            "content_id": str(b.get("content_id") or ""),
            "path": str(b.get("_path") or ""),
        },
    ]

    return PairFinding(
        channel_a=channel_a,
        channel_b=channel_b,
        same_channel=same_channel,
        affected_records=affected_records,
        shared_provider_asset_ids=shared_provider,
        shared_asset_fingerprints=shared_fingerprints,
        shared_perceptual_hashes_exact=shared_phash_exact,
        shared_perceptual_hashes_near=shared_phash_near,
        shared_thumbnail_hashes=shared_thumbnails,
        shared_render_hashes=shared_renders,
        shared_first_scene_fingerprints=shared_first_scene,
        shared_exact_scene_sequences=same_sequence,
        high_scene_sequence_overlap=high_overlap,
        scene_sequence_overlap_ratio=overlap_ratio,
        shared_media_queries=shared_media_queries,
        shared_thumbnail_prompts=shared_prompts,
        shared_cache_provenance_keys=shared_cache,
        severity=severity,
        confidence=confidence,
        classification=classification,
    )


def build_report(records: list[dict[str, Any]], *, phash_distance_threshold: int) -> dict[str, Any]:
    findings: list[PairFinding] = []
    for left, right in combinations(records, 2):
        findings.append(_pair_compare(left, right, phash_distance_threshold=phash_distance_threshold))

    by_channel: dict[str, int] = defaultdict(int)
    matrix: dict[str, dict[str, str]] = defaultdict(dict)
    for row in findings:
        pair_key = row.classification
        matrix[row.channel_a][row.channel_b] = pair_key
        matrix[row.channel_b][row.channel_a] = pair_key
        if row.classification not in {"insufficient_evidence", "expected_same_channel_reuse"}:
            by_channel[row.channel_a] += 1
            by_channel[row.channel_b] += 1

    summary = {
        "records_analyzed": len(records),
        "pairs_analyzed": len(findings),
        "exact_duplicate_pairs": sum(1 for x in findings if x.classification == "exact_duplicate"),
        "perceptual_near_duplicate_pairs": sum(1 for x in findings if x.classification == "perceptual_near_duplicate"),
        "cross_channel_pairs_with_findings": sum(
            1
            for x in findings
            if (x.channel_a != x.channel_b and x.classification in {"exact_duplicate", "perceptual_near_duplicate"})
        ),
        "affected_channels": sorted([k for k, v in by_channel.items() if v > 0]),
        "phash_distance_threshold": int(phash_distance_threshold),
    }

    return {
        "summary": summary,
        "channel_pair_matrix": {k: dict(v) for k, v in matrix.items()},
        "findings": [item.to_dict() for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only cross-channel forensic auditor")
    parser.add_argument("--root", default="output/forensics/generation", help="Root directory of forensic records")
    parser.add_argument("--successful-only", action="store_true", help="Only include generation_result=success records")
    parser.add_argument("--phash-distance-threshold", type=int, default=DEFAULT_PHASH_DISTANCE_THRESHOLD)
    parser.add_argument("--json-out", default="", help="Optional path to write JSON report")
    parser.add_argument(
        "--target-sha",
        default="",
        help="Optional full 40-character target SHA to classify forensic record release_sha values",
    )
    args = parser.parse_args()

    records = _iter_records(Path(args.root))
    if args.successful_only:
        records = [r for r in records if str(r.get("generation_result") or "").lower() == "success"]

    report = build_report(records, phash_distance_threshold=max(0, int(args.phash_distance_threshold)))

    if str(args.target_sha or "").strip():
        report["release_identity"] = build_release_identity_report(records, target_sha=str(args.target_sha or ""))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))

    summary = report["summary"]
    print(
        "AUDIT SUMMARY "
        f"records={summary['records_analyzed']} "
        f"pairs={summary['pairs_analyzed']} "
        f"exact={summary['exact_duplicate_pairs']} "
        f"near={summary['perceptual_near_duplicate_pairs']} "
        f"cross_channel={summary['cross_channel_pairs_with_findings']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
