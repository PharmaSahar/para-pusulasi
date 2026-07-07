"""
ElevenLabs Ses Kurulum Yardımcısı
-----------------------------------
Her kanala farklı bir ElevenLabs sesi atar.
Kullanım:
  python setup_voices.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

REGISTRY_PATH = "channels/channel_registry.json"

# Kanallar için önerilen ses tipi açıklamaları
CHANNEL_VOICE_GUIDE = {
    "para_pusulasi":      "Otoriter erkek ses — finans otoritesi hissi",
    "borsa_akademi":      "Profesyonel erkek — ciddi borsa analisti",
    "kripto_rehber":      "Enerjik genç erkek — dinamik kripto anlatımı",
    "kariyer_pusulasi":   "Sıcak kadın sesi — motive edici kariyer koçu",
    "saglik_pusulasi":    "Sakin kadın — güven veren sağlık uzmanı",
    "gayrimenkul_tv":     "Olgun erkek — prestijli gayrimenkul danışmanı",
    "teknoloji_pusulasi": "Net genç erkek — yenilikçi teknoloji anlatımı",
    "girisim_okulu":      "İlham verici erkek — vizioner girişimci sesi",
    "egitim_rehberi":     "Açık kadın sesi — öğretici, net, samimi",
}


def main():
    reg = json.loads(Path(REGISTRY_PATH).read_text(encoding="utf-8"))
    channels = reg.get("channels", {})

    print("\n" + "="*60)
    print("  ElevenLabs Ses Kurulum Sihirbazı")
    print("="*60)
    print("\nHer kanal için:")
    print("  1. elevenlabs.io/app/voice-library → Language: Turkish")
    print("  2. Sesi beğen → Add to My Voices")
    print("  3. My Voices → Ses üzerine tıkla → Voice ID kopyala")
    print("\nBOŞ bırakırsan o kanal için global ELEVENLABS_VOICE_ID kullanılır.\n")

    changed = False
    for cid, data in channels.items():
        if data.get("status") != "active":
            continue

        guide = CHANNEL_VOICE_GUIDE.get(cid, "Türkçe ses seç")
        current = data.get("elevenlabs_voice_id", "")
        current_display = current if current else "(ayarlanmamış)"

        print(f"\n{'─'*50}")
        print(f"📺 {data.get('name', cid)}")
        print(f"   Öneri: {guide}")
        print(f"   Mevcut Voice ID: {current_display}")
        voice_id = input("   Yeni Voice ID (boş bırak = değiştirme): ").strip()

        if voice_id:
            channels[cid]["elevenlabs_voice_id"] = voice_id
            changed = True
            print(f"   ✅ Kaydedildi: {voice_id}")
        else:
            print("   ⏭  Atlandı")

    if changed:
        reg["channels"] = channels
        Path(REGISTRY_PATH).write_text(
            json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("\n✅ Registry güncellendi!")
        print("\nŞimdi VPS'e göndermek için:")
        print("  scp -i ~/.ssh/hetzner_vps channels/channel_registry.json root@168.119.126.103:/opt/parapusulasi/channels/")
    else:
        print("\n⏭  Hiçbir değişiklik yapılmadı.")


if __name__ == "__main__":
    main()
