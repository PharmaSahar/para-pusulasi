from __future__ import annotations

from pathlib import Path

from src.fact_check_audit import build_failed_fact_check_audit, classify_failed_fact_check, parse_failed_fact_check_events


def test_classify_stale_fx_claim():
    failure_kind, claim_type = classify_failed_fact_check(
        "failed_fact_check: USD/TRY stale claim: script='dolar TL yıl sonunda 38-42 TL' live=46.86 outside [34.96, 45.36]"
    )

    assert failure_kind == "stale_fx_claim"
    assert claim_type == "fx_usd_try"


def test_classify_unverifiable_claim_with_claim_type():
    failure_kind, claim_type = classify_failed_fact_check(
        "failed_fact_check: unverifiable_volatile_claim: 'Bitcoin 150.000' (crypto)"
    )

    assert failure_kind == "unverifiable_volatile_claim"
    assert claim_type == "crypto"


def test_parse_failed_fact_check_events_uses_scheduler_fatal_lines_only():
    log_text = "\n".join(
        [
            "2026-07-08 22:35:40,647 [ERROR] Scheduler: [Saglik Pusulasi] Fatal hata (retry yok): failed_fact_check: unverifiable_volatile_claim: 'hisse 47' (stock)",
            "2026-07-08 22:35:40,647 [ERROR] Scheduler: [Saglik Pusulasi] Render hatası: failed_fact_check: unverifiable_volatile_claim: 'hisse 47' (stock)",
            "2026-07-08 22:37:16,930 [ERROR] Scheduler: [Teknoloji Pusulasi] Fatal hata (retry yok): failed_fact_check: USD/TRY stale claim: script='dolar TL yıl sonunda 38-42 TL' live=46.86 outside [34.96, 45.36]",
        ]
    )

    events = parse_failed_fact_check_events(log_text)

    assert len(events) == 2
    assert events[0]["channel"] == "Saglik Pusulasi"
    assert events[0]["claim_type"] == "stock"
    assert events[1]["failure_kind"] == "stale_fx_claim"


def test_build_failed_fact_check_audit_summarizes_log(tmp_path: Path):
    log_path = tmp_path / "production_scheduler.out"
    log_path.write_text(
        "\n".join(
            [
                "2026-07-08 22:35:40,647 [ERROR] Scheduler: [Saglik Pusulasi] Fatal hata (retry yok): failed_fact_check: unverifiable_volatile_claim: 'hisse 47' (stock)",
                "2026-07-08 22:37:16,930 [ERROR] Scheduler: [Teknoloji Pusulasi] Fatal hata (retry yok): failed_fact_check: USD/TRY stale claim: script='dolar TL yıl sonunda 38-42 TL' live=46.86 outside [34.96, 45.36]",
                "2026-07-08 22:39:06,006 [ERROR] Scheduler: [Egitim Rehberi] Fatal hata (retry yok): failed_fact_check: unverifiable_volatile_claim: 'BIST 100' (stock)",
            ]
        ),
        encoding="utf-8",
    )

    summary = build_failed_fact_check_audit(log_path, max_examples=2)

    assert summary["total_failed_fact_checks"] == 3
    assert summary["counts_by_failure_kind"] == {
        "stale_fx_claim": 1,
        "unverifiable_volatile_claim": 2,
    }
    assert summary["counts_by_claim_type"] == {
        "fx_usd_try": 1,
        "stock": 2,
    }
    assert summary["counts_by_channel"] == {
        "Egitim Rehberi": 1,
        "Saglik Pusulasi": 1,
        "Teknoloji Pusulasi": 1,
    }
    assert len(summary["examples"]) == 2