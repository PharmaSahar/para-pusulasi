"""Profesyonel video testi v2 - tüm özellikler görünür uzunlukta."""
import logging, json, subprocess
logging.basicConfig(level=logging.WARNING)
from src.tts_engine import TTSEngine
from src.video_creator_pro import VideoCreator
from src.image_fetcher import ImageFetcher
from pathlib import Path

# Uzun script: intro / lower third / chyron / outro hepsini görmek için
test_script = (
    "Para Pusulası kanalına hoş geldiniz! "
    "Bugün Türkiye'nin en kritik finans sorusunu ele alıyoruz. "
    "2026 yılında dolar kaç TL olacak? Bu sorunun cevabı portföyünüzü doğrudan etkiliyor. "
    "Piyasa uzmanlarının yüzde 68'i dolar kurunda ciddi oynaklık bekliyor. "
    "Merkez Bankası'nın son faiz kararları piyasaları sarstı ve yatırımcılar tetikte bekliyor. "
    "Dikkat: enflasyon yüzde 65 seviyesinde seyrederken reel getiri elde etmek zorlaşıyor. "
    "Altın, dolar ve borsa arasında doğru seçim yapmazsanız yüzde 30 kayıp yaşayabilirsiniz. "
    "Bu yıl en güvenli liman hangisi? Hepsini karşılaştırıyoruz. "
    "Faiz oranları yüzde 42'de seyrediyor ve bu oran yatırım kararlarını kökten değiştiriyor. "
    "Kişisel finans planınızı bugün gözden geçirin. "
    "Abone olun, bildirimleri açın ve bir sonraki videomuzu kaçırmayın!"
)

print("1. TTS üretiliyor...")
tts = TTSEngine()
audio_path = tts.generate_audio(test_script, "/tmp/test_pro.mp3")
with open("/tmp/test_pro_timing.json") as f:
    sb = json.load(f)
print(f"   {len(sb)} cümle zamanlandı, toplam ~{sb[-1]['end']:.0f}s")

print("2. Pexels klipleri indiriliyor (6 klip)...")
fetcher = ImageFetcher()
clips = fetcher.fetch_video_clips("dolar yatırım borsa finans", count=6, output_dir="/tmp/pexels_pro")
print(f"   {len(clips)} klip hazır")

print("3. Profesyonel render başlıyor...")
vc = VideoCreator()
vp = vc.create_video(
    audio_path="/tmp/test_pro.mp3",
    title="Dolar 2026: 50 TL mi 60 TL mi?",
    image_paths=clips or None,
    output_path="/tmp/test_pro.mp4",
    script=test_script,
)
size_mb = Path(vp).stat().st_size / 1_000_000
print(f"✅ Video hazır: {size_mb:.1f} MB → {vp}")
subprocess.Popen(["open", vp])
