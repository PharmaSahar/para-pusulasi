"""Video Olusturma Modulu - Ses + Pexels video klipleri veya gradient arka plan"""
import json
import logging
import random
import re
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)

from .config import config

logger = logging.getLogger(__name__)


class VideoCreator:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg
        self.width = cfg.video_width
        self.height = cfg.video_height
        self.fps = 24
        # Kanal renklerini al
        if channel_cfg and hasattr(channel_cfg, "color_primary"):
            self.color_primary = tuple(channel_cfg.color_primary)
            self.color_bg = tuple(channel_cfg.color_bg)
            self.channel_name = channel_cfg.name
        else:
            self.color_primary = (212, 175, 55)
            self.color_bg = (15, 25, 60)
            self.channel_name = "Para Pusulasi"
        # Watermark yolu
        if channel_cfg and hasattr(channel_cfg, "base_dir"):
            wm_channel = f"{channel_cfg.base_dir}/branding/watermark_150x150.png"
            self.watermark_path = wm_channel if Path(wm_channel).exists() else "assets/branding/watermark_150x150.png"
        else:
            self.watermark_path = "assets/branding/watermark_150x150.png"

    def create_video(self, audio_path, title, image_paths=None, output_path=None, script=None):
        if not output_path:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = "".join(c for c in title[:30] if c.isalnum() or c in " _").strip()
            output_path = f"{config.videos_dir}/{ts}_{safe}.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info("Video olusturuluyor: " + title)
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration
        if image_paths:
            bg = self._create_image_slideshow(image_paths, duration)
        else:
            bg = self._create_gradient_background(duration)
        title_clip = self._create_title_clip(title, duration)
        footer_clip = self._create_footer_clip(duration)

        layers = [bg, title_clip, footer_clip]

        # Koyu seritler (video klipli modda okunurluk icin)
        if image_paths:
            layers.extend(self._create_dark_overlay(duration))

        # Watermark: sag alt kosede
        watermark = self._create_watermark_clip(duration)
        if watermark:
            layers.append(watermark)

        # Altyazi (word boundary timing varsa)
        timing_path = audio_path.replace(".mp3", "_timing.json")
        word_boundaries = []
        if Path(timing_path).exists():
            try:
                with open(timing_path, encoding="utf-8") as f:
                    word_boundaries = json.load(f)
            except Exception:
                pass

        subtitle_clips = self._create_subtitle_clips(word_boundaries, duration, script)
        layers.extend(subtitle_clips)

        # Anahtar nokta popup kutulari
        if script:
            key_points = self._extract_key_points(script)
            popup_clips = self._create_text_popup_clips(key_points, duration)
            layers.extend(popup_clips)

        composite = CompositeVideoClip(layers, size=(self.width, self.height)).with_audio(audio_clip)
        composite.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile="temp_audio.m4a",
            remove_temp=True,
            logger=None,
        )
        logger.info("Video hazir: " + output_path)
        return output_path

    def _create_watermark_clip(self, duration):
        if not Path(self.watermark_path).exists():
            return None
        try:
            wm_img = Image.open(self.watermark_path).convert("RGBA")
            wm_w, wm_h = wm_img.size
            # Sag alt kose - 20px kenar boslugu
            x = self.width - wm_w - 20
            y = self.height - wm_h - 20
            wm_arr = np.array(wm_img)
            clip = (
                ImageClip(wm_arr)
                .with_duration(duration)
                .with_position((x, y))
            )
            return clip
        except Exception as e:
            logger.warning("Watermark eklenemedi: " + str(e))
            return None

    def _create_image_slideshow(self, image_paths, duration):
        """Video klipleri veya fotograflari arka plan olarak kullan."""
        from moviepy import vfx, ColorClip
        clips = []
        total = len(image_paths)
        per_clip = duration / total

        for idx, p in enumerate(image_paths):
            ext = Path(p).suffix.lower()
            if ext == ".mp4":
                try:
                    vc = VideoFileClip(p).without_audio()
                    # Rastgele baslangic noktasi - tekrari onle
                    if vc.duration > per_clip + 2:
                        max_start = vc.duration - per_clip - 1
                        start_offset = random.uniform(0, max_start)
                    else:
                        start_offset = 0
                    if vc.duration < per_clip:
                        vc = vc.with_effects([vfx.Loop(duration=per_clip)])
                    else:
                        vc = vc.subclipped(start_offset, start_offset + per_clip)
                    vc = vc.resized((self.width, self.height))
                    clips.append(vc)
                    continue
                except Exception as e:
                    logger.warning("Video klibi yuklenemedi: " + str(e))
                    clips.append(self._create_gradient_background(per_clip))
                    continue
            # Fotograf - Ken Burns zoom uygula
            try:
                arr = np.array(self._fit_image(p))
                img_clip = ImageClip(arr).with_duration(per_clip).resized((self.width, self.height))
                clips.append(img_clip)
            except Exception as e:
                logger.warning("Fotograf yuklenemedi: " + str(e))
                clips.append(self._create_gradient_background(per_clip))

        return concatenate_videoclips(clips)

    def _apply_ken_burns(self, clip, effect="zoom_in"):
        """Yer tutucu - video kliplerde kullanilmiyor."""
        return clip

    def _create_dark_overlay(self, duration):
        """Ust ve alt kisimda koyu serit - metin okunurlugu icin."""
        # Ust serit (baslik)
        top = ColorClip(size=(self.width, 140), color=(0, 0, 0)).with_duration(duration).with_opacity(0.55).with_position((0, 0))
        # Alt serit (altyazi + footer)
        bottom = ColorClip(size=(self.width, 120), color=(0, 0, 0)).with_duration(duration).with_opacity(0.65).with_position((0, self.height - 120))
        return [top, bottom]

    def _fit_image(self, path):
        img = Image.open(path).convert("RGB")
        bg = img.resize((self.width, self.height), Image.LANCZOS).filter(
            ImageFilter.GaussianBlur(radius=20)
        )
        ratio = min(self.width / img.width, self.height / img.height)
        nw, nh = int(img.width * ratio), int(img.height * ratio)
        fg = img.resize((nw, nh), Image.LANCZOS)
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 100))
        bg.paste(fg, ((self.width - nw) // 2, (self.height - nh) // 2))
        return Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    def _create_gradient_background(self, duration):
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)
        for y in range(self.height):
            r = int(10 + (y / self.height) * 20)
            g = int(10 + (y / self.height) * 15)
            b = int(35 + (y / self.height) * 40)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        return ImageClip(np.array(img)).with_duration(duration)

    def _create_title_clip(self, title, duration):
        wrapped = "\n".join(textwrap.wrap(title, width=35))
        return (
            TextClip(
                text=wrapped,
                font_size=72,
                color="white",
                font="Arial",
                size=(self.width - 200, None),
                text_align="center",
                stroke_color="black",
                stroke_width=2,
            )
            .with_position("center")
            .with_duration(duration)
        )

    def _create_footer_clip(self, duration):
        return (
            TextClip(
                text="AI Destekli Icerik | Abone Ol",
                font_size=32,
                color="white",
                font="Arial",
                text_align="center",
                stroke_color="black",
                stroke_width=1,
            )
            .with_position(("center", self.height - 80))
            .with_duration(duration)
        )

    def _extract_key_points(self, script: str) -> list[str]:
        """Script metninden onemli istatistik ve noktalari cikart."""
        sentences = re.split(r'(?<=[.!?])\s+', script.strip())
        key_points = []
        for s in sentences:
            s = s.strip()
            if not s or len(s) < 20:
                continue
            # Rakam/istatistik iceren cumleler
            if re.search(r'\d+[%₺$€]|\d{4}|\d+\.\d+', s):
                key_points.append(s)
            # Anahtar kelime iceren cumleler
            elif any(kw in s.lower() for kw in ['dikkat', 'önemli', 'kritik', 'fırsat', 'kazanç', 'risk']):
                key_points.append(s)
        # Maks 4 popupı kısa tut
        return [p[:90] for p in key_points[:4]]

    def _create_subtitle_clips(self, word_boundaries: list, duration: float, script: str | None = None) -> list:
        """Alt kisimda profesyonel altyazi - SentenceBoundary timing veya script tahminle."""
        WORDS_PER_LINE = 7
        subtitle_clips = []

        if word_boundaries:
            # Her cumle icin gercek zamanlamaya gore altyazi
            for sb in word_boundaries:
                text = sb.get("text", "").strip()
                if not text:
                    continue
                start = sb["start"]
                end = sb["end"]
                chunk_dur = max(min(end - start, duration - start - 0.1), 0.5)
                if start >= duration - 0.5:
                    break
                # Uzun cumleleri satirlara bol
                words = text.split()
                j = 0
                line_dur = chunk_dur / max(len(words) // WORDS_PER_LINE + 1, 1)
                t = start
                while j < len(words):
                    chunk_words = words[j:j + WORDS_PER_LINE]
                    subtitle_clips.extend(self._make_subtitle_overlay(
                        " ".join(chunk_words), t, max(line_dur, 0.5)
                    ))
                    t += line_dur
                    j += WORDS_PER_LINE
        elif script:
            # Karakter sayisina gore proporsiyonel zamanlama tahmini
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', script.strip()) if s.strip()]
            total_chars = max(sum(len(s) for s in sentences), 1)
            current_t = 0.8
            for sentence in sentences:
                frac = len(sentence) / total_chars
                seg_dur = max(frac * (duration - 1.0), 1.0)
                seg_dur = min(seg_dur, 8.0)
                if current_t >= duration - 0.5:
                    break
                words = sentence.split()
                j = 0
                while j < len(words) and current_t < duration - 0.5:
                    chunk_words = words[j:j + WORDS_PER_LINE]
                    chunk_text = " ".join(chunk_words)
                    chunk_dur = seg_dur * len(chunk_words) / max(len(words), 1)
                    chunk_dur = max(chunk_dur, 0.8)
                    subtitle_clips.extend(self._make_subtitle_overlay(chunk_text, current_t, chunk_dur))
                    current_t += chunk_dur
                    j += WORDS_PER_LINE

        return subtitle_clips

    def _make_subtitle_overlay(self, text: str, start: float, dur: float) -> list:
        """Tek bir altyazi satirinin arka plan + yazi cliplerini olustur."""
        from moviepy import ColorClip
        # Siyah yari saydam bar (ColorClip + opacity)
        bar_h = 65
        bar_clip = (
            ColorClip(size=(self.width, bar_h), color=(0, 0, 0))
            .with_start(start)
            .with_duration(dur)
            .with_opacity(0.78)
            .with_position((0, self.height - bar_h - 5))
        )
        # Metin
        try:
            txt_clip = (
                TextClip(
                    text=text,
                    font_size=40,
                    color="white",
                    font="Arial",
                    text_align="center",
                    stroke_color="black",
                    stroke_width=2,
                )
                .with_start(start)
                .with_duration(dur)
                .with_position(("center", self.height - bar_h + 2))
            )
            return [bar_clip, txt_clip]
        except Exception as e:
            logger.warning(f"Altyazi klibi olusturulamadi: {e}")
            return [bar_clip]

    def _create_text_popup_clips(self, key_points: list, duration: float) -> list:
        """Onemli bilgileri gosteren popup kutulari (solid arka plan)."""
        if not key_points:
            return []
        clips = []
        n = len(key_points)
        for i, point in enumerate(key_points):
            show_at = duration * (i + 1) / (n + 1)
            if show_at < 4 or show_at > duration - 6:
                continue
            popup_dur = 4.5
            text = point if len(point) <= 80 else point[:77] + "..."
            wrapped_lines = textwrap.wrap(text, width=42)[:2]
            display_text = "\n".join(wrapped_lines)
            # Solid colored popup kutusu (PIL RGB - no RGBA)
            line_h = 52
            box_w = 840
            box_h = len(wrapped_lines) * line_h + 28
            box_img = Image.new("RGB", (box_w, box_h), (20, 20, 20))
            draw = ImageDraw.Draw(box_img)
            r, g, b = self.color_primary
            # Sol kenar vurgu
            draw.rectangle([0, 0, 7, box_h], fill=(r, g, b))
            # Ust border
            draw.rectangle([0, 0, box_w, 3], fill=(r, g, b))
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
            except OSError:
                font = ImageFont.load_default()
            draw.text((22, 12), display_text, font=font, fill=(255, 255, 255))
            x_pos = (self.width - box_w) // 2
            y_pos = int(self.height * 0.12)
            popup_clip = (
                ImageClip(np.array(box_img))
                .with_start(show_at)
                .with_duration(popup_dur)
                .with_position((x_pos, y_pos))
            )
            clips.append(popup_clip)
        return clips

    def create_thumbnail(self, title, image_path=None, output_path=None):
        if not output_path:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"{config.videos_dir}/{ts}_thumbnail.jpg"

        W, H = 1280, 720

        # Arka plan
        if image_path and Path(image_path).exists():
            try:
                ext = Path(image_path).suffix.lower()
                if ext == ".mp4":
                    # Video'dan ilk kareyi al
                    vc = VideoFileClip(image_path)
                    frame = vc.get_frame(min(1.0, vc.duration / 2))
                    vc.close()
                    base = Image.fromarray(frame).resize((W, H))
                else:
                    base = Image.fromarray(np.array(self._fit_image(image_path))).resize((W, H))
            except Exception:
                base = self._make_gradient_bg(W, H)
        else:
            base = self._make_gradient_bg(W, H)

        # Koyu overlay - metin okunurlugu
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 150))
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

        # Alt kirmizi banner
        band = Image.new("RGB", (W, 110), (200, 30, 30))
        base.paste(band, (0, H - 110))

        draw = ImageDraw.Draw(base)
        try:
            font_big = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 68)
            font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        except OSError:
            font_big = ImageFont.load_default()
            font_small = font_big

        # Baslik
        lines = textwrap.wrap(title, width=30)[:2]
        y = 90
        for line in lines:
            bb = draw.textbbox((0, 0), line, font=font_big)
            x = (W - (bb[2] - bb[0])) // 2
            draw.text((x + 3, y + 3), line, font=font_big, fill=(0, 0, 0))
            draw.text((x, y), line, font=font_big, fill="white")
            y += 80

        # Banner alt yazi
        banner_text = "Para Pusulasi | 2026"
        bb2 = draw.textbbox((0, 0), banner_text, font=font_small)
        bx = (W - (bb2[2] - bb2[0])) // 2
        draw.text((bx, H - 82), banner_text, font=font_small, fill="white")

        # Sari rozet
        draw.ellipse([(W - 125, 18), (W - 18, 108)], fill=(255, 200, 0))
        year_bb = draw.textbbox((0, 0), "2026", font=font_small)
        rx = W - 125 + (107 - (year_bb[2] - year_bb[0])) // 2
        draw.text((rx, 50), "2026", font=font_small, fill=(0, 0, 0))

        base.save(output_path, "JPEG", quality=97)
        logger.info("Thumbnail olusturuldu: " + output_path)
        return output_path

    def _make_gradient_bg(self, w, h):
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        for y in range(h):
            arr[y, :] = [int(10 + (y/h)*30), int(10 + (y/h)*20), int(60 + (y/h)*60)]
        return Image.fromarray(arr)

