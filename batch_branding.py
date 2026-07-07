"""200 kanal için toplu branding üretimi - logo, watermark, banner."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def load_font(size):
    for p in ["/System/Library/Fonts/Helvetica.ttc", "/Library/Fonts/Arial.ttf"]:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def generate_branding(channel_id: str, cfg: dict):
    base = Path(f"channels/{channel_id}/branding")
    base.mkdir(parents=True, exist_ok=True)

    # Zaten var mı?
    if (base / "logo_800x800.png").exists():
        return False  # Skip

    r, g, b = cfg.get("color_primary", [212, 175, 55])
    br, bg_, bb = cfg.get("color_bg", [10, 18, 40])
    name = cfg.get("name", channel_id)
    tagline = cfg.get("tagline", "YouTube Channel")
    initials = "".join(w[0].upper() for w in name.split()[:2])

    # ── LOGO 800×800 ─────────────────────────────────────────
    img = Image.new("RGB", (800, 800), (br, bg_, bb))
    draw = ImageDraw.Draw(img)
    draw.ellipse([50, 50, 750, 750], fill=(r, g, b))
    draw.ellipse([90, 90, 710, 710], fill=(br, bg_, bb))
    fi = load_font(min(240, max(120, 480 // max(len(initials), 1))))
    bbox = draw.textbbox((0, 0), initials, font=fi)
    x = (800 - (bbox[2] - bbox[0])) // 2
    y = (800 - (bbox[3] - bbox[1])) // 2 - 10
    draw.text((x + 4, y + 4), initials, font=fi, fill=(0, 0, 0))
    draw.text((x, y), initials, font=fi, fill=(r, g, b))
    img.save(str(base / "logo_800x800.png"))

    # ── WATERMARK 150×150 ────────────────────────────────────
    wm = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
    dw = ImageDraw.Draw(wm)
    dw.ellipse([5, 5, 145, 145], fill=(r, g, b, 200))
    fw = load_font(52)
    bbox2 = dw.textbbox((0, 0), initials, font=fw)
    x2 = (150 - (bbox2[2] - bbox2[0])) // 2
    y2 = (150 - (bbox2[3] - bbox2[1])) // 2 - 4
    dw.text((x2, y2), initials, font=fw, fill=(br, bg_, bb))
    wm.save(str(base / "watermark_150x150.png"))

    # ── BANNER 2560×1440 ─────────────────────────────────────
    banner = Image.new("RGB", (2560, 1440))
    db = ImageDraw.Draw(banner)
    for y_b in range(1440):
        blend = y_b / 1440
        db.line([(0, y_b), (2560, y_b)], fill=(
            int(br + blend * 30), int(bg_ + blend * 22), int(bb + blend * 40)
        ))
    db.rectangle([0, 0, 2560, 14], fill=(r, g, b))
    db.rectangle([0, 1426, 2560, 1440], fill=(r, g, b))
    fb = load_font(160)
    fbs = load_font(70)
    bb4 = db.textbbox((0, 0), name, font=fb)
    cx = (2560 - (bb4[2] - bb4[0])) // 2
    db.text((cx + 5, 545 + 5), name, font=fb, fill=(0, 0, 0))
    db.text((cx, 545), name, font=fb, fill=(255, 255, 255))
    bb5 = db.textbbox((0, 0), tagline, font=fbs)
    ct = (2560 - (bb5[2] - bb5[0])) // 2
    db.text((ct, 730), tagline, font=fbs, fill=(r, g, b))
    banner.save(str(base / "banner_2560x1440.png"))
    return True


if __name__ == "__main__":
    data = json.loads(Path("channels/channel_registry.json").read_text())
    channels = data.get("channels", {})
    total = len(channels)
    created = 0
    skipped = 0

    print(f"{total} kanal için branding kontrol ediliyor...")
    for i, (cid, cfg) in enumerate(channels.items(), 1):
        result = generate_branding(cid, cfg)
        if result:
            created += 1
        else:
            skipped += 1
        if i % 25 == 0:
            print(f"  {i}/{total} ({created} yeni, {skipped} zaten var)")

    print(f"\n✅ Tamamlandı: {created} yeni branding, {skipped} zaten vardı")
    print(f"   Dosyalar: channels/<id>/branding/")
