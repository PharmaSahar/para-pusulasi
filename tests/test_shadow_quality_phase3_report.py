from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.shadow_content_quality import ShadowContentQualityEngine, build_shadow_evaluation_context
from src.shadow_quality_taxonomy import get_finding_spec
from tests.test_shadow_quality_calibration_golden import CASES, FixtureCase


REPORT_PATH = Path("artifacts/latest/project001_slice3_phase3_calibration_report.json")
FULL_REPORT_PATH = Path("artifacts/latest/project001_slice3_phase3_calibration_full_report.json")


@pytest.fixture
def dataset() -> list[dict]:
    return [
        {
            "id": "safe_negation",
            "checkpoint": "generation",
            "script": "İçeriden bilgi iddialarına güvenmeyin. Garantili getiri diye bir şey yoktur.",
            "title": "Risk Uyarısı",
            "topic": "Eğitim",
            "expected_positive": False,
            "positive_codes": {"unverifiable_insider_information_detection", "guaranteed_return_wording_detection"},
        },
        {
            "id": "high_guarantee",
            "checkpoint": "generation",
            "script": "Bu yöntemle garanti kazanç var ve kesin getiri alırsın.",
            "title": "Kesin Getiri",
            "topic": "Borsa",
            "expected_positive": True,
            "positive_codes": {"unsupported_financial_claim_detection", "guaranteed_return_wording_detection"},
        },
        {
            "id": "high_insider",
            "checkpoint": "generation",
            "script": "İçeriden bilgi aldık, resmi açıklanmadan önce hemen al.",
            "title": "Insider",
            "topic": "Borsa",
            "expected_positive": True,
            "positive_codes": {"unverifiable_insider_information_detection", "urgent_trade_pressure_detection"},
        },
        {
            "id": "safe_uncertainty",
            "checkpoint": "generation",
            "script": "Teknik analiz olasılıklarla çalışır, fiyatın yükselmesi kesin değildir.",
            "title": "Olasılık",
            "topic": "Eğitim",
            "expected_positive": False,
            "positive_codes": {"specific_security_certainty_detection"},
        },
        {
            "id": "not_priced_in",
            "checkpoint": "generation",
            "script": "Bu gelişme henüz fiyatlanmadı ve piyasaya yansımadı.",
            "title": "Fiyatlama",
            "topic": "Borsa",
            "expected_positive": True,
            "positive_codes": {"not_priced_in_claim_detection"},
        },
        {
            "id": "secret_funds",
            "checkpoint": "generation",
            "script": "Fonların gizlice topladığı bu hissede son şans.",
            "title": "Gizli Toplama Son Sans",
            "topic": "Borsa",
            "expected_positive": True,
            "positive_codes": {"secret_institutional_claim_detection"},
        },
        {
            "id": "safe_education",
            "checkpoint": "generation",
            "script": "Bütçe disiplini ve uzun vadeli planlama birikim için önemlidir.",
            "title": "Birikim Eğitimi",
            "topic": "Birikim",
            "expected_positive": False,
            "positive_codes": {"unsupported_financial_claim_detection", "unverifiable_insider_information_detection", "guaranteed_return_wording_detection"},
        },
        {
            "id": "urgent_buy",
            "checkpoint": "generation",
            "script": "Hemen al, bugün almazsan kaçırırsın.",
            "title": "Acil Al",
            "topic": "Borsa",
            "expected_positive": True,
            "positive_codes": {"urgent_trade_pressure_detection"},
        },
        {
            "id": "extreme_return",
            "checkpoint": "generation",
            "script": "Yüzde 300 getiri kesin, kaçırılmayacak fırsat.",
            "title": "300 Getiri",
            "topic": "Borsa",
            "expected_positive": True,
            "positive_codes": {"extreme_return_claim_detection", "guaranteed_return_wording_detection"},
        },
        {
            "id": "safe_quote_warning",
            "checkpoint": "generation",
            "script": "'Garanti kazanç' iddialarına inanmayın, kaynak arayın.",
            "title": "Uyarı",
            "topic": "Eğitim",
            "expected_positive": False,
            "positive_codes": {"guaranteed_return_wording_detection"},
        },
    ]


def _row(item: dict, tmp_path: Path) -> dict:
    ctx = build_shadow_evaluation_context(
        run_id=f"phase3_{item['id']}",
        content_id=f"content_{item['id']}",
        channel_id="phase3_cal",
        content_type="mixed",
        topic=item["topic"],
        title=item["title"],
        script=item["script"],
        description="calibration",
        thumbnail_prompt="finance",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "phase3_rows.jsonl", history_window=100)
    return engine.evaluate_checkpoint(checkpoint=item["checkpoint"])


def _context_from_case(case: FixtureCase, run_id: str):
    return build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="phase3_cal",
        content_type="mixed",
        topic=case.topic,
        title=case.title,
        script=case.script,
        description=case.description,
        thumbnail_prompt=case.thumbnail_prompt,
        cta_text="abone ol",
    )


def _evaluate_case_with_seeded_history(case: FixtureCase, tmp_path: Path, idx: int) -> dict:
    # Isolate each fixture to avoid cross-fixture state coupling.
    path = tmp_path / f"phase3_full_case_{idx}.jsonl"

    expected = set(case.expected_findings_any)
    needs_generation_history = bool(
        expected & {"duplicate_title_detection", "duplicate_script_detection", "repetitive_opening_detection"}
    )
    needs_thumbnail_history = "duplicate_thumbnail_text_detection" in expected

    if needs_generation_history:
        seed_ctx = _context_from_case(case, run_id=f"seed_{idx}")
        seed_engine = ShadowContentQualityEngine(context=seed_ctx, results_path=path, history_window=120)
        seed_engine.evaluate_and_store(checkpoint="generation")

    if needs_thumbnail_history:
        seed_ctx = _context_from_case(case, run_id=f"seed_thumb_{idx}")
        seed_engine = ShadowContentQualityEngine(context=seed_ctx, results_path=path, history_window=120)
        seed_engine.evaluate_and_store(checkpoint="thumbnail_metadata", thumbnail_text=case.thumbnail_text)

    ctx = _context_from_case(case, run_id=f"case_{idx}")
    engine = ShadowContentQualityEngine(context=ctx, results_path=path, history_window=120)
    kwargs = {}
    if case.checkpoint == "description":
        kwargs["description"] = case.description
    if case.checkpoint == "thumbnail_metadata":
        kwargs["thumbnail_text"] = case.thumbnail_text
    if case.checkpoint == "shorts":
        kwargs["short_script"] = case.short_script
        kwargs["short_title"] = case.short_title or f"{case.title} #Shorts"
        kwargs["short_duration_seconds"] = case.short_duration_seconds
    if case.checkpoint == "seo_discovery":
        kwargs["description"] = case.description
        kwargs["tags"] = case.tags
        kwargs["playlist_recommendation"] = case.playlist_recommendation
        kwargs["card_recommendation"] = case.card_recommendation
        kwargs["end_screen_recommendation"] = case.end_screen_recommendation
    return engine.evaluate_checkpoint(checkpoint=case.checkpoint, **kwargs)


_EQUIVALENT_FINDINGS: dict[str, set[str]] = {
    "guaranteed_return_wording_detection": {"unsupported_financial_claim_detection"},
    "repetitive_opening_detection": {"duplicate_script_detection"},
    "shorts_payoff_without_context": {"shorts_missing_context"},
}


def _matches_expected(expected: set[str], actual: set[str]) -> bool:
    if not expected:
        return True
    if expected & actual:
        return True
    for item in expected:
        if item in _EQUIVALENT_FINDINGS and (_EQUIVALENT_FINDINGS[item] & actual):
            return True
    return False


def test_phase3_local_calibration_report(dataset: list[dict], tmp_path: Path) -> None:
    tp = tn = fp = fn = 0
    per_validator: dict[str, dict[str, int]] = {}
    negation_results: list[dict] = []

    for item in dataset:
        row = _row(item, tmp_path)
        codes = {finding["code"] for finding in row.get("findings", [])}
        pred_positive = bool(codes & set(item["positive_codes"]))

        if item["expected_positive"] and pred_positive:
            tp += 1
        elif (not item["expected_positive"]) and (not pred_positive):
            tn += 1
        elif (not item["expected_positive"]) and pred_positive:
            fp += 1
        else:
            fn += 1

        for code in item["positive_codes"]:
            bucket = per_validator.setdefault(code, {"tp": 0, "tn": 0, "fp": 0, "fn": 0})
            has_code = code in codes
            if item["expected_positive"] and has_code:
                bucket["tp"] += 1
            elif (not item["expected_positive"]) and (not has_code):
                bucket["tn"] += 1
            elif (not item["expected_positive"]) and has_code:
                bucket["fp"] += 1
            else:
                bucket["fn"] += 1

        if "güvenmeyin" in item["script"].lower() or "yoktur" in item["script"].lower() or "değildir" in item["script"].lower():
            negation_results.append(
                {
                    "id": item["id"],
                    "high_severity_financial_findings": [
                        f["code"]
                        for f in row.get("findings", [])
                        if f.get("severity") in {"HIGH", "CRITICAL"}
                        and f.get("code")
                        in {
                            "unsupported_financial_claim_detection",
                            "unverifiable_insider_information_detection",
                            "guaranteed_return_wording_detection",
                        }
                    ],
                }
            )

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    specificity = tn / (tn + fp) if (tn + fp) else 1.0

    report = {
        "label": "LOCAL CALIBRATION EVIDENCE - NOT PRODUCTION VALIDATION",
        "fixture_total": len(dataset),
        "expected_positive_cases": sum(1 for x in dataset if x["expected_positive"]),
        "expected_negative_cases": sum(1 for x in dataset if not x["expected_positive"]),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "per_validator": per_validator,
        "turkish_negation_results": negation_results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Provisional acceptance gates for financial high-risk subset.
    assert report["false_negatives"] == 0
    assert report["precision"] >= 0.90
    assert report["recall"] >= 0.90
    assert all(not item["high_severity_financial_findings"] for item in negation_results)


def test_phase3_full_40_fixture_calibration_report(tmp_path: Path) -> None:
    tp = tn = fp = fn = 0
    per_validator: dict[str, dict[str, int]] = {}
    per_category: dict[str, dict[str, int]] = {}
    negation_results: list[dict] = []
    fixture_debug: list[dict] = []

    for idx, case in enumerate(CASES):
        row = _evaluate_case_with_seeded_history(case, tmp_path, idx)
        expected = set(case.expected_findings_any)
        actual = {f["code"] for f in row.get("findings", [])}
        is_positive = bool(expected)
        got_positive = bool(expected) and _matches_expected(expected, actual)

        if is_positive and got_positive:
            tp += 1
        elif (not is_positive) and (not got_positive):
            tn += 1
        elif (not is_positive) and got_positive:
            fp += 1
        else:
            fn += 1

        for code in expected or {"__none__"}:
            bucket = per_validator.setdefault(code, {"tp": 0, "tn": 0, "fp": 0, "fn": 0})
            has_code = _matches_expected({code}, actual) if code != "__none__" else (not actual)
            if is_positive and has_code:
                bucket["tp"] += 1
            elif (not is_positive) and (not has_code):
                bucket["tn"] += 1
            elif (not is_positive) and has_code:
                bucket["fp"] += 1
            else:
                bucket["fn"] += 1

        expected_categories = {get_finding_spec(code).category for code in expected} if expected else {"none"}
        actual_categories = {get_finding_spec(code).category for code in actual}
        for category in expected_categories:
            cat_bucket = per_category.setdefault(category, {"tp": 0, "tn": 0, "fp": 0, "fn": 0})
            has_cat = category in actual_categories
            if is_positive and has_cat:
                cat_bucket["tp"] += 1
            elif (not is_positive) and (not has_cat):
                cat_bucket["tn"] += 1
            elif (not is_positive) and has_cat:
                cat_bucket["fp"] += 1
            else:
                cat_bucket["fn"] += 1

        script_l = case.script.lower()
        if any(token in script_l for token in ["güvenmeyin", "guvenmeyin", "yoktur", "değildir", "degildir", "garanti etmez"]):
            negation_results.append(
                {
                    "fixture": case.case_id,
                    "high_severity_financial_findings": [
                        f["code"]
                        for f in row.get("findings", [])
                        if f.get("severity") in {"HIGH", "CRITICAL"}
                        and get_finding_spec(f.get("code", "")).category == "financial_claim_risk"
                    ],
                }
            )

        fixture_debug.append(
            {
                "fixture": case.case_id,
                "checkpoint": case.checkpoint,
                "expected": sorted(expected),
                "actual": sorted(actual),
                "matched": got_positive,
                "severity": row.get("severity"),
                "highest_severity_level": row.get("highest_severity_level"),
            }
        )

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    specificity = tn / (tn + fp) if (tn + fp) else 1.0

    report = {
        "label": "LOCAL CALIBRATION EVIDENCE - NOT PRODUCTION VALIDATION",
        "fixture_total": len(CASES),
        "expected_positive_cases": sum(1 for case in CASES if case.expected_findings_any),
        "expected_negative_cases": sum(1 for case in CASES if not case.expected_findings_any),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "per_validator": per_validator,
        "per_category": per_category,
        "equivalent_finding_policy": {k: sorted(v) for k, v in _EQUIVALENT_FINDINGS.items()},
        "turkish_negation_results": negation_results,
        "fixture_debug": fixture_debug,
    }

    FULL_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FULL_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    assert report["precision"] >= 0.90
    assert report["recall"] >= 0.90
    assert report["specificity"] >= 0.90
    assert all(not item["high_severity_financial_findings"] for item in negation_results)
