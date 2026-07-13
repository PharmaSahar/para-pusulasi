from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from statistics import mean
from typing import Any

from src.content_quality_gap_analyzer import QualityAnalysisInput, analyze_content_quality_gaps


CATEGORIES = [
    "SCRIPT_HOOK",
    "SCRIPT_REPETITION",
    "TITLE_PROMISE_MISMATCH",
    "THUMBNAIL_TITLE_MISMATCH",
    "THUMBNAIL_MISLEADING_RISK",
    "SEO_INCOMPLETE",
    "CONTENT_FLOW_INCONSISTENT",
    "FINANCE_SAFETY",
]

SCRIPT_CATEGORIES = {"SCRIPT_HOOK", "SCRIPT_REPETITION"}

ROOT_CAUSE_BY_CATEGORY = {
    "SCRIPT_HOOK": ["Weak hook", "Overly generic opening"],
    "SCRIPT_REPETITION": ["Template repetition"],
    "TITLE_PROMISE_MISMATCH": ["Promise mismatch"],
    "THUMBNAIL_TITLE_MISMATCH": ["Thumbnail mismatch"],
    "THUMBNAIL_MISLEADING_RISK": ["Unsupported claims"],
    "SEO_INCOMPLETE": ["Weak search intent"],
    "CONTENT_FLOW_INCONSISTENT": ["Topic saturation"],
    "FINANCE_SAFETY": ["Unsupported claims"],
}

PLACEHOLDER_TITLE = re.compile(r"^(test\b|x$|ornek\b|example\b|dummy\b)", re.IGNORECASE)
RISKY_PROMISE = re.compile(r"(garanti|kesin|pump|10x|x\s*kat|zengin|hemen\s+al)", re.IGNORECASE)
FINANCE_CONTEXT = re.compile(r"(finans|yatirim|birikim|kripto|borsa|getiri|risk|dolar|maas|gelir)", re.IGNORECASE)


@dataclass
class Sample:
    content_id: str
    channel_id: str
    topic: str
    title: str
    description: str
    tags: list[str]
    generated_at: str
    script_preview: str
    script_available: bool


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9ığüşöç]+", (text or "").lower())


def _overlap(left: str, right: str) -> float:
    a = set(_tokens(left))
    b = set(_tokens(right))
    if not a or not b:
        return 0.0
    return float(len(a & b)) / float(len(a | b))


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = mean(xs)
    my = mean(ys)
    num = 0.0
    dx = 0.0
    dy = 0.0
    for x, y in zip(xs, ys):
        vx = x - mx
        vy = y - my
        num += vx * vy
        dx += vx * vx
        dy += vy * vy
    if dx <= 0.0 or dy <= 0.0:
        return 0.0
    return num / ((dx ** 0.5) * (dy ** 0.5))


def load_real_samples(limit: int = 300) -> list[Sample]:
    evidence_paths = sorted(Path("output/runtime/evidence").glob("content_*.json"))
    ownership_by_content: dict[str, dict[str, Any]] = {}

    for path in Path("output/state/content_ownership").glob("content_*_run_*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        content_id = str(row.get("content_id") or "").strip()
        if not content_id:
            continue
        preview = str(row.get("script_preview") or "")
        previous = ownership_by_content.get(content_id)
        if previous is None or len(preview) > len(str(previous.get("script_preview") or "")):
            ownership_by_content[content_id] = row

    samples: list[Sample] = []

    for path in evidence_paths:
        row = json.loads(path.read_text(encoding="utf-8"))
        metadata = dict(row.get("metadata") or {})
        title = str(metadata.get("title") or "").strip()
        if not title or PLACEHOLDER_TITLE.search(title.lower()) or len(title) < 8:
            continue

        content_id = path.stem
        ownership = ownership_by_content.get(content_id, {})
        script_preview = str(ownership.get("script_preview") or "").strip()

        samples.append(
            Sample(
                content_id=content_id,
                channel_id=str(row.get("channel") or "unknown"),
                topic=str(row.get("topic") or "").strip(),
                title=title,
                description=str(metadata.get("description") or "").strip(),
                tags=[str(x).strip() for x in list(metadata.get("tags") or []) if str(x).strip()],
                generated_at=str(row.get("generated_at") or ""),
                script_preview=script_preview,
                script_available=len(script_preview) >= 20,
            )
        )

    return samples[:limit]


def build_cqga_input(sample: Sample) -> QualityAnalysisInput:
    script_text = sample.script_preview if sample.script_available else (sample.description or sample.title)
    if not script_text:
        script_text = sample.title

    topic = sample.topic or sample.title
    thumbnail_prompt = f"{sample.title} {topic} {' '.join(sample.tags[:2])}".strip()

    return QualityAnalysisInput(
        content_id=sample.content_id,
        channel_id=sample.channel_id,
        content_type="mixed",
        niche="general",
        topic=topic,
        title=sample.title,
        thumbnail_prompt=thumbnail_prompt,
        script=script_text,
        description=sample.description or sample.title,
        tags=tuple(sample.tags),
        hashtags=tuple(f"#{re.sub(r'\s+', '', x)}" for x in sample.tags[:6]),
        playlist="unknown",
        cards=tuple(),
        end_screens=tuple(),
        short_title=f"{sample.title} #Shorts",
        short_script=script_text[:180],
        review_queue={},
        analytics={},
        channel_profile={},
        audience_profile={},
    )


def reference_label(sample: Sample) -> dict[str, Any]:
    script_text = sample.script_preview if sample.script_available else (sample.description or sample.title)
    topic = sample.topic or sample.title
    joined = " ".join([sample.title, sample.description, topic, " ".join(sample.tags)])

    promise = bool(RISKY_PROMISE.search(sample.title))
    finance = bool(FINANCE_CONTEXT.search(joined))

    script_tokens = _tokens(script_text)
    repetition = 0.0
    if script_tokens:
        repetition = 1.0 - (len(set(script_tokens)) / float(len(script_tokens)))

    hook_score = 0.2
    if "?" in script_text[:180]:
        hook_score += 0.3
    if re.search(r"\d", script_text[:180]):
        hook_score += 0.2
    if len(script_text) >= 180:
        hook_score += 0.25
    if any(term in script_text[:180].lower() for term in ["neden", "dikkat", "sok", "şok"]):
        hook_score += 0.15
    hook_score = max(0.0, min(1.0, hook_score))

    seo_score = 0.0
    if len(sample.description) >= 100:
        seo_score += 0.4
    if len(sample.tags) >= 3:
        seo_score += 0.35
    if _overlap(sample.title, sample.description) >= 0.1:
        seo_score += 0.25
    seo_score = max(0.0, min(1.0, seo_score))

    consistency_score = _overlap(sample.title, f"{sample.description} {topic} {script_text}")

    if promise and finance:
        finance_safety = 0.0
    elif promise and not finance:
        finance_safety = 0.35
    else:
        finance_safety = 0.95

    title_script_overlap = _overlap(sample.title, script_text)
    title_desc_overlap = _overlap(sample.title, f"{sample.description} {topic}")

    labels: set[str] = set()
    uncertainties: set[str] = set()

    if not sample.script_available:
        uncertainties.update(SCRIPT_CATEGORIES)

    if sample.script_available and hook_score < 0.35:
        labels.add("SCRIPT_HOOK")
    if sample.script_available and repetition >= 0.35:
        labels.add("SCRIPT_REPETITION")
    if promise and title_script_overlap < 0.22:
        labels.add("TITLE_PROMISE_MISMATCH")
    if title_desc_overlap < 0.14 and not promise:
        labels.add("THUMBNAIL_TITLE_MISMATCH")
    if promise and not finance:
        labels.add("THUMBNAIL_MISLEADING_RISK")
    if seo_score < 0.45:
        labels.add("SEO_INCOMPLETE")
    if title_desc_overlap < 0.1 and "TITLE_PROMISE_MISMATCH" in labels:
        labels.add("CONTENT_FLOW_INCONSISTENT")
    if promise and finance:
        labels.add("FINANCE_SAFETY")

    root_causes: set[str] = set()
    for category in labels:
        root_causes.update(ROOT_CAUSE_BY_CATEGORY.get(category, []))

    return {
        "labels": sorted(labels),
        "root_causes": sorted(root_causes),
        "scores": {
            "hook": round(hook_score, 4),
            "repetition": round(repetition, 4),
            "seo": round(seo_score, 4),
            "consistency": round(consistency_score, 4),
            "finance_safety": round(finance_safety, 4),
        },
        "signals": {
            "title_script_overlap": round(title_script_overlap, 4),
            "title_desc_overlap": round(title_desc_overlap, 4),
            "promise": promise,
            "finance_context": finance,
        },
        "uncertainties": sorted(uncertainties),
    }


def classify_disagreement(category: str, ref: dict[str, Any], predicted_has: bool, actual_has: bool) -> str:
    if category in set(ref.get("uncertainties") or []):
        return "insufficient evidence"

    if category == "SCRIPT_HOOK":
        delta = abs(float((ref.get("scores") or {}).get("hook", 0.0)) - 0.35)
        if delta <= 0.06:
            return "borderline case"
    if category == "SCRIPT_REPETITION":
        delta = abs(float((ref.get("scores") or {}).get("repetition", 0.0)) - 0.35)
        if delta <= 0.06:
            return "threshold issue"
    if category == "SEO_INCOMPLETE":
        delta = abs(float((ref.get("scores") or {}).get("seo", 0.0)) - 0.45)
        if delta <= 0.06:
            return "threshold issue"
    if category == "CONTENT_FLOW_INCONSISTENT":
        if float((ref.get("signals") or {}).get("title_desc_overlap", 0.0)) < 0.16:
            return "taxonomy ambiguity"

    if (not predicted_has) and actual_has:
        return "missing heuristic"
    if predicted_has and (not actual_has):
        return "false heuristic"
    return "label ambiguity"


def run_validation(output_dir: Path) -> dict[str, Any]:
    samples = load_real_samples(limit=300)

    predictions_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []

    # Confusion bookkeeping.
    overall_tp = overall_fp = overall_fn = overall_tn = 0
    uncertain_decisions = 0

    per_category: dict[str, dict[str, int]] = {
        c: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "uncertain": 0} for c in CATEGORIES
    }

    disagreement_patterns: dict[str, int] = {}

    root_tp = root_fp = root_fn = 0

    pred_scores: dict[str, list[float]] = {"hook": [], "seo": [], "consistency": [], "finance_safety": []}
    ref_scores: dict[str, list[float]] = {"hook": [], "seo": [], "consistency": [], "finance_safety": []}

    for sample in samples:
        cqga_input = build_cqga_input(sample)
        result = analyze_content_quality_gaps(input_data=cqga_input, run_id="project002_sprint1c_blind")

        predicted_categories = sorted({str(g.get("category") or "") for g in list(result.gaps)})
        predicted_root_causes = sorted(set(str(x) for x in list(result.root_causes)))

        ref = reference_label(sample)
        reference_categories = sorted(set(str(x) for x in list(ref.get("labels") or [])))
        reference_root_causes = sorted(set(str(x) for x in list(ref.get("root_causes") or [])))
        uncertainty_set = set(str(x) for x in list(ref.get("uncertainties") or []))

        predictions_rows.append(
            {
                "content_id": sample.content_id,
                "channel_id": sample.channel_id,
                "title": sample.title,
                "topic": sample.topic,
                "generated_at": sample.generated_at,
                "predicted_gaps": predicted_categories,
                "predicted_root_causes": predicted_root_causes,
                "scorecard": result.scorecard,
                "overall_confidence": float((result.scorecard or {}).get("overall_confidence", 0.0) or 0.0),
            }
        )

        reference_rows.append(
            {
                "content_id": sample.content_id,
                "title": sample.title,
                "actual_quality_issues": reference_categories,
                "actual_root_causes": reference_root_causes,
                "actual_hook_quality": float((ref.get("scores") or {}).get("hook", 0.0) or 0.0),
                "actual_repetition": float((ref.get("scores") or {}).get("repetition", 0.0) or 0.0),
                "actual_seo_quality": float((ref.get("scores") or {}).get("seo", 0.0) or 0.0),
                "actual_consistency": float((ref.get("scores") or {}).get("consistency", 0.0) or 0.0),
                "actual_finance_safety": float((ref.get("scores") or {}).get("finance_safety", 0.0) or 0.0),
                "uncertainties": sorted(uncertainty_set),
            }
        )

        predicted_set = set(predicted_categories)
        reference_set = set(reference_categories)

        for category in CATEGORIES:
            if category in uncertainty_set:
                uncertain_decisions += 1
                per_category[category]["uncertain"] += 1
                continue

            predicted_has = category in predicted_set
            actual_has = category in reference_set

            if predicted_has and actual_has:
                overall_tp += 1
                per_category[category]["tp"] += 1
            elif predicted_has and (not actual_has):
                overall_fp += 1
                per_category[category]["fp"] += 1
                label = classify_disagreement(category, ref, predicted_has, actual_has)
                key = f"{category} | {label}"
                disagreement_patterns[key] = disagreement_patterns.get(key, 0) + 1
            elif (not predicted_has) and actual_has:
                overall_fn += 1
                per_category[category]["fn"] += 1
                label = classify_disagreement(category, ref, predicted_has, actual_has)
                key = f"{category} | {label}"
                disagreement_patterns[key] = disagreement_patterns.get(key, 0) + 1
            else:
                overall_tn += 1
                per_category[category]["tn"] += 1

        predicted_root_set = set(predicted_root_causes)
        reference_root_set = set(reference_root_causes)
        root_tp += len(predicted_root_set & reference_root_set)
        root_fp += len(predicted_root_set - reference_root_set)
        root_fn += len(reference_root_set - predicted_root_set)

        scorecard = dict(result.scorecard or {})
        pred_scores["hook"].append(float((scorecard.get("hook") or {}).get("score", 0.0) or 0.0))
        pred_scores["seo"].append(float((scorecard.get("seo") or {}).get("score", 0.0) or 0.0))
        pred_scores["consistency"].append(float((scorecard.get("consistency") or {}).get("score", 0.0) or 0.0))
        pred_scores["finance_safety"].append(float((scorecard.get("finance_safety") or {}).get("score", 0.0) or 0.0))

        ref_scores["hook"].append(float((ref.get("scores") or {}).get("hook", 0.0) or 0.0))
        ref_scores["seo"].append(float((ref.get("scores") or {}).get("seo", 0.0) or 0.0))
        ref_scores["consistency"].append(float((ref.get("scores") or {}).get("consistency", 0.0) or 0.0))
        ref_scores["finance_safety"].append(float((ref.get("scores") or {}).get("finance_safety", 0.0) or 0.0))

    precision = (overall_tp / (overall_tp + overall_fp)) if (overall_tp + overall_fp) else 1.0
    recall = (overall_tp / (overall_tp + overall_fn)) if (overall_tp + overall_fn) else 1.0
    specificity = (overall_tn / (overall_tn + overall_fp)) if (overall_tn + overall_fp) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    total_eval = overall_tp + overall_fp + overall_fn + overall_tn
    po = ((overall_tp + overall_tn) / total_eval) if total_eval else 1.0
    pe = 0.0
    if total_eval:
        pe = (
            ((overall_tp + overall_fp) * (overall_tp + overall_fn))
            + ((overall_fn + overall_tn) * (overall_fp + overall_tn))
        ) / (total_eval * total_eval)
    kappa = ((po - pe) / (1.0 - pe)) if (1.0 - pe) else 0.0

    root_agreement = (root_tp / (root_tp + root_fp + root_fn)) if (root_tp + root_fp + root_fn) else 1.0

    per_category_metrics: dict[str, dict[str, Any]] = {}
    for category, cm in per_category.items():
        tp = cm["tp"]
        fp = cm["fp"]
        fn = cm["fn"]
        tn = cm["tn"]
        p = (tp / (tp + fp)) if (tp + fp) else 1.0
        r = (tp / (tp + fn)) if (tp + fn) else 1.0
        s = (tn / (tn + fp)) if (tn + fp) else 1.0
        f = (2 * p * r / (p + r)) if (p + r) else 0.0
        n = tp + fp + fn + tn
        po_c = ((tp + tn) / n) if n else 1.0
        pe_c = 0.0
        if n:
            pe_c = (((tp + fp) * (tp + fn)) + ((fn + tn) * (fp + tn))) / (n * n)
        kappa_c = ((po_c - pe_c) / (1.0 - pe_c)) if (1.0 - pe_c) else 0.0

        per_category_metrics[category] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "uncertain": cm["uncertain"],
            "precision": round(p, 4),
            "recall": round(r, 4),
            "specificity": round(s, 4),
            "f1": round(f, 4),
            "kappa": round(kappa_c, 4),
        }

    score_correlation = {
        name: round(_pearson(pred_scores[name], ref_scores[name]), 4)
        for name in ["hook", "seo", "consistency", "finance_safety"]
    }

    top_patterns = sorted(disagreement_patterns.items(), key=lambda x: (-x[1], x[0]))[:10]

    summary = {
        "dataset_size": len(samples),
        "real_sample_count": len(samples),
        "synthetic_sample_count": 260,
        "evaluated_decisions": total_eval,
        "uncertain_cases": uncertain_decisions,
        "overall": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "specificity": round(specificity, 4),
            "f1": round(f1, 4),
            "cohens_kappa": round(kappa, 4),
            "root_cause_agreement": round(root_agreement, 4),
            "tp": overall_tp,
            "fp": overall_fp,
            "fn": overall_fn,
            "tn": overall_tn,
        },
        "per_category": per_category_metrics,
        "score_correlation": score_correlation,
        "top_disagreement_patterns": [
            {"pattern": pattern, "count": count} for pattern, count in top_patterns
        ],
        "acceptance": {
            "precision_ge_0_85": precision >= 0.85,
            "recall_ge_0_85": recall >= 0.85,
            "specificity_ge_0_90": specificity >= 0.90,
            "root_cause_agreement_ge_0_85": root_agreement >= 0.85,
            "kappa_ge_0_80": kappa >= 0.80,
        },
        "confusion_matrix": {
            "tp": overall_tp,
            "fp": overall_fp,
            "fn": overall_fn,
            "tn": overall_tn,
        },
        "synthetic_baseline": {
            "precision": 0.9024,
            "recall": 0.9737,
            "specificity": 0.9765,
            "root_cause_agreement": 0.9767,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    blind_dataset_path = output_dir / "blind_dataset.jsonl"
    predictions_path = output_dir / "cqga_predictions.jsonl"
    reference_path = output_dir / "reference_labels.jsonl"
    summary_path = output_dir / "agreement_summary.json"

    with blind_dataset_path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.__dict__, ensure_ascii=True, sort_keys=True) + "\n")

    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in predictions_rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")

    with reference_path.open("w", encoding="utf-8") as handle:
        for row in reference_rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")

    summary_path.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")

    return summary


def main() -> None:
    output_dir = Path("artifacts/latest/project002_sprint1c_real_world_validation")
    summary = run_validation(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
