from __future__ import annotations

from src.learning_foundation import (
    LEARNING_SIGNAL_SCHEMA_VERSION,
    QUALITY_SCORE_SCHEMA_VERSION,
    RECOMMENDATION_SCHEMA_VERSION,
    LearningSignal,
    QualityScore,
    QualityValidationInput,
    Recommendation,
    content_hash,
    detect_duplicate_text,
    detect_guaranteed_return_wording,
    detect_repeated_cta,
    detect_repetitive_opening,
    detect_unsupported_financial_claims,
    detect_unverifiable_insider_information,
    evaluate_quality_checkpoints,
    semantic_similarity_score,
)


def _build_payload() -> QualityValidationInput:
    return QualityValidationInput(
        channel_id="ch_finance",
        content_id="cnt_001",
        title="Birikim Yaparken Yapilan 5 Hata",
        script="Birikim plani, harcama disiplini ve risk yonetimi ile ilerleyin.",
        description="Birikim planinda yapilan hatalari ve duzeltme adimlarini anlatiyoruz.",
        thumbnail_prompt="Savings mistakes checklist with bold warning icon",
        thumbnail_text="5 Buyuk Hata",
        short_script="Birikim yaparken 5 kritik hataya dikkat edin.",
        rendered_video_text="Video birikim hatalarini ve cozumleri acikliyor.",
        hook_text="Birikim yapiyorum ama neden para birikmiyor?",
        cta_text="abone ol",
        historical_titles=["Birikim Icin Temel Kurallar"],
        historical_scripts=["Acil durum fonu ve butce takibi ile birikim yap."],
        historical_thumbnail_texts=["Tasarruf Rehberi"],
    )


def test_serializable_models() -> None:
    score = QualityScore(
        schema_version=QUALITY_SCORE_SCHEMA_VERSION,
        score_name="hook_quality",
        score_value=0.8,
        status="pass",
        details={"hint": "ok"},
    )
    signal = LearningSignal(
        schema_version=LEARNING_SIGNAL_SCHEMA_VERSION,
        signal_type="retention_drop",
        channel_id="ch_1",
        content_id="ct_1",
        severity="medium",
        payload={"minute": 2},
    )
    recommendation = Recommendation(
        schema_version=RECOMMENDATION_SCHEMA_VERSION,
        recommendation_type="improve_hook",
        priority="high",
        rationale="Drop in first 30 seconds",
        actions=["test a stronger opening"],
    )

    assert score.to_dict()["score_name"] == "hook_quality"
    assert signal.to_dict()["signal_type"] == "retention_drop"
    assert recommendation.to_dict()["priority"] == "high"


def test_semantic_similarity_and_hash() -> None:
    s1 = "bitcoin yatirim stratejisi"
    s2 = "yatirim stratejisi bitcoin"
    s3 = "saglikli beslenme listesi"

    assert semantic_similarity_score(s1, s2) > 0.6
    assert semantic_similarity_score(s1, s3) < 0.3
    assert content_hash(s1) == content_hash("  Bitcoin   yatirim stratejisi ")


def test_duplicate_and_repetition_detectors() -> None:
    is_dup, score = detect_duplicate_text(
        "Acil durum fonu nasil olusturulur",
        ["Acil durum fonu nasil olusturulur"],
        threshold=0.8,
    )
    assert is_dup is True
    assert score >= 0.99

    repeated_opening, opening_score = detect_repetitive_opening(
        "Ilk cumle ayni ve guclu bir acilis. Sonra farkli detaylar geliyor.",
        ["Ilk cumle ayni ve guclu bir acilis. Baska icerikte devam farkli."],
        threshold=0.35,
    )
    assert repeated_opening is True
    assert opening_score > 0.35

    has_repeated_cta, count = detect_repeated_cta("abone ol", "abone ol simdi. abone ol lutfen. abone ol")
    assert has_repeated_cta is True
    assert count == 3


def test_risky_phrase_detectors() -> None:
    text = "Bu islemle garanti getiri var ve kesin kazanc saglar. Iceriden bilgi aldik."
    assert detect_unsupported_financial_claims(text)
    assert detect_unverifiable_insider_information(text)
    assert detect_guaranteed_return_wording(text)


def test_quality_checkpoint_result_shape() -> None:
    payload = _build_payload()
    result = evaluate_quality_checkpoints(payload)
    data = result.to_dict()
    assert data["schema_version"] == "v1"
    assert data["channel_id"] == "ch_finance"
    assert data["content_id"] == "cnt_001"
    assert len(data["checks"]) >= 10
    assert any(item["score_name"] == "title_script_semantic_consistency" for item in data["checks"])


def test_quality_checkpoint_detects_duplicate_title() -> None:
    payload = _build_payload()
    payload = QualityValidationInput(
        **{
            **payload.__dict__,
            "historical_titles": [payload.title],
        }
    )
    result = evaluate_quality_checkpoints(payload)
    checks = {item.score_name: item for item in result.checks}
    assert checks["duplicate_title_detection"].status == "fail"
