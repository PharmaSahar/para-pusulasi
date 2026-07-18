from __future__ import annotations

from pathlib import Path

from tools.visual_safety_incident_audit import scan_roots, write_outputs


def test_visual_safety_incident_audit_uses_required_bucket_names(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        """
        {
          "items": [
            {"channel_id": "para_pusulasi", "alt": "Woman in bikini on beach"},
            {"channel_id": "girisim_okulu", "query": "business model canvas"},
            {"channel_id": "kripto_rehber", "alt": "fashion model in resort"},
            {"channel_id": "saglik_pusulasi", "approved": false, "moderation_result": "unsafe", "asset": "unsafe.jpg"},
            {"status": "MISSING_EVIDENCE", "raw_line_preview": "{not-json"}
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    records = scan_roots([evidence])
    output = write_outputs(records, tmp_path / "audit")
    buckets = {record["evidence_classification"] for record in records}

    assert "TEXT_CONFIRMED_HIGH_CONFIDENCE" in buckets
    assert "BENIGN_FALSE_POSITIVE" in buckets
    assert "REVIEW_REQUIRED" in buckets
    assert "VISUALLY_CONFIRMED_UNSAFE" in buckets
    assert "MISSING_EVIDENCE" in buckets
    assert output["high_confidence_unsafe_count"] == 2
    assert output["review_required_count"] == 2
    assert output["false_positive_count"] == 1