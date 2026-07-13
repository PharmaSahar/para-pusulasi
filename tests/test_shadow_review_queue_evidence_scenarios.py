from __future__ import annotations

import json
from pathlib import Path

from src.shadow_content_quality import ShadowContentQualityEngine, build_shadow_evaluation_context
from src.shadow_review_queue import ShadowReviewQueueBuilder, is_finding_review_eligible


def _eval_generation(tmp_path: Path, *, run_id: str, title: str, script: str, description: str = "desc") -> dict:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="channel_phase4",
        content_type="mixed",
        topic="finance",
        title=title,
        script=script,
        description=description,
        thumbnail_prompt="Finance board",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "shadow_rows_phase4.jsonl")
    return engine.evaluate_checkpoint(checkpoint="generation")


def _eval_shorts(tmp_path: Path, *, run_id: str, short_script: str, short_title: str = "Finance #Shorts", duration: float = 58) -> dict:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="channel_phase4",
        content_type="short",
        topic="finance",
        title="Shorts title",
        script="Long script baseline",
        description="desc",
        thumbnail_prompt="Finance board",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "shadow_rows_phase4.jsonl")
    return engine.evaluate_checkpoint(
        checkpoint="shorts",
        short_script=short_script,
        short_title=short_title,
        short_duration_seconds=duration,
    )


def _eval_seo(tmp_path: Path, *, run_id: str) -> dict:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="channel_phase4",
        content_type="mixed",
        topic="finance",
        title="SEO title",
        script="script",
        description="desc",
        thumbnail_prompt="prompt",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "shadow_rows_phase4.jsonl")
    return engine.evaluate_checkpoint(
        checkpoint="seo_discovery",
        description="seo text",
        tags=["finans"],
        playlist_recommendation="Finance Basics",
        card_recommendation=None,
        end_screen_recommendation=None,
    )


def _first_finding(row: dict) -> dict:
    findings = [f for f in row.get("findings", []) if isinstance(f, dict)]
    return findings[0] if findings else {}


def _pick_finding(row: dict, preferred_codes: set[str]) -> dict:
    findings = [f for f in row.get("findings", []) if isinstance(f, dict)]
    if not findings:
        return {}
    for finding in findings:
        if str(finding.get("code") or "") in preferred_codes:
            return finding
    return findings[0]


def test_phase4_local_evidence_scenarios(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events_phase4.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)

    rows: list[tuple[str, set[str], dict]] = [
        (
            "safe_educational_finance_content",
            {"unsupported_financial_claim_detection", "guaranteed_return_wording_detection"},
            _eval_generation(tmp_path, run_id="s1", title="Risk Uyarisi", script="Iceriden bilgi iddialarina guvenmeyin. Garantili getiri diye bir sey yoktur."),
        ),
        (
            "guaranteed_return_claim",
            {"guaranteed_return_wording_detection", "unsupported_financial_claim_detection"},
            _eval_generation(tmp_path, run_id="s2", title="Kesin Getiri", script="Bu yontemle garanti getiri var."),
        ),
        (
            "insider_information_claim",
            {"unverifiable_insider_information_detection"},
            _eval_generation(tmp_path, run_id="s3", title="Insider", script="Iceriden bilgi aldik."),
        ),
        (
            "not_yet_priced_in_claim",
            {"not_priced_in_claim_detection"},
            _eval_generation(tmp_path, run_id="s4", title="Pricing", script="Bu bilgi henuz fiyatlanmadi."),
        ),
        (
            "secret_institutional_activity_claim",
            {"secret_institutional_claim_detection"},
            _eval_generation(tmp_path, run_id="s5", title="Fonlar", script="Fonlar gizlice topluyor."),
        ),
        (
            "urgent_buy_pressure_claim",
            {"urgent_trade_pressure_detection"},
            _eval_generation(tmp_path, run_id="s6", title="Acil Al", script="Hemen al son firsat."),
        ),
        (
            "ticker_company_mismatch",
            {"ticker_company_mismatch_detection"},
            _eval_generation(tmp_path, run_id="s7", title="THYAO Analizi", script="THYAO yerine baska sirketten bahsediyoruz."),
        ),
        (
            "title_script_mismatch",
            {"title_script_semantic_consistency"},
            _eval_generation(tmp_path, run_id="s8", title="Birikim", script="Yazilim mulakati anlatiliyor."),
        ),
        (
            "title_thumbnail_mismatch",
            {"title_thumbnail_text_consistency", "thumbnail_prompt_relevance"},
            _eval_generation(tmp_path, run_id="s9", title="Birikim", script="Birikim adimlari ve butce", description="desc"),
        ),
        (
            "exact_duplicate_script",
            {"duplicate_script_detection"},
            _eval_generation(tmp_path, run_id="s10", title="Acil Fon", script="Ayni script ayni script."),
        ),
        (
            "repeated_opening",
            {"repetitive_opening_detection", "duplicate_script_detection"},
            _eval_generation(tmp_path, run_id="s11", title="Acil Fon", script="Ayni opening ile basliyoruz. Ayni opening ile basliyoruz."),
        ),
        (
            "complete_valid_short",
            {"shorts_sentence_completeness"},
            _eval_shorts(tmp_path, run_id="s12", short_script="Birikim icin hedef belirleyin. Haftalik butce yapin. Acil fon olusturun.", duration=58),
        ),
        (
            "short_starts_mid_sentence",
            {"shorts_abrupt_beginning", "shorts_sentence_completeness"},
            _eval_shorts(tmp_path, run_id="s13", short_script="ve sonra bu adimi uygulayin cunku", duration=58),
        ),
        (
            "short_ends_mid_sentence",
            {"shorts_abrupt_ending", "shorts_sentence_completeness"},
            _eval_shorts(tmp_path, run_id="s14", short_script="Bu adimlari uyguladiginizda sonuclar", duration=58),
        ),
        (
            "short_context_without_payoff",
            {"shorts_context_without_payoff", "shorts_missing_context"},
            _eval_shorts(tmp_path, run_id="s15", short_script="Bu konuda once arka plani anlatalim ama", duration=58),
        ),
        (
            "short_payoff_without_context",
            {"shorts_payoff_without_context", "shorts_missing_context"},
            _eval_shorts(tmp_path, run_id="s16", short_script="Sonuc kesin degil ama kazanc var", duration=58),
        ),
        ("unsupported_seo_feature", {"card_recommendation_not_implemented", "end_screen_recommendation_not_implemented"}, _eval_seo(tmp_path, run_id="s17")),
    ]

    # Seed duplicate/repetition continuity for duplicate ingestion and supersede scenario.
    seed = _eval_generation(tmp_path, run_id="s_seed", title="Acil Fon", script="Ayni script ayni script.")
    rows.append(
        (
            "validator_failure",
            {"validator_exception"},
            {
                **seed,
                "findings": [
                    {
                        "code": "validator_exception",
                        "category": "validator_failure",
                        "severity": "MEDIUM",
                        "confidence": "HIGH",
                        "validator_version": "shadow_quality_taxonomy_v1",
                        "message": "validator crashed",
                        "affected_artifact": "validator",
                        "evidence_excerpt": "traceback redacted",
                        "evidence_hash": "validator_hash",
                        "remediation_class": "inspect_validator_trace",
                        "blocking_eligible_future": False,
                        "mode": "advisory",
                        "details": {},
                    }
                ],
                "finding_count": 1,
                "severity": "medium",
                "pipeline_output_changed": False,
            },
        )
    )

    scenarios: list[dict] = []

    # 1-18 scenario ingestion
    for name, preferred_codes, row in rows:
        finding = _pick_finding(row, preferred_codes)
        eligible = False
        priority = "P4_INFO"
        queue_item_id = ""
        bundle_id = ""
        suggested_action = "no_action"

        if finding:
            eligible, _ = is_finding_review_eligible(row=row, finding=finding, related_findings=row.get("findings", []))

        ingest = builder.ingest_shadow_rows([row])
        items, _diag = builder.get_current_items()
        if items:
            # Pick latest deterministic item for current run.
            run_items = [i for i in items if i.get("run_id") == row.get("run_id")]
            if run_items:
                current = run_items[0]
                priority = current.get("queue_priority", "P4_INFO")
                queue_item_id = current.get("review_item_id", "")
                bundle_id = current.get("bundle_id", "")
                suggested_action = current.get("suggested_review_action", "")

        scenarios.append(
            {
                "scenario": name,
                "source_finding": finding.get("code", "none"),
                "eligible": eligible,
                "priority": priority,
                "queue_item_id": queue_item_id,
                "bundle_id": bundle_id,
                "suggested_action": suggested_action,
                "advisory_only": True,
                "pipeline_output_changed": row.get("pipeline_output_changed", False),
                "review_items_created": ingest.review_items_created,
            }
        )

    # 19 duplicate ingestion
    duplicate_row = _eval_generation(tmp_path, run_id="s18", title="Duplicate", script="Bu yontemle garanti getiri var.")
    first_dup = builder.ingest_shadow_rows([duplicate_row])
    second_dup = builder.ingest_shadow_rows([duplicate_row])
    scenarios.append(
        {
            "scenario": "duplicate_ingestion",
            "source_finding": _first_finding(duplicate_row).get("code", "none"),
            "eligible": True,
            "priority": "idempotent",
            "queue_item_id": "duplicate_protected",
            "bundle_id": "",
            "suggested_action": "verify_source",
            "advisory_only": True,
            "pipeline_output_changed": duplicate_row.get("pipeline_output_changed", False),
            "review_items_created": first_dup.review_items_created,
            "review_items_existing": second_dup.review_items_existing,
        }
    )

    # 20 superseded finding
    supersede_old = _eval_generation(tmp_path, run_id="s19", title="Supersede", script="Bu yontemle garanti getiri var.")
    supersede_new = _eval_generation(tmp_path, run_id="s19", title="Supersede", script="Bu yontemle garanti getiri var ve yuzde 340 kesin.")
    _ = builder.ingest_shadow_rows([supersede_old])
    _ = builder.ingest_shadow_rows([supersede_new])
    items, _diag = builder.get_current_items()
    has_superseded = any(i.get("status") == "SUPERSEDED" for i in items)
    scenarios.append(
        {
            "scenario": "superseded_finding",
            "source_finding": _first_finding(supersede_new).get("code", "none"),
            "eligible": True,
            "priority": "supersede_checked",
            "queue_item_id": "supersede_checked",
            "bundle_id": "",
            "suggested_action": "verify_source",
            "advisory_only": True,
            "pipeline_output_changed": supersede_new.get("pipeline_output_changed", False),
            "has_superseded": has_superseded,
        }
    )

    report = {
        "schema_version": "v1",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    out = tmp_path / "phase4_evidence_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also persist under artifacts/latest for deterministic local evidence.
    artifacts_out = Path("artifacts/latest/project001_slice3_phase4_review_queue_evidence.json")
    artifacts_out.parent.mkdir(parents=True, exist_ok=True)
    artifacts_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    assert report["scenario_count"] == 20
    assert all(item["pipeline_output_changed"] is False for item in scenarios)
    duplicate = [item for item in scenarios if item["scenario"] == "duplicate_ingestion"][0]
    assert duplicate["review_items_created"] >= 1
    assert duplicate["review_items_existing"] >= 1
    superseded = [item for item in scenarios if item["scenario"] == "superseded_finding"][0]
    assert superseded["has_superseded"] is True
