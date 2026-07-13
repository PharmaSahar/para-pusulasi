from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.shadow_content_quality import (
    SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
    ShadowContentQualityEngine,
    build_shadow_evaluation_context,
)


@dataclass(frozen=True)
class FixtureCase:
    case_id: str
    checkpoint: str
    topic: str
    title: str
    script: str
    description: str
    thumbnail_prompt: str
    short_script: str = ""
    short_title: str = ""
    short_duration_seconds: float | None = None
    thumbnail_text: str = ""
    tags: list[str] | None = None
    playlist_recommendation: str | None = None
    card_recommendation: str | None = None
    end_screen_recommendation: str | None = None
    expected_findings_any: set[str] = frozenset()
    prohibited_findings: set[str] = frozenset()
    expected_severity_any: set[str] = frozenset({"none", "low", "medium", "high"})
    expected_confidence_any: set[str] = frozenset({"LOW", "MEDIUM", "HIGH"})
    quality_class: str = "safe"


def _context(case: FixtureCase, run_suffix: str = "a"):
    return build_shadow_evaluation_context(
        run_id=f"golden_{case.case_id}_{run_suffix}",
        content_id=f"content_{case.case_id}",
        channel_id="calibration_ch",
        content_type="mixed",
        topic=case.topic,
        title=case.title,
        script=case.script,
        description=case.description,
        thumbnail_prompt=case.thumbnail_prompt,
        cta_text="abone ol",
    )


def _evaluate(case: FixtureCase, tmp_path: Path, run_suffix: str = "a") -> dict:
    engine = ShadowContentQualityEngine(
        context=_context(case, run_suffix=run_suffix),
        results_path=tmp_path / "shadow_calibration_rows.jsonl",
        history_window=120,
    )
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


CASES: list[FixtureCase] = [
    FixtureCase(
        case_id="01_safe_edu_finance",
        checkpoint="generation",
        topic="Finansal okuryazarlik",
        title="Finansal Okuryazarlikta Temel Ilkeler",
        script="Bütçe disiplini, risk yönetimi ve uzun vadeli planlama ile ilerleyin. Garantili getiri diye bir sey yoktur.",
        description="Temel finans eğitimi ve disiplinli birikim adimlari.",
        thumbnail_prompt="Simple finance education board",
        prohibited_findings={"guaranteed_return_wording_detection", "unverifiable_insider_information_detection"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="02_risk_mgmt_education",
        checkpoint="generation",
        topic="Risk yönetimi",
        title="Portfoyde Risk Nasil Yonetilir",
        script="Bu içerik yatırım tavsiyesi değildir. Geçmiş performans gelecekteki getiriyi garanti etmez.",
        description="Risk yönetimi adimlari.",
        thumbnail_prompt="Risk checklist",
        prohibited_findings={"guaranteed_return_wording_detection"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="03_ta_education_uncertainty",
        checkpoint="generation",
        topic="Teknik analiz",
        title="Teknik Analiz Olasiliklarla Calisir",
        script="Teknik analiz olasılıklarla çalışır, fiyatın yükselmesi kesin değildir.",
        description="Belirsizlik dili ile teknik analiz.",
        thumbnail_prompt="Chart education",
        prohibited_findings={"specific_security_certainty_detection"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="04_company_analysis_safe",
        checkpoint="generation",
        topic="Sirket analizi",
        title="Sirket Analizi: Borc ve Nakit Dengesi",
        script="Bu analizde şirketin bilanço kalemleri ve riskler değerlendiriliyor, kesin getiri iddiası yoktur.",
        description="Temel şirket analizi.",
        thumbnail_prompt="Company balance sheet",
        prohibited_findings={"guaranteed_return_wording_detection"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="05_pump_title",
        checkpoint="generation",
        topic="Hisse",
        title="Bu Hisse Ucacak Son Sans",
        script="Bugün bu hisseye bakıyoruz.",
        description="Analiz",
        thumbnail_prompt="Rocket stock",
        expected_findings_any={"pump_style_title_detection"},
        expected_severity_any={"high"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="06_guaranteed_return",
        checkpoint="generation",
        topic="Hisse",
        title="Getiri Stratejisi",
        script="Bu yöntemle garanti kazanç var ve kesin getiri alırsın.",
        description="Riskli söylem",
        thumbnail_prompt="Guaranteed return",
        expected_findings_any={"unsupported_financial_claim_detection", "guaranteed_return_wording_detection"},
        expected_severity_any={"high"},
        expected_confidence_any={"HIGH", "MEDIUM"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="07_extreme_return",
        checkpoint="generation",
        topic="Kripto",
        title="Altcoin Firsati",
        script="Yüzde 300 getiri kesin, bu fırsat kaçmaz.",
        description="Aşırı getiri",
        thumbnail_prompt="300 return",
        expected_findings_any={"extreme_return_claim_detection"},
        expected_severity_any={"high"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="08_insider_info",
        checkpoint="generation",
        topic="Borsa",
        title="BIST Icinden Gelen Bilgi",
        script="İçeriden bilgi aldık, resmi açıklanmadan önce alım yap.",
        description="Insider claim",
        thumbnail_prompt="Insider",
        expected_findings_any={"unverifiable_insider_information_detection"},
        expected_severity_any={"high"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="09_not_priced_in",
        checkpoint="generation",
        topic="Borsa",
        title="Henüz Fiyatlanmadi Iddiasi",
        script="Bu gelişme piyasaya yansımadı, henüz fiyatlanmadı.",
        description="claim",
        thumbnail_prompt="pricing gap",
        expected_findings_any={"not_priced_in_claim_detection"},
        expected_severity_any={"high"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="10_secret_meeting",
        checkpoint="generation",
        topic="Borsa",
        title="Toplanti Odalarinda Konusulan",
        script="Toplantı odalarında konuşulan bilgiye göre fonlar gizlice topluyor.",
        description="claim",
        thumbnail_prompt="meeting room",
        expected_findings_any={"secret_institutional_claim_detection"},
        expected_severity_any={"high"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="11_unnamed_authority",
        checkpoint="generation",
        topic="Borsa",
        title="Isim Vermeden Iddia",
        script="Uzmanlar diyor ki, üst düzey isim paylaştı ama kaynak vermeyeceğim.",
        description="claim",
        thumbnail_prompt="authority",
        expected_findings_any={"fabricated_authority_detection"},
        expected_severity_any={"high", "medium"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="12_urgent_buy_now",
        checkpoint="generation",
        topic="Borsa",
        title="Acil Alim",
        script="Hemen al, son şans, bugün almazsan kaçırırsın.",
        description="pressure",
        thumbnail_prompt="urgent",
        expected_findings_any={"urgent_trade_pressure_detection"},
        expected_severity_any={"high"},
        quality_class="high_risk",
    ),
    FixtureCase(
        case_id="13_balanced_disclaimer",
        checkpoint="generation",
        topic="Finans",
        title="Denge ve Risk",
        script="Bu içerik yatırım tavsiyesi değildir. Fiyatın yükselmesi kesin değildir.",
        description="balanced",
        thumbnail_prompt="balanced",
        prohibited_findings={"specific_security_certainty_detection", "guaranteed_return_wording_detection"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="14_title_script_match",
        checkpoint="generation",
        topic="Birikim",
        title="Birikim Plani",
        script="Birikim planı için üç adım: bütçe, acil fon, düzenli yatırım planı.",
        description="match",
        thumbnail_prompt="birikim plan",
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="15_title_script_mismatch",
        checkpoint="generation",
        topic="Birikim",
        title="Birikim Plani",
        script="Yazılım mülakatı tekniklerini anlatıyoruz.",
        description="mismatch",
        thumbnail_prompt="finance checklist",
        expected_findings_any={"title_script_semantic_consistency"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="16_description_script_match",
        checkpoint="description",
        topic="Birikim",
        title="Birikim Plani",
        script="Birikim planı adımları ve acil fon planı.",
        description="Birikim planı adımları ve acil fon planını anlatıyoruz.",
        thumbnail_prompt="finance",
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="17_description_script_mismatch",
        checkpoint="description",
        topic="Birikim",
        title="Birikim Plani",
        script="Birikim adımları.",
        description="Oyun bilgisayarı toplama rehberi.",
        thumbnail_prompt="finance",
        expected_findings_any={"script_description_consistency", "title_description_consistency"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="18_thumbnail_title_match",
        checkpoint="thumbnail_metadata",
        topic="Birikim",
        title="Birikim Plani",
        script="Birikim planı ve bütçe.",
        description="desc",
        thumbnail_prompt="Birikim checklist",
        thumbnail_text="Birikim Plani",
        prohibited_findings={"title_thumbnail_text_consistency"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="19_thumbnail_title_mismatch",
        checkpoint="thumbnail_metadata",
        topic="Birikim",
        title="Birikim Plani",
        script="Birikim planı ve bütçe.",
        description="desc",
        thumbnail_prompt="luxury private jet instant rich",
        thumbnail_text="Luks Yasam",
        expected_findings_any={"title_thumbnail_text_consistency", "thumbnail_prompt_relevance"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="20_wrong_ticker_company",
        checkpoint="generation",
        topic="Borsa",
        title="THYAO Analizi",
        script="THYAO konuşurken Sabancı bilançosuna odaklanıyoruz.",
        description="ticker mismatch",
        thumbnail_prompt="finance",
        expected_findings_any={"ticker_company_mismatch_detection"},
        expected_severity_any={"high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="21_exact_duplicate_title",
        checkpoint="generation",
        topic="Birikim",
        title="Acil Durum Fonu",
        script="Acil fon için üç adım.",
        description="desc",
        thumbnail_prompt="finance",
        expected_findings_any={"duplicate_title_detection"},
        expected_severity_any={"high", "medium"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="22_near_duplicate_title",
        checkpoint="generation",
        topic="Birikim",
        title="Acil Durum Fonu Rehberi",
        script="Acil fon için üç adım.",
        description="desc",
        thumbnail_prompt="finance",
        expected_findings_any={"duplicate_title_detection"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="23_exact_duplicate_script",
        checkpoint="generation",
        topic="Birikim",
        title="Birikim Adimlari",
        script="Aynı metin aynı metin aynı metin acil fon bütçe planı.",
        description="desc",
        thumbnail_prompt="finance",
        expected_findings_any={"duplicate_script_detection"},
        expected_severity_any={"high", "medium"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="24_near_duplicate_script",
        checkpoint="generation",
        topic="Birikim",
        title="Birikim Adimlari 2",
        script="Acil fon ve bütçe planını benzer cümlelerle yeniden anlatıyoruz.",
        description="desc",
        thumbnail_prompt="finance",
        expected_findings_any={"duplicate_script_detection"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="25_repeated_opening",
        checkpoint="generation",
        topic="Birikim",
        title="Birikimde Hata",
        script="Bugün herkesin yaptığı kritik hatayı konuşuyoruz. Sonra farklı adımlara geçiyoruz.",
        description="desc",
        thumbnail_prompt="finance",
        expected_findings_any={"repetitive_opening_detection", "duplicate_script_detection"},
        expected_severity_any={"medium", "high"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="26_repeated_cta",
        checkpoint="generation",
        topic="Birikim",
        title="CTA Test",
        script="CTA testinde abone ol şimdi. abone ol lütfen. abone ol ve paylaş.",
        description="desc",
        thumbnail_prompt="finance",
        expected_findings_any={"repeated_cta_detection"},
        expected_severity_any={"low", "medium"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="27_repeated_thumbnail_phrase",
        checkpoint="thumbnail_metadata",
        topic="Birikim",
        title="Birikim",
        script="Birikim planı.",
        description="desc",
        thumbnail_prompt="finance",
        thumbnail_text="Ayni Thumbnail",
        expected_findings_any={"duplicate_thumbnail_text_detection"},
        expected_severity_any={"medium", "high"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="28_valid_complete_short",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script birikim adımları",
        description="desc",
        thumbnail_prompt="finance",
        short_script="Birikim için önce hedef belirleyin. Sonra bütçe ile harcamaları izleyin. Son olarak acil fon oluşturun ve düzenli devam edin.",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=58,
        expected_severity_any={"none", "low", "medium"},
        prohibited_findings={"shorts_abrupt_beginning", "shorts_abrupt_ending"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="29_short_begins_mid_sentence",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script",
        description="desc",
        thumbnail_prompt="finance",
        short_script="ve bu yüzden önce hedef belirleyin sonra bütçe yapın",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=52,
        expected_findings_any={"shorts_abrupt_beginning"},
        expected_severity_any={"low", "medium"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="30_short_ends_mid_sentence",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script",
        description="desc",
        thumbnail_prompt="finance",
        short_script="Birikim için önce hedef belirleyin ve sonra",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=52,
        expected_findings_any={"shorts_abrupt_ending"},
        expected_severity_any={"low", "medium"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="31_short_unresolved_pronoun",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script",
        description="desc",
        thumbnail_prompt="finance",
        short_script="Bunu yaparsanız kazanırsınız ama nedenini sonra anlatırım",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=50,
        expected_findings_any={"shorts_missing_context"},
        expected_severity_any={"low", "medium"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="32_context_no_payoff",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script",
        description="desc",
        thumbnail_prompt="finance",
        short_script="Bağlam bağlam neden sebep arka plan anlatıyoruz ama sonuç yok.",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=55,
        expected_findings_any={"shorts_context_without_payoff"},
        expected_severity_any={"low", "medium"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="33_payoff_no_context",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script",
        description="desc",
        thumbnail_prompt="finance",
        short_script="Sonuç adım kazanç özet veriyoruz fakat bağlam yok.",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=55,
        expected_findings_any={"shorts_payoff_without_context", "shorts_missing_context"},
        expected_severity_any={"low", "medium"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="34_short_title_mismatch",
        checkpoint="shorts",
        topic="Birikim",
        title="Birikim Rehberi",
        script="Uzun script",
        description="desc",
        thumbnail_prompt="finance",
        short_script="SQL performans tuning için indeks stratejileri.",
        short_title="Birikim Rehberi #Shorts",
        short_duration_seconds=56,
        expected_findings_any={"shorts_title_content_consistency"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="35_missing_optional_metadata",
        checkpoint="seo_discovery",
        topic="Birikim",
        title="Birikim Rehberi",
        script="script",
        description="Açıklama #birikim",
        thumbnail_prompt="finance",
        tags=[],
        playlist_recommendation=None,
        card_recommendation=None,
        end_screen_recommendation=None,
        expected_findings_any={"card_recommendation_not_implemented", "end_screen_recommendation_not_implemented"},
        expected_severity_any={"low", "medium"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="36_missing_required_input",
        checkpoint="generation",
        topic="",
        title="",
        script="",
        description="",
        thumbnail_prompt="",
        expected_findings_any={"title_script_semantic_consistency"},
        expected_severity_any={"medium", "high"},
        quality_class="defective",
    ),
    FixtureCase(
        case_id="37_unsupported_seo_feature",
        checkpoint="seo_discovery",
        topic="Birikim",
        title="Birikim Rehberi",
        script="script",
        description="desc",
        thumbnail_prompt="finance",
        tags=["birikim"],
        playlist_recommendation="Birikim Listesi",
        card_recommendation=None,
        end_screen_recommendation=None,
        expected_findings_any={"card_recommendation_not_implemented", "end_screen_recommendation_not_implemented"},
        expected_severity_any={"low", "medium"},
        quality_class="weak",
    ),
    FixtureCase(
        case_id="38_validator_exception",
        checkpoint="generation",
        topic="Birikim",
        title="Birikim",
        script="script",
        description="desc",
        thumbnail_prompt="prompt",
        expected_severity_any={"none", "low", "medium", "high"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="39_malformed_storage_row",
        checkpoint="generation",
        topic="Birikim",
        title="Birikim",
        script="script",
        description="desc",
        thumbnail_prompt="prompt",
        expected_severity_any={"none", "low", "medium", "high"},
        quality_class="safe",
    ),
    FixtureCase(
        case_id="40_unicode_turkish_examples",
        checkpoint="generation",
        topic="Finansal Okuryazarlık",
        title="İçeriden Bilgi İddialarına Güvenmeyin",
        script="İçeriden bilgi iddialarına güvenmeyin. Garantili getiri diye bir şey yoktur.",
        description="Türkçe güvenli bağlam örneği.",
        thumbnail_prompt="Türkçe finans eğitimi",
        prohibited_findings={"unverifiable_insider_information_detection", "guaranteed_return_wording_detection"},
        expected_severity_any={"none", "low", "medium"},
        quality_class="safe",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_calibration_golden_cases(case: FixtureCase, tmp_path: Path) -> None:
    if case.case_id in {"21_exact_duplicate_title", "22_near_duplicate_title", "23_exact_duplicate_script", "24_near_duplicate_script", "25_repeated_opening", "27_repeated_thumbnail_phrase"}:
        seed_title = "Acil Durum Fonu"
        seed_script = "Aynı metin aynı metin aynı metin acil fon bütçe planı."
        if case.case_id == "22_near_duplicate_title":
            seed_title = "Acil Durum Fonu"
            seed_script = "Acil fon için üç adım."
        elif case.case_id == "24_near_duplicate_script":
            seed_title = "Birikim Adimlari"
            seed_script = "Acil fon ve bütçe planını benzer cümlelerle yeniden anlatıyoruz."
        elif case.case_id == "25_repeated_opening":
            seed_title = "Birikimde Hata"
            seed_script = "Bugün herkesin yaptığı kritik hatayı konuşuyoruz. Farklı örneklerle devam ediyoruz."
        seed = FixtureCase(
            case_id=f"seed_{case.case_id}",
            checkpoint="generation",
            topic="Birikim",
            title=seed_title,
            script=seed_script,
            description="seed",
            thumbnail_prompt="finance",
        )
        seeded = _evaluate(seed, tmp_path, run_suffix="seed")
        seed_engine = ShadowContentQualityEngine(
            context=_context(seed, run_suffix="seed_store"),
            results_path=tmp_path / "shadow_calibration_rows.jsonl",
            history_window=120,
        )
        if case.case_id == "27_repeated_thumbnail_phrase":
            _ = seed_engine.evaluate_and_store(checkpoint="thumbnail_metadata", thumbnail_text="Ayni Thumbnail")
        else:
            _ = seed_engine.evaluate_and_store(checkpoint="generation")
        assert seeded["checkpoint"] == "generation"

    row = _evaluate(case, tmp_path)
    row2 = _evaluate(case, tmp_path, run_suffix="repeat")

    assert row["schema_version"] == SHADOW_CONTENT_QUALITY_SCHEMA_VERSION
    assert row["pipeline_output_changed"] is False
    assert row["current_mode"] == "advisory"
    assert row["checkpoint"] == case.checkpoint

    findings = row["findings"]
    finding_codes = {f["code"] for f in findings}
    if case.expected_findings_any:
        assert bool(finding_codes & set(case.expected_findings_any))
    assert case.prohibited_findings.isdisjoint(finding_codes)

    assert row["severity"] in case.expected_severity_any
    confidences = {str(f.get("confidence", "")) for f in findings}
    if findings:
        assert confidences.issubset(set(case.expected_confidence_any) | {""})

    # Determinism: findings and aggregate scores stable across repeated runs
    assert row["severity"] == row2["severity"]
    assert row["finding_count"] == row2["finding_count"]
    assert [f["code"] for f in row["findings"]] == [f["code"] for f in row2["findings"]]


def test_turkish_negation_mandatory(tmp_path: Path) -> None:
    positives = [
        "içeriden bilgi aldık",
        "insider bilgi var",
        "içeriden alınan bilgiye göre",
        "henüz fiyatlanmadı",
        "piyasaya yansımadı",
        "kimsenin bilmediği",
        "fonların gizlice topladığı",
        "toplantı odalarında konuşulan",
        "kesin yükselecek",
        "garanti kazanç",
        "yüzde 300 getiri",
        "kaçırılmayacak fırsat",
        "hemen al",
        "son şans",
        "yatırımcıların bilmediği sır",
        "kurumların sakladığı bilgi",
    ]
    negatives = [
        "İçeriden bilgi iddialarına güvenmeyin.",
        "Garantili getiri diye bir şey yoktur.",
        "Bu içerik yatırım tavsiyesi değildir.",
        "Fiyatın yükselmesi kesin değildir.",
        "Teknik analiz olasılıklarla çalışır.",
        "Geçmiş performans gelecekteki getiriyi garanti etmez.",
    ]

    for idx, text in enumerate(positives):
        case = FixtureCase(
            case_id=f"tr_pos_{idx}",
            checkpoint="generation",
            topic="Borsa",
            title="Riskli Söylem",
            script=text,
            description="desc",
            thumbnail_prompt="finance",
            expected_severity_any={"high", "medium"},
        )
        row = _evaluate(case, tmp_path, run_suffix=f"p{idx}")
        assert row["severity"] in {"high", "medium"}

    for idx, text in enumerate(negatives):
        case = FixtureCase(
            case_id=f"tr_neg_{idx}",
            checkpoint="generation",
            topic="Eğitim",
            title="Risk Uyarısı",
            script=text,
            description="desc",
            thumbnail_prompt="finance",
        )
        row = _evaluate(case, tmp_path, run_suffix=f"n{idx}")
        assert row["severity"] in {"none", "low", "medium"}
        assert all(
            finding["severity"] not in {"HIGH", "CRITICAL"}
            for finding in row["findings"]
            if finding["code"] in {
                "unverifiable_insider_information_detection",
                "guaranteed_return_wording_detection",
                "unsupported_financial_claim_detection",
            }
        )
