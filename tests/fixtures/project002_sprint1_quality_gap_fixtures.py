from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityGapFixture:
    fixture_id: str
    title: str
    input_data: dict[str, Any]
    expected_gap_categories: tuple[str, ...]
    expected_root_causes: tuple[str, ...]
    expected_scores: dict[str, float]


def _base_payload(*, fixture_id: str, domain: str, mode: str) -> dict[str, Any]:
    topic = {
        "finance": "Birikim ve risk yonetimi",
        "crypto": "Kripto volatilite ve risk",
        "career": "Kariyer gelisim stratejileri",
        "education": "Ogrenme verimliligi",
        "entrepreneurship": "Girisim buyume adimlari",
    }[domain]

    title = {
        "finance": "2026 Birikim Stratejisi: Risk ve Disiplin",
        "crypto": "Kripto Risk Yonetimi Rehberi",
        "career": "Kariyerde Maas Artisi Icin 7 Adim",
        "education": "Hizli Ogrenme Icin 5 Teknik",
        "entrepreneurship": "Startup Buyutme Icin Yol Haritasi",
    }[domain]

    return {
        "content_id": f"content_{fixture_id}",
        "channel_id": f"{domain}_channel",
        "content_type": "short" if mode == "shorts" else "video",
        "niche": domain,
        "topic": topic,
        "title": title,
        "thumbnail_prompt": "high contrast trusted educational single object focus max 2 short text",
        "script": (
            "Sok edici soru: Neden ayni gelirle bazi kisiler daha hizli birikim yapar? "
            "Giris: Bugun uc net ilke anlatacagim. 1. neden onemli. 2. nasil uygulayacaksin. 3. hatalar. "
            "Ornek: Aylik 7000 TL ile iki farkli senaryo. Veri ve analiz ile ilerliyoruz. "
            "Sonuc ve ozet: sonraki videoda uygulama listesi. Abone ol ve yorum yap."
        ),
        "description": (
            "Bu videoda adim adim uygulama stratejilerini anlatiyoruz.\n"
            "Onceki video ve sonraki video baglantilari ile izleme zinciri kurulur."
        ),
        "tags": ["finans", "yatirim", "risk", "birikim", "strateji", "egitim", "portfoy", "disiplin"],
        "hashtags": ["#finans", "#yatirim", "#birikim", "#strateji"],
        "playlist": f"{domain}_playlist",
        "cards": ["onceki video"],
        "end_screens": ["sonraki video"],
        "short_title": f"{title} #Shorts",
        "short_script": "Neden bu hata yapiliyor? 20 saniyede cevabi ve sonraki adim.",
        "review_queue": {},
        "analytics": {},
        "channel_profile": {"tone": domain, "authority_level": "medium"},
        "audience_profile": {"experience_level": "intermediate"},
    }


def _apply_pattern(payload: dict[str, Any], pattern: str) -> tuple[dict[str, Any], set[str], set[str], dict[str, float]]:
    p = dict(payload)
    expected_gaps: set[str] = set()
    expected_roots: set[str] = set()
    expected_scores = {
        "hook": 0.7,
        "seo": 0.75,
        "consistency": 0.72,
        "finance_safety": 0.8,
    }

    script_poor = (
        "Merhaba sevgili izleyiciler bugun bu videoda bu videoda bu videoda ayni seyi soyleyecegim. "
        "Detay yok tekrar var tekrar var tekrar var."
    )
    script_average = (
        "Bugun bu konuyu anlatacagiz. Ilk olarak temel bilgileri gorecegiz. "
        "Ardindan orneklerle devam edecegiz. Son bolumde ozet ve bir sonraki adim olacak."
    )

    if pattern == "excellent":
        expected_scores.update({"hook": 0.85, "seo": 0.9, "consistency": 0.85, "finance_safety": 0.95})
    elif pattern == "average":
        p["script"] = script_average
        expected_scores.update({"hook": 0.65, "seo": 0.75, "consistency": 0.7})
    elif pattern == "poor":
        p["script"] = script_poor
        p["description"] = "Kisa aciklama"
        p["tags"] = ["finans", "video"]
        p["hashtags"] = ["#finans"]
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION", "SEO_INCOMPLETE"})
        expected_roots.update({"Weak hook", "Overly generic opening", "Template repetition", "Weak search intent"})
        expected_scores.update({"hook": 0.2, "seo": 0.2, "consistency": 0.45})
    elif pattern == "duplicate":
        p["script"] = script_poor + " same template same template same template"
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION"})
        expected_roots.update({"Weak hook", "Overly generic opening", "Template repetition"})
        expected_scores.update({"hook": 0.25, "seo": 0.7, "consistency": 0.5})
    elif pattern == "weak_hook":
        p["script"] = script_poor
        p["short_script"] = "ortadan baslayan parca"
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION"})
        expected_roots.update({"Weak hook", "Overly generic opening", "Template repetition"})
        expected_scores.update({"hook": 0.2, "consistency": 0.48})
    elif pattern == "weak_hook_duplicate":
        p["script"] = script_poor + " tekrarla tekrarla tekrarla"
        p["short_script"] = "ortadan baslayan parca"
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION"})
        expected_roots.update({"Weak hook", "Overly generic opening", "Template repetition"})
        expected_scores.update({"hook": 0.15, "consistency": 0.42})
    elif pattern == "poor_seo":
        p["description"] = "Kisa aciklama"
        p["tags"] = ["finans", "video"]
        p["hashtags"] = ["#finans"]
        p["cards"] = []
        p["end_screens"] = []
        expected_gaps.add("SEO_INCOMPLETE")
        expected_roots.add("Weak search intent")
        expected_scores.update({"seo": 0.2})
    elif pattern == "weak_thumbnail":
        p["thumbnail_prompt"] = "business finance concept generic"
        expected_gaps.add("THUMBNAIL_TITLE_MISMATCH")
        expected_roots.add("Thumbnail mismatch")
        expected_scores.update({"consistency": 0.35})
    elif pattern == "misleading":
        p["title"] = "Sok! 10x garanti kazancla zengin ol"
        p["thumbnail_prompt"] = "luxury private jet instant rich guaranteed millionaire"
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "THUMBNAIL_MISLEADING_RISK", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Unsupported claims"})
        expected_scores.update({"hook": 0.55, "finance_safety": 0.0, "consistency": 0.32})
    elif pattern == "mismatch":
        p["title"] = "Kripto Pump ile Hemen Zenginlik"
        p["thumbnail_prompt"] = "business finance concept generic"
        p["script"] = script_average
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "THUMBNAIL_TITLE_MISMATCH", "CONTENT_FLOW_INCONSISTENT", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Thumbnail mismatch", "Unsupported claims", "Topic saturation"})
        expected_scores.update({"hook": 0.5, "consistency": 0.2, "finance_safety": 0.0})
    elif pattern == "safe_finance":
        p["title"] = "Risk yonetimi ile guvenli birikim rehberi"
        expected_scores.update({"finance_safety": 0.95, "consistency": 0.82})
    elif pattern == "unsafe_finance":
        p["title"] = "Kesin kazanc ve garanti kazancla zengin ol"
        p["thumbnail_prompt"] = "high contrast warning urgent"
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Unsupported claims"})
        expected_scores.update({"finance_safety": 0.0, "consistency": 0.4})
    elif pattern == "title_overclaim":
        p["title"] = "Sok! Pump ile kesin kazanc"
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Unsupported claims"})
        expected_scores.update({"hook": 0.45, "finance_safety": 0.0})
    elif pattern == "thumbnail_generic":
        p["thumbnail_prompt"] = "generic concept visual"
        expected_gaps.add("THUMBNAIL_TITLE_MISMATCH")
        expected_roots.add("Thumbnail mismatch")
        expected_scores.update({"consistency": 0.38})
    elif pattern == "consistency_break":
        p["title"] = "Kripto Pump ile Hemen Zenginlik"
        p["thumbnail_prompt"] = "generic concept visual"
        p["script"] = "Bu video sadece kariyer ozgecmis duzenleme adimlarini anlatiyor."
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "THUMBNAIL_TITLE_MISMATCH", "CONTENT_FLOW_INCONSISTENT", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Thumbnail mismatch", "Unsupported claims", "Topic saturation"})
        expected_scores.update({"consistency": 0.1, "finance_safety": 0.0})
    elif pattern == "seo_sparse":
        p["description"] = "Kisa"
        p["tags"] = ["risk"]
        p["hashtags"] = ["#risk"]
        expected_gaps.add("SEO_INCOMPLETE")
        expected_roots.add("Weak search intent")
        expected_scores.update({"seo": 0.15})
    elif pattern == "seo_strong":
        p["description"] = (
            "Bu videoda adim adim stratejiler ve veri odakli plan var.\n"
            "Onceki video ve sonraki video baglantilari ile zincir kurulur."
        )
        p["tags"] = ["finans", "risk", "birikim", "strateji", "egitim", "analiz", "portfoy", "plan"]
        p["hashtags"] = ["#finans", "#risk", "#birikim", "#strateji"]
        expected_scores.update({"seo": 0.92})
    elif pattern == "shorts_trimmed":
        p["short_script"] = "ortadan baslayan parca"
        p["script"] = script_poor
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION"})
        expected_roots.update({"Weak hook", "Overly generic opening", "Template repetition"})
        expected_scores.update({"hook": 0.18})
    elif pattern == "shorts_strong":
        p["short_script"] = "Sok soru: neden bu hata? cevabi var. devami icin sonraki videoda."
        expected_scores.update({"hook": 0.82})
    elif pattern == "repetition_heavy":
        p["script"] = "Merhaba bugun tekrar tekrar tekrar tekrar ayni cumleyi kullaniyorum tekrar tekrar tekrar."
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION"})
        expected_roots.update({"Weak hook", "Template repetition", "Overly generic opening"})
        expected_scores.update({"hook": 0.12, "consistency": 0.4})
    elif pattern == "repetition_light":
        p["script"] = script_average
        expected_scores.update({"hook": 0.6, "consistency": 0.68})
    elif pattern == "finance_safe_education":
        p["title"] = "Belirsizlikte risk yonetimi egitim rehberi"
        p["script"] = "Neden risk vardir, nasil yonetilir, orneklerle adim adim anlatiyoruz."
        expected_scores.update({"finance_safety": 0.95, "hook": 0.75})
    elif pattern == "finance_unsafe_claim":
        p["title"] = "Hemen al, kesin kazanc ve zengin ol"
        p["thumbnail_prompt"] = "urgent guaranteed millionaire"
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "THUMBNAIL_MISLEADING_RISK", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Unsupported claims"})
        expected_scores.update({"finance_safety": 0.0, "consistency": 0.28})
    elif pattern == "edge_minimal":
        p["script"] = "Merhaba sevgili izleyiciler bugun bu videoda tekrar var tekrar var tekrar var."
        p["description"] = "Kisa"
        p["tags"] = ["x"]
        p["hashtags"] = ["#x"]
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION", "SEO_INCOMPLETE"})
        expected_roots.update({"Weak hook", "Template repetition", "Overly generic opening", "Weak search intent"})
        expected_scores.update({"hook": 0.1, "seo": 0.1, "consistency": 0.35})
    elif pattern == "edge_balanced":
        p["script"] = script_average
        p["description"] = (
            "Bu konu dengeli analiz ile anlatilir.\n"
            "Onceki ve sonraki videolarla baglanti korunur."
        )
        expected_scores.update({"hook": 0.62, "seo": 0.8, "consistency": 0.7})
    elif pattern == "control_neutral":
        p["script"] = script_average
        p["thumbnail_prompt"] = "high contrast educational focus"
        expected_scores.update({"hook": 0.64, "seo": 0.76, "consistency": 0.74})
    else:
        raise ValueError(f"unknown_pattern:{pattern}")

    return p, expected_gaps, expected_roots, expected_scores


def build_project002_sprint1_fixtures() -> list[QualityGapFixture]:
    domains = ["finance", "crypto", "career", "education", "entrepreneurship"]
    modes = ["long", "shorts"]
    patterns = [
        "excellent",
        "average",
        "poor",
        "duplicate",
        "weak_hook",
        "weak_hook_duplicate",
        "poor_seo",
        "weak_thumbnail",
        "misleading",
        "mismatch",
        "safe_finance",
        "unsafe_finance",
        "title_overclaim",
        "thumbnail_generic",
        "consistency_break",
        "seo_sparse",
        "seo_strong",
        "shorts_trimmed",
        "shorts_strong",
        "repetition_heavy",
        "repetition_light",
        "finance_safe_education",
        "finance_unsafe_claim",
        "edge_minimal",
        "edge_balanced",
        "control_neutral",
    ]

    fixtures: list[QualityGapFixture] = []
    idx = 1
    for domain in domains:
        for mode in modes:
            for pattern in patterns:
                fixture_id = f"fx{idx:03d}"
                payload = _base_payload(fixture_id=fixture_id, domain=domain, mode=mode)
                payload, expected_gaps, expected_roots, expected_scores = _apply_pattern(payload, pattern)

                if mode == "shorts" and pattern not in {"shorts_trimmed", "shorts_strong"}:
                    payload["short_script"] = "Sok soru: neden bu hata? cevabi var. devami icin sonraki videoda."

                fixtures.append(
                    QualityGapFixture(
                        fixture_id=fixture_id,
                        title=f"{domain}:{mode}:{pattern}",
                        input_data=payload,
                        expected_gap_categories=tuple(sorted(expected_gaps)),
                        expected_root_causes=tuple(sorted(expected_roots)),
                        expected_scores={k: max(0.0, min(1.0, float(v))) for k, v in expected_scores.items()},
                    )
                )
                idx += 1
    return fixtures
