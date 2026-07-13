from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from src.shadow_content_quality import (
    SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
    ShadowContentQualityEngine,
    append_shadow_row,
    build_shadow_evaluation_context,
    content_quality_shadow_mode_enabled,
    load_shadow_results,
    validate_shadow_row,
)


def _build_context() -> object:
    return build_shadow_evaluation_context(
        run_id="run_1",
        content_id="content_1",
        channel_id="channel_1",
        content_type="mixed",
        topic="Birikim plani",
        title="Birikim Yaparken 5 Hata",
        script="Birikim yaparken en sik gorulen 5 hatayi ve duzeltme adimlarini anlatiyoruz.",
        description="Bu videoda birikim surecinde yapilan hatalari anlatiyoruz.",
        thumbnail_prompt="Savings mistakes, warning icon, simple bold title",
        cta_text="abone ol",
        created_at="2026-07-13T12:00:00+00:00",
    )


@pytest.mark.parametrize("raw", [None, "", "0", "false", "False", "no", "off", "invalid", "  maybe "])
def test_shadow_mode_flag_false_values(raw: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTENT_QUALITY_SHADOW_MODE_ENABLED", raising=False)
    assert content_quality_shadow_mode_enabled(raw) is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", "  on  "])
def test_shadow_mode_flag_true_values(raw: str) -> None:
    assert content_quality_shadow_mode_enabled(raw) is True


def test_context_immutable_and_hashes_deterministic() -> None:
    ctx1 = _build_context()
    ctx2 = _build_context()
    assert ctx1.evaluation_id == ctx2.evaluation_id
    assert ctx1.script_hash == ctx2.script_hash
    with pytest.raises(FrozenInstanceError):
        ctx1.title = "mutate"  # type: ignore[misc]


def test_generation_checkpoint_safe_content_low_severity(tmp_path: Path) -> None:
    engine = ShadowContentQualityEngine(context=_build_context(), results_path=tmp_path / "shadow.jsonl")
    row = engine.evaluate_checkpoint(checkpoint="generation")
    assert row["checkpoint"] == "generation"
    assert row["severity"] in {"none", "low", "medium"}


def test_generation_checkpoint_detects_high_risk_claims(tmp_path: Path) -> None:
    ctx = build_shadow_evaluation_context(
        run_id="run_2",
        content_id="content_2",
        channel_id="channel_1",
        content_type="mixed",
        topic="Hisse tahmini",
        title="Bu Hisse Ucacak Son Sans",
        script=(
            "Insider information var. Bu bilgi henuz fiyata yansimadi. "
            "Fonlar gizlice topluyor. Hemen al. Yuzde 340 getiri garanti."
        ),
        description="Ayni iddialar bu aciklamada da geciyor.",
        thumbnail_prompt="Rocket stock instant rich",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "shadow.jsonl")
    row = engine.evaluate_checkpoint(checkpoint="generation")
    assert row["severity"] == "high"
    finding_codes = {item["code"] for item in row["findings"]}
    assert "pump_style_title_detection" in finding_codes
    assert "not_priced_in_claim_detection" in finding_codes
    assert "secret_institutional_claim_detection" in finding_codes


def test_description_checkpoint_detects_mismatch_and_links(tmp_path: Path) -> None:
    engine = ShadowContentQualityEngine(context=_build_context(), results_path=tmp_path / "shadow.jsonl")
    row = engine.evaluate_checkpoint(
        checkpoint="description",
        description="www.fake.example linkte garanti kazanacaksiniz. konu disi bir metin.",
    )
    finding_codes = {item["code"] for item in row["findings"]}
    assert "misleading_external_link_context" in finding_codes
    assert "title_description_consistency" in finding_codes


def test_thumbnail_checkpoint_detects_mismatch_and_duplication(tmp_path: Path) -> None:
    out = tmp_path / "shadow.jsonl"
    engine = ShadowContentQualityEngine(context=_build_context(), results_path=out)
    first = engine.evaluate_and_store(
        checkpoint="thumbnail_metadata",
        thumbnail_text="Birikimde Buyuk Hata",
    )
    assert first["checkpoint"] == "thumbnail_metadata"

    engine2 = ShadowContentQualityEngine(context=_build_context(), results_path=out)
    second = engine2.evaluate_checkpoint(
        checkpoint="thumbnail_metadata",
        thumbnail_text="Birikimde Buyuk Hata",
    )
    finding_codes = {item["code"] for item in second["findings"]}
    assert "duplicate_thumbnail_text_detection" in finding_codes


def test_shorts_checkpoint_signals_abrupt_text(tmp_path: Path) -> None:
    engine = ShadowContentQualityEngine(context=_build_context(), results_path=tmp_path / "shadow.jsonl")
    row = engine.evaluate_checkpoint(
        checkpoint="shorts",
        short_script="ve sonra bu konuya geciyoruz çünkü",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=65,
    )
    finding_codes = {item["code"] for item in row["findings"]}
    assert "shorts_abrupt_beginning" in finding_codes
    assert "shorts_abrupt_ending" in finding_codes
    assert "shorts_duration_signal" in finding_codes


def test_shorts_checkpoint_valid_complete_short(tmp_path: Path) -> None:
    engine = ShadowContentQualityEngine(context=_build_context(), results_path=tmp_path / "shadow.jsonl")
    short_script = (
            "Birikim rehberinde ilk adim net bir hedef koymaktir. "
        "Ikinci adim haftalik butce takibi ile harcamalari izlemektir. "
        "Ucuncu adim acil durum fonu olusturmaktir. "
        "Bu uc adim birikim planinin omurgasini kurar ve surekli gelisim saglar."
    )
    row = engine.evaluate_checkpoint(
        checkpoint="shorts",
        short_script=short_script,
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=58,
    )
    assert row["severity"] in {"none", "low", "medium"}


def test_seo_discovery_observability_states(tmp_path: Path) -> None:
    engine = ShadowContentQualityEngine(context=_build_context(), results_path=tmp_path / "shadow.jsonl")
    row = engine.evaluate_checkpoint(
        checkpoint="seo_discovery",
        description="Bu aciklama #birikim #finans etiketi icerir.",
        tags=["birikim", "finans"],
        playlist_recommendation="Birikim ve Tasarruf",
    )
    assert row["checkpoint"] == "seo_discovery"
    score_names = {item["score_name"] for item in row["quality_scores"]}
    assert "seo_discovery_observability_coverage" in score_names


def test_append_only_storage_and_malformed_line_handling(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    ctx = _build_context()
    engine = ShadowContentQualityEngine(context=ctx, results_path=path)
    row = engine.evaluate_checkpoint(checkpoint="generation")
    append_shadow_row(row, output_path=path)

    bad_line = "{this is malformed}\n"
    path.write_text(path.read_text(encoding="utf-8") + bad_line, encoding="utf-8")

    loaded, malformed = load_shadow_results(input_path=path)
    assert len(loaded) == 1
    assert malformed == 1


def test_row_validation_and_no_full_script_persistence(tmp_path: Path) -> None:
    ctx = _build_context()
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "shadow.jsonl")
    row = engine.evaluate_checkpoint(checkpoint="generation")
    normalized = validate_shadow_row(row)
    blob = json.dumps(normalized, ensure_ascii=False)
    assert ctx.script not in blob
    assert ctx.description not in blob
    assert "script_hash" in blob

