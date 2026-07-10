#!/usr/bin/env python3
"""Build persistent optimization memory from historical performance snapshots.

This layer stores learned performance patterns so optimization decisions can use
history instead of only latest snapshots.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_PATH = ROOT / "logs" / "channel_performance.jsonl"
MIN_REQUIRED_SAMPLE_COUNT = 30


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_recent_rows(*, max_rows: int) -> list[dict[str, Any]]:
    if not PERFORMANCE_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in PERFORMANCE_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        rows.append(item)

    return rows[-max(1, int(max_rows)) :]


def _thumbnail_strategy_insights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        strategy = str(row.get("thumbnail_strategy") or "").strip().lower()
        ctr = _safe_float(row.get("click_through_rate"))
        if not strategy or ctr is None:
            continue
        grouped.setdefault(strategy, []).append(ctr)

    insights: list[dict[str, Any]] = []
    for strategy, ctrs in grouped.items():
        if len(ctrs) < 3:
            continue
        insights.append(
            {
                "type": "thumbnail_strategy_ctr",
                "strategy": strategy,
                "sample_size": len(ctrs),
                "avg_ctr": round(mean(ctrs), 4),
            }
        )

    insights.sort(key=lambda x: float(x.get("avg_ctr", 0.0)), reverse=True)
    return insights


def _title_pattern_insights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with_q: list[float] = []
    without_q: list[float] = []

    for row in rows:
        title = str(row.get("title") or "")
        ctr = _safe_float(row.get("click_through_rate"))
        if ctr is None:
            continue
        if "?" in title:
            with_q.append(ctr)
        else:
            without_q.append(ctr)

    insights: list[dict[str, Any]] = []
    if len(with_q) >= 5 and len(without_q) >= 5:
        avg_with_q = mean(with_q)
        avg_without_q = mean(without_q)
        delta_pct = 0.0
        if avg_without_q > 0:
            delta_pct = ((avg_with_q - avg_without_q) / avg_without_q) * 100.0
        insights.append(
            {
                "type": "title_question_pattern",
                "sample_size": len(with_q) + len(without_q),
                "question_title_count": len(with_q),
                "plain_title_count": len(without_q),
                "avg_ctr_question_title": round(avg_with_q, 4),
                "avg_ctr_plain_title": round(avg_without_q, 4),
                "ctr_delta_percent": round(delta_pct, 2),
            }
        )

    return insights


def _quality_band_insights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[tuple[float, float]] = []
    for row in rows:
        quality = _safe_float(row.get("overall_quality_score"))
        ctr = _safe_float(row.get("click_through_rate"))
        if quality is None or ctr is None:
            continue
        scored.append((quality, ctr))

    if len(scored) < 9:
        return []

    scored.sort(key=lambda item: item[0])
    chunk = max(1, len(scored) // 3)
    bands = {
        "low": scored[:chunk],
        "mid": scored[chunk : chunk * 2],
        "high": scored[chunk * 2 :],
    }

    out: list[dict[str, Any]] = []
    for band_name, values in bands.items():
        if len(values) < 2:
            continue
        qualities = [v[0] for v in values]
        ctrs = [v[1] for v in values]
        out.append(
            {
                "type": "quality_band_ctr",
                "band": band_name,
                "sample_size": len(values),
                "avg_quality_score": round(mean(qualities), 3),
                "avg_ctr": round(mean(ctrs), 4),
            }
        )

    return out


def _build_human_summary(insights: list[dict[str, Any]]) -> list[str]:
    summary: list[str] = []
    for item in insights:
        typ = str(item.get("type") or "")
        if typ == "thumbnail_strategy_ctr":
            summary.append(
                f"thumbnail_strategy={item.get('strategy')} avg_ctr={item.get('avg_ctr')} sample={item.get('sample_size')}"
            )
        elif typ == "title_question_pattern":
            summary.append(
                "question_mark_titles ctr_delta_percent="
                f"{item.get('ctr_delta_percent')} sample={item.get('sample_size')}"
            )
        elif typ == "quality_band_ctr":
            summary.append(
                f"quality_band={item.get('band')} avg_ctr={item.get('avg_ctr')} sample={item.get('sample_size')}"
            )
    return summary


def build_optimization_memory(*, max_rows: int = 500) -> dict[str, Any]:
    rows = _load_recent_rows(max_rows=max_rows)

    required_sample_count = max(10, int(MIN_REQUIRED_SAMPLE_COUNT))
    sample_count = len(rows)
    if sample_count < required_sample_count:
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "insufficient_data",
            "sample_count": sample_count,
            "required_sample_count": required_sample_count,
            "source": {
                "performance_path": str(PERFORMANCE_PATH),
                "rows_scanned": sample_count,
                "max_rows": max_rows,
            },
            "insights": [],
            "insight_summary": [],
            "coverage": {
                "has_thumbnail_strategy_memory": False,
                "has_title_pattern_memory": False,
                "has_quality_band_memory": False,
                "missing_dimensions": [
                    "thumbnail_color_layout",
                    "title_pattern",
                    "quality_band",
                ],
            },
            "safety": {
                "read_only": True,
                "writes_runtime_flags": False,
                "writes_code": False,
            },
        }

    strategy_insights = _thumbnail_strategy_insights(rows)
    title_insights = _title_pattern_insights(rows)
    quality_insights = _quality_band_insights(rows)
    all_insights = strategy_insights + title_insights + quality_insights

    missing_dimensions: list[str] = []
    if not strategy_insights:
        missing_dimensions.append("thumbnail_color_layout")

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "sample_count": sample_count,
        "required_sample_count": required_sample_count,
        "source": {
            "performance_path": str(PERFORMANCE_PATH),
            "rows_scanned": len(rows),
            "max_rows": max_rows,
        },
        "insights": all_insights,
        "insight_summary": _build_human_summary(all_insights),
        "coverage": {
            "has_thumbnail_strategy_memory": bool(strategy_insights),
            "has_title_pattern_memory": bool(title_insights),
            "has_quality_band_memory": bool(quality_insights),
            "missing_dimensions": missing_dimensions,
        },
        "safety": {
            "read_only": True,
            "writes_runtime_flags": False,
            "writes_code": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate optimization memory from performance history")
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--output", default=str(ROOT / "logs" / "optimization_memory.json"))
    args = parser.parse_args(argv)

    report = build_optimization_memory(max_rows=max(50, int(args.max_rows)))
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(out_path),
                "rows_scanned": report["source"]["rows_scanned"],
                "insight_count": len(report["insights"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
