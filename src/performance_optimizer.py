"""Performance-driven optimization signals for content generation."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from .channel_performance import load_recent_performance_snapshots


DEFAULT_STATE_DIR = Path("output/state/channel_optimization")


def _state_path(channel_id: str, state_dir: Path | str = DEFAULT_STATE_DIR) -> Path:
    return Path(state_dir) / f"{channel_id}.json"


def load_channel_optimization_state(channel_id: str, *, state_dir: Path | str = DEFAULT_STATE_DIR) -> dict:
    path = _state_path(channel_id, state_dir=state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_channel_optimization_state(
    channel_id: str,
    state: dict,
    *,
    state_dir: Path | str = DEFAULT_STATE_DIR,
) -> None:
    path = _state_path(channel_id, state_dir=state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def derive_channel_optimization_state(snapshots: list[dict[str, Any]]) -> dict:
    if not snapshots:
        return {
            "mode": "balanced",
            "focus": ["thumbnail", "hook", "retention"],
            "guidance": "",
        }

    ctr_values = [float(x) for x in (item.get("click_through_rate") for item in snapshots) if isinstance(x, (int, float))]
    retention_values = [float(x) for x in (item.get("average_view_percentage") for item in snapshots) if isinstance(x, (int, float))]
    watch_time_values = [float(x) for x in (item.get("watch_time_hours") for item in snapshots) if isinstance(x, (int, float))]
    thumbnail_values = [float(x) for x in (item.get("thumbnail_attention_score") for item in snapshots) if isinstance(x, (int, float))]
    hook_values = [float(x) for x in (item.get("hook_score") for item in snapshots) if isinstance(x, (int, float))]

    avg_ctr = mean(ctr_values) if ctr_values else None
    avg_retention = mean(retention_values) if retention_values else None
    avg_watch_time = mean(watch_time_values) if watch_time_values else None
    avg_thumbnail = mean(thumbnail_values) if thumbnail_values else None
    avg_hook = mean(hook_values) if hook_values else None
    total_impressions = sum(float(item.get("impressions") or 0.0) for item in snapshots if isinstance(item.get("impressions"), (int, float)))
    sample_count = len(snapshots)

    min_samples = 5
    min_impressions = 1000.0
    weak_sample = sample_count < min_samples or total_impressions < min_impressions

    if weak_sample:
        return {
            "mode": "balanced",
            "focus": ["observe"],
            "avg_ctr": avg_ctr,
            "avg_retention": avg_retention,
            "avg_watch_time_hours": avg_watch_time,
            "avg_thumbnail_attention_score": avg_thumbnail,
            "avg_hook_score": avg_hook,
            "sample_count": sample_count,
            "total_impressions": total_impressions,
            "weak_sample": True,
            "guidance": (
                "Insufficient statistical evidence for automatic optimization. "
                "Keep current strategy and continue collecting performance data."
            ),
        }

    focus: list[str] = []
    if avg_ctr is None or avg_ctr < 0.04:
        focus.append("thumbnail")
    if avg_retention is None or avg_retention < 55:
        focus.append("hook")
        focus.append("retention")
    if avg_watch_time is None or avg_watch_time < 2.0:
        focus.append("structure")
    if avg_thumbnail is not None and avg_thumbnail < 70:
        focus.append("visual")
    if avg_hook is not None and avg_hook < 70:
        focus.append("opening")

    focus = list(dict.fromkeys(focus)) or ["balanced"]
    mode = "balanced"
    if "thumbnail" in focus and "retention" not in focus:
        mode = "click" if avg_retention and avg_retention >= 55 else "thumbnail"
    elif "retention" in focus and "thumbnail" not in focus:
        mode = "retention"
    elif "thumbnail" in focus and "retention" in focus:
        mode = "balanced"

    guidance_parts = []
    if "thumbnail" in focus or "visual" in focus:
        guidance_parts.append(
            "Thumbnail: daha spesifik, tek odaklı, yüksek kontrastlı, mobilde okunur, insan yüzü veya belirgin obje içeren konseptler üret."
        )
    if "hook" in focus or "opening" in focus:
        guidance_parts.append(
            "Hook: ilk 15-20 saniyede daha güçlü merak boşluğu aç, sonucu geciktirme, daha kısa ve ritimli cümle kullan."
        )
    if "retention" in focus or "structure" in focus:
        guidance_parts.append(
            "Retention: yapıyı daha bölümlemeli kur, her 45-60 saniyede yeni fayda ver, örnekleri daha erken göster."
        )
    guidance_parts.append("Kesin fiyat hedefi ve canlı veri izlenimi veren iddialardan kaçın.")

    return {
        "mode": mode,
        "focus": focus,
        "avg_ctr": avg_ctr,
        "avg_retention": avg_retention,
        "avg_watch_time_hours": avg_watch_time,
        "avg_thumbnail_attention_score": avg_thumbnail,
        "avg_hook_score": avg_hook,
        "sample_count": sample_count,
        "total_impressions": total_impressions,
        "weak_sample": False,
        "guidance": " ".join(guidance_parts),
    }


def build_optimization_guidance(state: dict | None) -> str:
    state = state or {}
    if not state:
        return ""
    metrics = []
    if state.get("avg_ctr") is not None:
        metrics.append(f"CTR ort.: {state['avg_ctr']:.3f}")
    if state.get("avg_retention") is not None:
        metrics.append(f"izlenme oranı ort.: {state['avg_retention']:.1f}%")
    if state.get("avg_watch_time_hours") is not None:
        metrics.append(f"watch time ort.: {state['avg_watch_time_hours']:.2f} saat")
    prefix = "CANLI OPTIMIZATION FEEDBACK: "
    if metrics:
        prefix += " | ".join(metrics) + " -> "
    return prefix + str(state.get("guidance") or "")


def refresh_channel_optimization_state(
    channel_id: str,
    *,
    state_dir: Path | str = DEFAULT_STATE_DIR,
    performance_path: Path | str | None = None,
) -> dict:
    snapshots = load_recent_performance_snapshots(history_path=performance_path) if performance_path else load_recent_performance_snapshots()
    channel_snapshots = [row for row in snapshots if str(row.get("channel_id") or "") == channel_id]
    state = derive_channel_optimization_state(channel_snapshots)
    state["channel_id"] = channel_id
    save_channel_optimization_state(channel_id, state, state_dir=state_dir)
    return state
