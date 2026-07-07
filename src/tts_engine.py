"""
Metinden Sese Dönüştürme Motoru
Öncelik: Azure Neural TTS (SSML+duygu) > ElevenLabs > Edge TTS
"""
import asyncio
import logging
import os
from pathlib import Path

from .config import config

logger = logging.getLogger(__name__)

# Dil → ses eşleşmeleri
EDGE_VOICES = {
    "tr": "tr-TR-EmelNeural",
    "en": "en-US-JennyNeural",
    "de": "de-DE-KatjaNeural",
}

# Azure Neural TTS - En kaliteli Türkçe sesler (2024 modelleri)
AZURE_VOICES = {
    "tr":   "tr-TR-EmelNeural",          # Kadın — standart, doğal
    "tr_m": "tr-TR-AhmetNeural",         # Erkek — güçlü, profesyonel
    "en":   "en-US-AriaNeural",
}

# Her kanal için Azure sesi (erkek/kadın tercihi)
CHANNEL_AZURE_VOICE = {
    "para_pusulasi":      "tr-TR-Aydın:MAI-Voice-2",  # Erkek NeuralHD — otoriter finans
    "borsa_akademi":      "tr-TR-Aydın:MAI-Voice-2",  # Erkek NeuralHD — profesyonel analiz
    "kripto_rehber":      "tr-TR-Aydın:MAI-Voice-2",  # Erkek NeuralHD — enerjik kripto
    "kariyer_pusulasi":   "tr-TR-EmelNeural",          # Kadın — motive edici kariyer
    "saglik_pusulasi":    "tr-TR-EmelNeural",          # Kadın — güven veren sağlık
    "gayrimenkul_tv":     "tr-TR-Aydın:MAI-Voice-2",  # Erkek NeuralHD — prestijli
    "teknoloji_pusulasi": "tr-TR-Aydın:MAI-Voice-2",  # Erkek NeuralHD — teknoloji uzmanı
    "girisim_okulu":      "tr-TR-Aydın:MAI-Voice-2",  # Erkek NeuralHD — girişimci koç
    "egitim_rehberi":     "tr-TR-EmelNeural",          # Kadın — öğretici, samimi
}

# Türkçe finans anahtar kelimeleri → daha yavaş/vurgulu konuşma
EMPHASIS_WORDS_TR = [
    "dikkat", "önemli", "kritik", "uyarı", "fırsat", "risk",
    "kazanç", "kayıp", "tehlike", "şok", "acil", "kesinlikle",
    "asla", "mutlaka", "bugün", "hemen", "rekor",
]


class TTSEngine:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg

        self.language = getattr(cfg, "channel_language", None) or getattr(cfg, "language", "tr")
        self._channel_id = getattr(cfg, "channel_id", "")

        # ElevenLabs — sadece channel'da elevenlabs_enabled=True ise (öncelik 1)
        el_key = getattr(cfg, "elevenlabs_api_key", "") or os.getenv("ELEVENLABS_API_KEY", "")
        el_voice = getattr(cfg, "elevenlabs_voice_id", "") or os.getenv("ELEVENLABS_VOICE_ID", "")
        el_enabled = getattr(cfg, "elevenlabs_enabled", False)
        self._el_api_key = el_key
        self._el_voice_id = el_voice
        self.use_elevenlabs = bool(el_key) and not el_key.startswith("your_") and el_enabled

        # Azure TTS — ElevenLabs yoksa kullan (öncelik 2)
        self.azure_key = os.getenv("AZURE_TTS_KEY", "")
        self.azure_region = os.getenv("AZURE_TTS_REGION", "eastus")
        self.use_azure = bool(self.azure_key) and not self.use_elevenlabs

        if self.use_elevenlabs:
            logger.info(f"ElevenLabs TTS motoru [{self._el_voice_id[:12]}] (premium ses).")
        elif self.use_azure:
            logger.info("Azure Neural TTS motoru kullanılıyor (SSML + duygu).")
        elif self.use_azure:
            logger.info(f"Azure Neural TTS motoru (SSML + duygu).")
        else:
            logger.info("Edge TTS motoru kullanılıyor (ücretsiz).")

    def generate_audio(self, text: str, output_path: str | None = None) -> str:
        """Metni sese dönüştür ve dosyaya kaydet. Dosya yolunu döndür."""
        if not output_path:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"{config.audio_dir}/{timestamp}_narration.mp3"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        clean_text = self._clean_script(text)

        if self.use_azure:
            self._generate_azure_tts(clean_text, output_path)
        elif self.use_elevenlabs:
            self._generate_elevenlabs(clean_text, output_path)
        else:
            self._generate_edge_tts(clean_text, output_path)

        logger.info(f"Ses dosyası oluşturuldu: {output_path}")
        return output_path

    def _clean_script(self, script: str) -> str:
        """Script'ten Markdown başlıklarını temizle."""
        lines = []
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped:
                lines.append(stripped)
        return " ".join(lines)

    def _generate_azure_tts(self, text: str, output_path: str):
        """Azure Cognitive Services Neural TTS - tam SSML + duygu desteği."""
        import requests
        # Kanal-özel ses seç (her kanal için erkek/kadın ayarlı)
        channel_id = getattr(self, "_channel_id", "")
        voice = (
            CHANNEL_AZURE_VOICE.get(channel_id)
            or AZURE_VOICES.get(self.language, "tr-TR-EmelNeural")
        )
        ssml = self._build_ssml(text, voice)
        endpoint = f"https://{self.azure_region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.azure_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
        }
        resp = requests.post(endpoint, headers=headers, data=ssml.encode("utf-8"), timeout=60)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)
        self._save_estimated_timing(text, output_path)
        logger.info(f"Azure TTS tamamlandı [{voice}]: {output_path}")

    def _build_ssml(self, text: str, voice: str) -> str:
        """Türkçe finans içeriği için duygusal SSML oluştur."""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        parts = []
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            # Önemli kelimelere vurgu
            for word in EMPHASIS_WORDS_TR:
                sent = re.sub(
                    rf'(?i)\b({re.escape(word)})\b',
                    r'<emphasis level="strong">\1</emphasis>',
                    sent,
                )
            # Soru cümlesi → yavaş + biraz yüksek perde
            if sent.endswith('?'):
                parts.append(
                    f'<prosody rate="-8%" pitch="+6%">{sent}</prosody>'
                    f'<break time="500ms"/>'
                )
            # Ünlem → enerjik
            elif sent.endswith('!'):
                parts.append(
                    f'<prosody rate="+5%" pitch="+4%">{sent}</prosody>'
                    f'<break time="300ms"/>'
                )
            else:
                parts.append(f'{sent}<break time="420ms"/>')

        body = "\n    ".join(parts)
        return f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
       xmlns:mstts="http://www.w3.org/2001/mstts"
       xml:lang="tr-TR">
  <voice name="{voice}">
    <prosody rate="+6%" pitch="+2%">
    {body}
    </prosody>
  </voice>
</speak>"""

    def _save_estimated_timing(self, text: str, audio_path: str):
        """Azure için yaklaşık cümle zamanlaması (karakter tabanlı)."""
        import json, re
        from moviepy import AudioFileClip
        try:
            dur = AudioFileClip(audio_path).duration
        except Exception:
            dur = len(text) * 0.07
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
        total_chars = max(sum(len(s) for s in sentences), 1)
        boundaries = []
        t = 0.3
        for sent in sentences:
            seg = (len(sent) / total_chars) * (dur - 0.5)
            boundaries.append({"text": sent, "start": round(t, 3), "end": round(t + seg, 3)})
            t += seg
        timing_path = audio_path.replace(".mp3", "_timing.json")
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(boundaries, f, ensure_ascii=False)

    def _generate_edge_tts(self, text: str, output_path: str):
        """Microsoft Edge TTS ile doğal ses üret + cümle timing kaydet."""
        import edge_tts, json
        voice = EDGE_VOICES.get(self.language, "tr-TR-EmelNeural")
        processed = self._preprocess_emotion(text)
        sentence_boundaries = []

        async def _run():
            communicate = edge_tts.Communicate(processed, voice, rate="+8%")
            with open(output_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "SentenceBoundary":
                        sentence_boundaries.append({
                            "text": chunk["text"],
                            "start": chunk["offset"] / 10_000_000,
                            "end": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                        })

        asyncio.run(_run())
        timing_path = output_path.replace(".mp3", "_timing.json")
        with open(timing_path, "w", encoding="utf-8") as f:
            json.dump(sentence_boundaries, f, ensure_ascii=False)

    def _preprocess_emotion(self, text: str) -> str:
        """Doğal duraklama için metin ön işleme."""
        import re
        text = re.sub(r'\.\s+', '.  ', text)
        text = re.sub(r'\?\s+', '?  ', text)
        text = re.sub(r'!\s+', '!  ', text)
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        for s in sentences:
            if len(s) > 110 and s.count(',') == 0:
                mid = len(s) // 2
                idx = s.find(' ', mid)
                if idx > 0:
                    s = s[:idx] + ', ' + s[idx + 1:]
            result.append(s)
        return '  '.join(result)

    def _generate_elevenlabs(self, text: str, output_path: str):
        """ElevenLabs ile yüksek kalite ses üret — stüdyo seviyesi."""
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings

        # Kanal-özel key kullan, yoksa env'den al
        api_key = (
            getattr(self, "_el_api_key", None)
            or os.getenv("ELEVENLABS_API_KEY", "")
        )
        voice_id = (
            getattr(self, "_el_voice_id", None)
            or os.getenv("ELEVENLABS_VOICE_ID", "")
            or "JBFqnCBsd6RMkjVDRZzb"  # Varsayılan: George (İngilizce fallback)
        )

        client = ElevenLabs(api_key=api_key)

        # Ses kalite ayarları — doğallık için optimize
        voice_settings = VoiceSettings(
            stability=0.45,           # Düşük = daha doğal/dinamik tonlama
            similarity_boost=0.82,    # Yüksek = sese sadık kal
            style=0.35,               # Hafif stil varyasyonu — monotonluğu önler
            use_speaker_boost=True,   # Mikrofon kalitesi simülasyonu
        )

        audio_bytes = client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",  # Türkçe desteği en iyi model
            voice_settings=voice_settings,
            output_format="mp3_44100_128",       # 44kHz 128kbps — yayın kalitesi
        )

        with open(output_path, "wb") as f:
            for chunk in audio_bytes:
                if chunk:
                    f.write(chunk)

        # Altyazı zamanlama verisi oluştur (ElevenLabs'ta timestamp yok → tahmin et)
        self._save_estimated_timing(text, output_path)
        logger.info(f"ElevenLabs TTS tamamlandı: {output_path}")

