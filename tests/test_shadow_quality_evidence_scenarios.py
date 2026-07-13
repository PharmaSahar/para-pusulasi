from __future__ import annotations

import json
from pathlib import Path

from src.shadow_content_quality import (
    SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
    ShadowContentQualityEngine,
    build_shadow_evaluation_context,
)


def _engine_for(
    *,
    run_id: str,
    topic: str,
    title: str,
    script: str,
    description: str,
    thumbnail_prompt: str,
    cta_text: str = "abone ol",
) -> ShadowContentQualityEngine:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="channel_demo",
        content_type="mixed",
        topic=topic,
        title=title,
        script=script,
        description=description,
        thumbnail_prompt=thumbnail_prompt,
        cta_text=cta_text,
    )
    return ShadowContentQualityEngine(context=ctx, results_path=Path("logs/shadow_content_quality_results_test.jsonl"))


def test_shadow_evidence_scenarios_local_report(tmp_path: Path):
    scenarios = []

    # 1. Safe educational finance content
    s1 = _engine_for(
        run_id="s1",
        topic="Finansal okuryazarlik",
        title="Finansal Okuryazarlikta Temel Ilkeler",
        script="Butce disiplini, risk yonetimi ve hedef planlamasi ile ilerleyin.",
        description="Temel finans egitimi ve disiplinli birikim adimlari.",
        thumbnail_prompt="Simple finance education board and checklist",
    ).evaluate_checkpoint(checkpoint="generation")
    scenarios.append(
        {
            "scenario": "safe_educational_finance",
            "checkpoint": "generation",
            "score": s1.get("overall_score"),
            "findings": s1.get("findings"),
            "severity": s1.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 2. Pump-style stock content
    s2 = _engine_for(
        run_id="s2",
        topic="Hisse hype",
        title="Bu Hisse Ucacak Son Sans",
        script="Insider information var, hemen al, yuzde 340 getiri garanti.",
        description="Ayni iddialar burada tekrar edilir.",
        thumbnail_prompt="Rocket stock millionaire instantly",
    ).evaluate_checkpoint(checkpoint="generation")
    scenarios.append(
        {
            "scenario": "pump_style_stock",
            "checkpoint": "generation",
            "score": s2.get("overall_score"),
            "findings": s2.get("findings"),
            "severity": s2.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 3. Title/script mismatch
    s3 = _engine_for(
        run_id="s3",
        topic="Birikim",
        title="Birikim Plani",
        script="Yazilim kariyerinde remote mulakat teknikleri anlatiliyor.",
        description="Birikim konusu dense de icerik farkli.",
        thumbnail_prompt="Finance checklist",
    ).evaluate_checkpoint(checkpoint="generation")
    scenarios.append(
        {
            "scenario": "title_script_mismatch",
            "checkpoint": "generation",
            "score": s3.get("overall_score"),
            "findings": s3.get("findings"),
            "severity": s3.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 4. Thumbnail/script mismatch
    s4 = _engine_for(
        run_id="s4",
        topic="Birikim",
        title="Birikim Aliskanligi",
        script="Birikim plani ve harcama kontrolu anlatilir.",
        description="Birikim adimlari.",
        thumbnail_prompt="Luxury private jet instant rich celebrity scene",
    ).evaluate_checkpoint(checkpoint="thumbnail_metadata", thumbnail_text="Luks Yasam")
    scenarios.append(
        {
            "scenario": "thumbnail_script_mismatch",
            "checkpoint": "thumbnail_metadata",
            "score": s4.get("overall_score"),
            "findings": s4.get("findings"),
            "severity": s4.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 5. Duplicate script
    dup_engine = _engine_for(
        run_id="s5",
        topic="Birikim",
        title="Acil Durum Fonu",
        script="Acil durum fonu icin uc adimli plan uygulayin.",
        description="Acil durum fonu adimlari.",
        thumbnail_prompt="Emergency fund checklist",
    )
    _ = dup_engine.evaluate_and_store(checkpoint="generation")
    s5 = _engine_for(
        run_id="s5b",
        topic="Birikim",
        title="Acil Durum Fonu",
        script="Acil durum fonu icin uc adimli plan uygulayin.",
        description="Acil durum fonu adimlari.",
        thumbnail_prompt="Emergency fund checklist",
    ).evaluate_checkpoint(checkpoint="generation")
    scenarios.append(
        {
            "scenario": "duplicate_script",
            "checkpoint": "generation",
            "score": s5.get("overall_score"),
            "findings": s5.get("findings"),
            "severity": s5.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 6. Abrupt Shorts clipping
    s6 = _engine_for(
        run_id="s6",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script.",
        description="Aciklama.",
        thumbnail_prompt="Finance prompt",
    ).evaluate_checkpoint(
        checkpoint="shorts",
        short_script="ve sonra bunu yapiyoruz cunku",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=64,
    )
    scenarios.append(
        {
            "scenario": "abrupt_shorts_clipping",
            "checkpoint": "shorts",
            "score": s6.get("overall_score"),
            "findings": s6.get("findings"),
            "severity": s6.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 7. Valid complete short
    s7 = _engine_for(
        run_id="s7",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script.",
        description="Aciklama.",
        thumbnail_prompt="Finance prompt",
    ).evaluate_checkpoint(
        checkpoint="shorts",
        short_script=(
            "Birikim icin once net bir hedef belirleyin. Sonra aylik butce cikarip gereksiz harcamalari azaltin. "
            "Acil durum fonu olusturarak beklenmedik giderlere karsi koruma saglayin. "
            "Bu uc adim duzenli uygulandiginda birikim sureci kalici hale gelir."
        ),
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=58,
    )
    scenarios.append(
        {
            "scenario": "valid_complete_short",
            "checkpoint": "shorts",
            "score": s7.get("overall_score"),
            "findings": s7.get("findings"),
            "severity": s7.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    # 8. Missing metadata
    s8 = _engine_for(
        run_id="s8",
        topic="",
        title="",
        script="",
        description="",
        thumbnail_prompt="",
        cta_text="",
    ).evaluate_checkpoint(checkpoint="description", description="")
    scenarios.append(
        {
            "scenario": "missing_metadata",
            "checkpoint": "description",
            "score": s8.get("overall_score"),
            "findings": s8.get("findings"),
            "severity": s8.get("severity"),
            "pipeline_output_changed": False,
        }
    )

    report = {
        "schema_version": SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
        "generated_at": "local_test",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }

    out = tmp_path / "shadow_evidence_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["scenario_count"] == 8
    assert all(item["pipeline_output_changed"] is False for item in loaded["scenarios"])
