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


def _content_payload(
    *,
    fixture_id: str,
    domain: str,
    mode: str,
    pattern: str,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    topic = {
        "finance": "Birikim ve risk yonetimi",
        "crypto": "Kripto volatilite ve risk",
        "career": "Kariyer gelisim stratejileri",
        "education": "Ogrenme verimliligi",
        "entrepreneurship": "Girisim buyume adimlari",
    }[domain]

    base_title = {
        "finance": "2026 Birikim Stratejisi: Risk ve Disiplin",
        "crypto": "Kripto Risk Yonetimi Rehberi",
        "career": "Kariyerde Maas Artisi Icin 7 Adim",
        "education": "Hizli Ogrenme Icin 5 Teknik",
        "entrepreneurship": "Startup Buyutme Icin Yol Haritasi",
    }[domain]

    script_excellent = (
        "Sok edici soru: Neden ayni gelirle bazi kisiler daha hizli birikim yapar? "
        "Giris: Bugun uc net ilke anlatacagim. 1. neden onemli. 2. nasil uygulayacaksin. 3. hatalar. "
        "Ornek: Aylik 7000 TL ile iki farkli senaryo. Veri ve analiz ile ilerliyoruz. "
        "Sonuc ve ozet: sonraki videoda uygulama listesi. Abone ol ve yorum yap."
    )
    script_average = (
        "Bugun bu konuyu anlatacagiz. Ilk olarak temel bilgileri gorecegiz. "
        "Ardindan orneklerle devam edecegiz. Son bolumde ozet ve bir sonraki adim olacak."
    )
    script_poor = (
        "Merhaba sevgili izleyiciler bugun bu videoda bu videoda bu videoda ayni seyi soyleyecegim. "
        "Detay yok tekrar var tekrar var tekrar var."
    )

    thumb_good = "high contrast trusted educational single object focus max 2 short text"
    thumb_weak = "business finance concept generic"
    thumb_misleading = "luxury private jet instant rich guaranteed millionaire"

    description_good = (
        "Bu videoda adim adim uygulama stratejilerini anlatiyoruz.\n"
        "Onceki video ve sonraki video baglantilari ile izleme zinciri kurulur."
    )
    description_poor = "Kisa aciklama"

    tags_good = ["finans", "yatirim", "risk", "birikim", "strateji", "egitim", "portfoy", "disiplin"]
    tags_poor = ["finans", "video"]
    hashtags_good = ["#finans", "#yatirim", "#birikim", "#strateji"]
    hashtags_poor = ["#finans"]

    title = base_title
    script = script_excellent
    thumbnail_prompt = thumb_good
    description = description_good
    tags = tags_good
    hashtags = hashtags_good
    cards = ["onceki video"]
    end_screens = ["sonraki video"]
    short_script = "Neden bu hata yapiliyor? 20 saniyede cevabi ve sonraki adim."

    expected_gaps: set[str] = set()
    expected_roots: set[str] = set()

    if pattern == "excellent":
        pass
    elif pattern == "average":
        script = script_average
    elif pattern == "poor":
        script = script_poor
        description = description_poor
        tags = tags_poor
        hashtags = hashtags_poor
        expected_gaps.update({"SCRIPT_HOOK", "SCRIPT_REPETITION", "SEO_INCOMPLETE"})
        expected_roots.update({"Weak hook", "Template repetition", "Weak search intent"})
    elif pattern == "duplicate":
        script = script_poor + " same template same template same template"
        expected_gaps.update({"SCRIPT_REPETITION"})
        expected_roots.update({"Template repetition"})
    elif pattern == "misleading":
        title = "Sok! 10x garanti kazancla zengin ol"
        thumbnail_prompt = thumb_misleading
        expected_gaps.update({"THUMBNAIL_MISLEADING_RISK", "TITLE_PROMISE_MISMATCH", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Unsupported claims"})
    elif pattern == "weak_thumbnail":
        thumbnail_prompt = thumb_weak
        expected_gaps.update({"THUMBNAIL_TITLE_MISMATCH"})
        expected_roots.update({"Thumbnail mismatch"})
    elif pattern == "weak_hook":
        script = script_poor
        short_script = "ortadan baslayan parca"
        expected_gaps.update({"SCRIPT_HOOK"})
        expected_roots.update({"Weak hook", "Overly generic opening"})
    elif pattern == "poor_seo":
        description = description_poor
        tags = tags_poor
        hashtags = hashtags_poor
        cards = []
        end_screens = []
        expected_gaps.update({"SEO_INCOMPLETE"})
        expected_roots.update({"Weak search intent"})
    elif pattern == "excellent_seo":
        description = description_good + "\nIzle: onceki video. Sonraki video baglantisi burada."
    elif pattern == "mismatch":
        title = "Kripto Pump ile Hemen Zenginlik"
        thumbnail_prompt = thumb_weak
        script = script_average
        expected_gaps.update({"TITLE_PROMISE_MISMATCH", "THUMBNAIL_TITLE_MISMATCH", "CONTENT_FLOW_INCONSISTENT", "FINANCE_SAFETY"})
        expected_roots.update({"Promise mismatch", "Thumbnail mismatch", "Unsupported claims"})

    if domain in {"finance", "crypto"} and pattern in {"misleading", "mismatch"}:
        expected_gaps.add("FINANCE_SAFETY")
        expected_roots.add("Unsupported claims")

    if mode == "shorts":
        short_script = "Sok soru: neden bu hata? cevabi var. devami icin sonraki videoda."

    payload = {
        "content_id": f"content_{fixture_id}",
        "channel_id": f"{domain}_channel",
        "content_type": "short" if mode == "shorts" else "video",
        "niche": domain,
        "topic": topic,
        "title": title,
        "thumbnail_prompt": thumbnail_prompt,
        "script": script,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "playlist": f"{domain}_playlist",
        "cards": cards,
        "end_screens": end_screens,
        "short_title": f"{title} #Shorts",
        "short_script": short_script,
        "review_queue": {},
        "analytics": {},
        "channel_profile": {
            "tone": domain,
            "authority_level": "medium",
        },
        "audience_profile": {
            "experience_level": "beginner" if pattern in {"excellent", "weak_hook"} else "intermediate",
        },
    }

    return payload, tuple(sorted(expected_gaps)), tuple(sorted(expected_roots))


def build_project002_sprint1_fixtures() -> list[QualityGapFixture]:
    domains = ["finance", "crypto", "career", "education", "entrepreneurship"]
    modes = ["long", "shorts"]
    patterns = [
        "excellent",
        "average",
        "poor",
        "duplicate",
        "misleading",
        "weak_thumbnail",
        "weak_hook",
        "poor_seo",
        "excellent_seo",
        "mismatch",
    ]

    fixtures: list[QualityGapFixture] = []
    idx = 1
    for domain in domains:
        for mode in modes:
            for pattern in patterns:
                fixture_id = f"fx{idx:03d}"
                payload, expected_gaps, expected_roots = _content_payload(
                    fixture_id=fixture_id,
                    domain=domain,
                    mode=mode,
                    pattern=pattern,
                )
                fixtures.append(
                    QualityGapFixture(
                        fixture_id=fixture_id,
                        title=f"{domain}:{mode}:{pattern}",
                        input_data=payload,
                        expected_gap_categories=expected_gaps,
                        expected_root_causes=expected_roots,
                    )
                )
                idx += 1
    return fixtures
