"""
YouTube Shorts Olusturucu
Her uzun videodan 60 saniyelik dikey (9:16) Short otomatik uretir.
"""
import logging
import os
from pathlib import Path

import edge_tts
import asyncio
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, ColorClip, CompositeVideoClip, ImageClip, TextClip, VideoFileClip, concatenate_videoclips

from .config import config

logger = logging.getLogger(__name__)

SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
SHORT_DURATION = 58  # YouTube Shorts max 60sn


def _extract_short_script(full_script: str, hook: str = "") -> str:
    """Scriptten en etkili 60 saniyelik bolumu cikar (~350-400 kelime)."""
    if hook:
        lines = [hook.strip()]
    else:
        lines = []

    target_words = 380
    word_count = sum(len(l.split()) for l in lines)

    for line in full_script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
        word_count += len(stripped.split())
        if word_count >= target_words:
            break

    text = " ".join(lines)
    # Bitirise soru ekle
    text += " Bu videoyu begendiyseniz abone olmayı unutmayin!"
    return text


class ShortsCreator:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        self.cfg = channel_cfg if channel_cfg else _cfg
        self.channel_name = getattr(channel_cfg, "name", "Para Pusulasi") if channel_cfg else "Para Pusulasi"
        self.primary = tuple(getattr(channel_cfg, "color_primary", [212, 175, 55])[:3]) if channel_cfg else (212, 175, 55)
        self.bg = tuple(getattr(channel_cfg, "color_bg", [15, 25, 60])[:3]) if channel_cfg else (15, 25, 60)

    def get_font(self, size):
        font_paths = [
            # Linux (VPS)
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            # macOS
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ]
        for f in font_paths:
            if os.path.exists(f):
                try:
                    return ImageFont.truetype(f, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    async def _generate_audio(self, text: str, path: str):
        voice = "tr-TR-EmelNeural"
        communicate = edge_tts.Communicate(text, voice, rate="+10%")
        await communicate.save(path)

    def create_short(
        self,
        script: str,
        title: str,
        hook: str = "",
        image_paths: list | None = None,
        output_path: str | None = None,
    ) -> str:
        """60 saniyeye kadar dikey Short video olustur."""
        if not output_path:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = "".join(c for c in title[:25] if c.isalnum() or c in " _").strip()
            videos_dir = getattr(self.cfg, "videos_dir", config.output_dir + "/videos")
            output_path = f"{videos_dir}/{ts}_SHORT_{safe}.mp4"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Short script
        short_text = _extract_short_script(script, hook)
        logger.info(f"Short olusturuluyor: '{title}' ({len(short_text.split())} kelime)")

        # Ses
        audio_dir = getattr(self.cfg, "audio_dir", config.output_dir + "/audio")
        audio_path = output_path.replace(".mp4", "_audio.mp3")
        asyncio.run(self._generate_audio(short_text, audio_path))

        audio_clip = AudioFileClip(audio_path)
        duration = min(audio_clip.duration, SHORT_DURATION)
        audio_clip = audio_clip.subclipped(0, duration)

        # Arka plan (dikey)
        bg_arr = self._create_vertical_bg(duration, image_paths)

        # Baslik metni
        title_clip = self._create_short_title(title, duration)

        # Kanal ismi alt kisim
        channel_clip = self._create_channel_label(duration)

        # Shorts etiketi
        shorts_clip = self._create_shorts_badge(duration)

        composite = CompositeVideoClip(
            [bg_arr, title_clip, channel_clip, shorts_clip],
            size=(SHORT_WIDTH, SHORT_HEIGHT),
        ).with_audio(audio_clip)

        import uuid
        tmp_audio_file = output_path + f"_{uuid.uuid4().hex[:8]}_tmp.m4a"
        composite.write_videofile(
            output_path,
            fps=30,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=tmp_audio_file,
            remove_temp=True,
            logger=None,
            preset="fast",
            bitrate="1500k",
            threads=1,
        )
        try:
            Path(tmp_audio_file).unlink(missing_ok=True)
        except Exception:
            pass

        logger.info(f"Short hazir: {output_path}")
        return output_path

    def _create_vertical_bg(self, duration, image_paths=None):
        """Dikey 9:16 arka plan."""
        if image_paths:
            clip_duration = duration / len(image_paths)
            clips = []
            for p in image_paths:
                try:
                    ext = Path(p).suffix.lower()
                    if ext == ".mp4":
                        vc = VideoFileClip(p).without_audio()
                        from moviepy import vfx
                        if vc.duration < clip_duration:
                            vc = vc.with_effects([vfx.Loop(duration=clip_duration)])
                        else:
                            vc = vc.subclipped(0, clip_duration)
                        # Dikey crop (center crop)
                        vc = vc.resized(height=SHORT_HEIGHT)
                        if vc.w > SHORT_WIDTH:
                            x_center = vc.w // 2
                            vc = vc.cropped(x1=x_center-SHORT_WIDTH//2, x2=x_center+SHORT_WIDTH//2)
                        clips.append(vc)
                    else:
                        from PIL import Image as PILImg, ImageFilter
                        img = PILImg.open(p).convert("RGB")
                        # Dikey format
                        ratio = SHORT_HEIGHT / img.height
                        new_w = int(img.width * ratio)
                        img = img.resize((new_w, SHORT_HEIGHT))
                        if new_w > SHORT_WIDTH:
                            left = (new_w - SHORT_WIDTH) // 2
                            img = img.crop((left, 0, left+SHORT_WIDTH, SHORT_HEIGHT))
                        # Koyu overlay
                        overlay = PILImg.new("RGBA", img.size, (0,0,0,150))
                        img = PILImg.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
                        clips.append(ImageClip(np.array(img)).with_duration(clip_duration).resized((SHORT_WIDTH, SHORT_HEIGHT)))
                except Exception as e:
                    logger.warning(f"Gorsel yuklenemedi: {e}")
                    clips.append(self._gradient_bg_clip(clip_duration))

            if clips:
                return concatenate_videoclips(clips)

        return self._gradient_bg_clip(duration)

    def _gradient_bg_clip(self, duration):
        arr = np.zeros((SHORT_HEIGHT, SHORT_WIDTH, 3), dtype=np.uint8)
        for y in range(SHORT_HEIGHT):
            t = y / SHORT_HEIGHT
            arr[y, :] = [int(self.bg[i] + (max(0,self.bg[i]-30) - self.bg[i]) * t) for i in range(3)]
        return ImageClip(arr).with_duration(duration)

    def _create_short_title(self, title, duration):
        import textwrap
        wrapped = "\n".join(textwrap.wrap(title, width=22))
        return (
            TextClip(
                text=wrapped,
                font_size=85,
                color="white",
                font="Arial",
                size=(SHORT_WIDTH - 80, None),
                text_align="center",
                stroke_color="black",
                stroke_width=3,
            )
            .with_position(("center", SHORT_HEIGHT // 3))
            .with_duration(duration)
        )

    def _create_channel_label(self, duration):
        return (
            TextClip(
                text=f"@{self.channel_name.replace(' ', '')}",
                font_size=48,
                color="white",
                font="Arial",
                text_align="center",
                stroke_color="black",
                stroke_width=2,
            )
            .with_position(("center", SHORT_HEIGHT - 200))
            .with_duration(duration)
        )

    def _create_shorts_badge(self, duration):
        return (
            TextClip(
                text="#Shorts",
                font_size=42,
                color=self.primary,
                font="Arial",
                text_align="center",
                stroke_color="black",
                stroke_width=1,
            )
            .with_position(("center", SHORT_HEIGHT - 150))
            .with_duration(duration)
        )
