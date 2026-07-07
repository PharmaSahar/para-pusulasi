"""Profesyonel video testi - video_creator_pro ile tüm özellikler."""
import logging, json, subprocess
logging.basicConfig(level=logging.WARNING)
from src.tts_engine import TTSEngine
from src.video_creator_pro import VideoCreator
from src.image_fetcher import ImageFetcher
from pathlib import Path

test_script = (
    "2026 yılında dolar 50 TL mi 60 TL mi olacak? "
    "Bu kritik soruyu uzmanlar tartışıyor. "
    "Yatırımcıların yüzde 40'ı dolar almayı planlıyor. "
    "Faiz oranları en önemli etken. "
    "Enflasyon baskısı devam ediyor. "
    "Portföyünüzü korumak için bugün harekete geçin!"
)

print("1. TTS üretiliyor...")
tts = TTSEngine()
audio_path = tts.generate_audio(test_script, "/tmp/test3.mp3")
with open("/tmp/test3_timing.json") as f:
    sb = json.load(f)
print(f"   {len(sb)} cümle zamanlandı: {[s['text'][:30] for s in sb]}")

print("2. Pexels klipleri indiriliyor...")
fetcher = ImageFetcher()
clips = fetcher.fetch_video_clips("dolar yatırım finans", count=3, output_dir="/tmp/pexels_test")
print(f"   {len(clips)} klip indirildi")

print("3. Video oluşturuluyor...")
vc = VideoCreator()
vp = vc.create_video(
    audio_path="/tmp/test3.mp3",
    title="Dolar 2026: 50 TL mi 60 TL mi?",
    image_paths=clips or None,
    output_path="/tmp/test3.mp4",
    script=test_script,
)
size_mb = Path(vp).stat().st_size / 1_000_000
print(f"   Video hazır: {size_mb:.1f} MB → {vp}")
subprocess.Popen(["open", vp])
print("TAMAMLANDI!")
