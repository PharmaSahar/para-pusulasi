from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass
class Finding:
    severity: str
    source: str
    channel_id: str
    niche: str
    title: str
    reason: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "source": self.source,
            "channel_id": self.channel_id,
            "niche": self.niche,
            "title": self.title,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _channel_niches(registry: dict[str, Any]) -> dict[str, str]:
    channels = dict(registry.get("channels") or {})
    out: dict[str, str] = {}
    for cid, cfg in channels.items():
        out[str(cid)] = str((cfg or {}).get("niche") or "")
    return out


def _forbidden_for_niche(niche: str) -> list[str]:
    niche = (niche or "").strip().lower()
    finance = [
        "bist", "borsa", "hisse", "bitcoin", "ethereum", "kripto", "dolar", "usd", "kur", "yatirim", "temettu",
    ]
    health = ["doktor", "hastane", "tedavi", "diyet", "beslenme", "saglik", "sağlık"]
    if niche == "saglik":
        return finance
    if niche in {"borsa", "kripto", "kisisel_finans"}:
        return health
    if niche in {"egitim", "kariyer", "teknoloji"}:
        return ["bitcoin", "borsa", "hisse", "usd", "dolar"]
    return []


def _classify_title(channel_id: str, niche: str, title: str) -> Finding | None:
    text = (title or "").lower()
    if not text.strip():
        return None
    hits = [kw for kw in _forbidden_for_niche(niche) if kw in text]
    if not hits:
        return None
    sev = "P0" if niche == "saglik" else "P1"
    return Finding(
        severity=sev,
        source="title_classifier",
        channel_id=channel_id,
        niche=niche,
        title=title,
        reason=f"forbidden_keyword_hits:{','.join(hits[:5])}",
        evidence={"keyword_hits": hits[:10]},
    )


def _scan_queue(queue_data: dict[str, Any], niches: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for channel_id, entries in dict(queue_data or {}).items():
        niche = niches.get(str(channel_id), "")
        for idx, entry in enumerate(list(entries or [])):
            title = str((entry or {}).get("title") or "")
            classified = _classify_title(channel_id=str(channel_id), niche=niche, title=title)
            if classified:
                classified.source = "queue"
                classified.evidence["queue_index"] = idx
                classified.evidence["queue_status"] = str((entry or {}).get("status") or "")
                classified.evidence["youtube_url"] = str((entry or {}).get("youtube_url") or "")
                findings.append(classified)
            reasons = list((entry or {}).get("guard_reason_codes") or [])
            if "channel_dna_mismatch" in reasons:
                findings.append(
                    Finding(
                        severity="P1",
                        source="queue_guard",
                        channel_id=str(channel_id),
                        niche=niche,
                        title=title,
                        reason="queue_marked_channel_dna_mismatch",
                        evidence={
                            "guard_reason_codes": reasons,
                            "quarantine_reason": str((entry or {}).get("quarantine_reason") or ""),
                        },
                    )
                )
    return findings


def _scan_telemetry(telemetry_files: list[Path], niches: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    for file_path in telemetry_files:
        for row in _load_jsonl(file_path):
            if str(row.get("event_type") or "") != "stage_completed":
                continue
            if str(row.get("stage") or "") != "content_generation":
                continue
            payload = dict(row.get("payload") or {})
            title = str(payload.get("title") or "")
            channel_id = str(row.get("channel_id") or "")
            if not channel_id:
                continue
            niche = niches.get(channel_id, "")
            classified = _classify_title(channel_id=channel_id, niche=niche, title=title)
            if classified:
                classified.source = "telemetry"
                classified.evidence["telemetry_file"] = file_path.as_posix()
                classified.evidence["run_id"] = str(row.get("run_id") or "")
                classified.evidence["content_id"] = str(row.get("content_id") or "")
                findings.append(classified)
    return findings


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    out: list[Finding] = []
    for f in findings:
        key = "|".join([f.source, f.channel_id, f.title, f.reason])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    out.sort(key=lambda x: (SEVERITY_ORDER.get(x.severity, 9), x.channel_id, x.source, x.title))
    return out


def _known_incident_line(findings: list[Finding], target_video_id: str) -> dict[str, Any]:
    # If the exact video id is absent in local artifacts, provide nearest local evidence.
    for f in findings:
        url = str((f.evidence or {}).get("youtube_url") or "")
        if target_video_id and target_video_id in url:
            return {
                "matched": True,
                "reason": "exact_video_id_found",
                "finding": f.to_dict(),
            }
    return {
        "matched": False,
        "reason": "exact_video_id_not_found_in_local_logs",
        "nearest_health_findings": [f.to_dict() for f in findings if f.channel_id == "saglik_pusulasi"][:5],
    }


def run_scan(workspace: Path, incident_dir: Path, target_video_id: str) -> dict[str, Any]:
    registry = _load_json(workspace / "channels" / "channel_registry.json", {"channels": {}})
    queue_data = _load_json(workspace / "output" / "queue" / "channel_queue.json", {})
    niches = _channel_niches(registry)

    telemetry_files = sorted((workspace / "output" / "telemetry").glob("events-*.jsonl"))
    findings = _scan_queue(queue_data=queue_data, niches=niches)
    findings.extend(_scan_telemetry(telemetry_files=telemetry_files, niches=niches))
    findings = _dedupe_findings(findings)

    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    by_channel: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
        by_channel[f.channel_id] = by_channel.get(f.channel_id, 0) + 1

    incident = {
        "schema_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_video_id": target_video_id,
        "counts": counts,
        "channels_with_findings": by_channel,
        "findings": [f.to_dict() for f in findings],
        "known_incident": _known_incident_line(findings=findings, target_video_id=target_video_id),
    }

    incident_dir.mkdir(parents=True, exist_ok=True)
    (incident_dir / "cross_channel_audit.json").write_text(
        json.dumps(incident, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    known = incident["known_incident"]
    known_lines = [
        "# Known Incident Report",
        "",
        f"- Target video id: {target_video_id or 'N/A'}",
        f"- Exact match in local artifacts: {known.get('matched')}",
        f"- Resolution status: {known.get('reason')}",
    ]
    if not known.get("matched"):
        known_lines.extend([
            "",
            "## Nearest Local Evidence",
        ])
        for row in list(known.get("nearest_health_findings") or []):
            known_lines.append(
                f"- [{row.get('severity')}] {row.get('channel_id')} :: {row.get('title')} ({row.get('reason')})"
            )

    (incident_dir / "known_incident_report.md").write_text("\n".join(known_lines) + "\n", encoding="utf-8")
    return incident


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-channel contamination scanner")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--incident-dir",
        default="artifacts/incidents/cross_channel_contamination",
    )
    parser.add_argument("--target-video-id", default="keE2dAsUjFQ")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    incident_dir = (workspace / args.incident_dir).resolve()
    incident = run_scan(workspace=workspace, incident_dir=incident_dir, target_video_id=args.target_video_id)
    print(
        json.dumps(
            {
                "counts": incident.get("counts"),
                "incident_dir": incident_dir.as_posix(),
                "findings": len(incident.get("findings") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
