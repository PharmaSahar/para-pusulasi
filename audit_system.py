"""Sistem audit scripti - tüm kritik kontroller."""
from pathlib import Path

OK = "[OK]"
FAIL = "[!!]"
results = []
errors = []

def check(filepath, desc, pattern):
    try:
        code = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        ok = pattern in code
        status = OK if ok else FAIL
        results.append(f"{status} {filepath}: {desc}")
        if not ok:
            errors.append(f"{filepath}: {desc}")
    except FileNotFoundError:
        results.append(f"{FAIL} {filepath}: DOSYA BULUNAMADI")
        errors.append(filepath)

# pipeline.py
check("src/pipeline.py", "Short -> public upload", 'privacy="public"')
check("src/pipeline.py", "Script video creator'a geciyor", "script=content.script")
check("src/pipeline.py", "Short publish_at=None", "publish_at=None")

# youtube_uploader.py
check("src/youtube_uploader.py", "Tag sanitization metodu", "_sanitize_tags")
check("src/youtube_uploader.py", "clean_tags kullaniliyor", "clean_tags")
check("src/youtube_uploader.py", "Max 500 char limit", "total_len")

# channel_manager.py
check("src/channel_manager.py", "channel_id duplicate fix", "data.pop")
check("src/channel_manager.py", "Unknown field filter", "known = {f.name")
check("src/channel_manager.py", "Optional fields (category_id default)", '"27"')
check("src/channel_manager.py", "Optional fields (persona default)", "persona: str")

# tts_engine.py
check("src/tts_engine.py", "SentenceBoundary timing", "SentenceBoundary")
check("src/tts_engine.py", "Emotion preprocessing", "_preprocess_emotion")
check("src/tts_engine.py", "Azure TTS hazir", "AZURE_TTS_KEY")
check("src/tts_engine.py", "ElevenLabs fallback", "elevenlabs")

# video_creator_pro.py
check("src/video_creator_pro.py", "Multi-font fallback (_load_font)", "_load_font")
check("src/video_creator_pro.py", "ColorClip+opacity (no RGBA bug)", "with_opacity")
check("src/video_creator_pro.py", "Intro card (branded)", "_create_intro_card")
check("src/video_creator_pro.py", "Lower thirds (TV style)", "_create_lower_thirds")
check("src/video_creator_pro.py", "Stat chyrons", "_create_stat_chyrons")
check("src/video_creator_pro.py", "Netflix subtitles", "_create_subtitle_clips")
check("src/video_creator_pro.py", "Outro card", "_create_outro_card")
check("src/video_creator_pro.py", "Cinematic grade", "_cinematic_grade")

# scheduler.py
check("scheduler.py", "v4.0 Production Ready", "v4.0")
check("scheduler.py", "Memory cleanup (force_cleanup)", "force_cleanup")
check("scheduler.py", "Daily maintenance 03:00", "maintenance_job")
check("scheduler.py", "scheduler_utils optional import", "except ImportError")
check("scheduler.py", "Retry logic (3 attempts)", "max_attempts")
check("scheduler.py", "Disk check before render", "check_disk_space")
check("scheduler.py", "Telegram notify on upload", "notify_upload")
check("scheduler.py", "Telegram notify on error", "notify_error")

# scheduler_utils.py
check("src/scheduler_utils.py", "Disk cleanup (48h)", "cleanup_old_renders")
check("src/scheduler_utils.py", "Disk space check", "get_free_disk_gb")
check("src/scheduler_utils.py", "Memory GC", "force_cleanup")
check("src/scheduler_utils.py", "Telegram send_telegram", "send_telegram")
check("src/scheduler_utils.py", "Topic deduplication", "is_topic_used")
check("src/scheduler_utils.py", "Health check", "health_check")
check("src/scheduler_utils.py", "Retry with_retry", "with_retry")

# .env kontrolu
print("\n--- .ENV KONTROL ---")
env_text = Path(".env").read_text(encoding="utf-8", errors="ignore")
env_lines = {l.split("=", 1)[0]: l.split("=", 1)[1].strip()
             for l in env_text.splitlines() if "=" in l and not l.startswith("#")}

required_keys = [
    "ANTHROPIC_API_KEY", "PEXELS_API_KEY",
    "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
]
for key in required_keys:
    val = env_keys.get(key, "") if (env_keys := env_lines) else ""
    ok = bool(val and "your_" not in val and len(val) > 5)
    status = OK if ok else FAIL
    results.append(f"{status} .env: {key}")
    if not ok:
        errors.append(f".env: {key} eksik veya placeholder")

# OAuth token kontrolu
print("\n--- OAUTH TOKEN KONTROL ---")
for ch in ["para_pusulasi", "borsa_akademi", "kripto_rehber", "kariyer_pusulasi"]:
    token_path = Path(f"channels/{ch}/youtube_token.pickle")
    ok = token_path.exists()
    status = OK if ok else FAIL
    results.append(f"{status} Token: {ch}")
    if not ok:
        errors.append(f"Token eksik: {ch}")

# VPS baglantisi
print("\n--- VPS KONTROL ---")
import subprocess
try:
    result = subprocess.run(
        ["ssh", "-i", str(Path.home() / ".ssh/hetzner_vps"),
         "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
         "root@168.119.126.103",
         "systemctl is-active parapusulasi && echo VPS_OK"],
        capture_output=True, text=True, timeout=15
    )
    vps_ok = "VPS_OK" in result.stdout or "active" in result.stdout
    results.append(f"{OK if vps_ok else FAIL} VPS: parapusulasi servisi {'aktif' if vps_ok else 'CALISMIYOR'}")
    if not vps_ok:
        errors.append("VPS: parapusulasi servisi aktif degil")
except Exception as e:
    results.append(f"{FAIL} VPS: Baglanti hatasi - {e}")
    errors.append("VPS baglantisi")

# Sonuclari yazdir
print("\n" + "="*60)
print("AUDIT SONUCLARI")
print("="*60)
for r in results:
    print(r)

print("\n" + "="*60)
if errors:
    print(f"!! {len(errors)} SORUN BULUNDU:")
    for e in errors:
        print(f"  - {e}")
else:
    print("OK TUM KONTROLLER GECTI - SISTEM HAZIR")
print("="*60)
