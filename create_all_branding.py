"""
Kanal Marka Sablonu Sistemi - v2.0
Tum kanallar icin profesyonel logo, watermark ve banner uretir.
Kullanim:
  python create_all_branding.py              # Tum kanallar
  python create_all_branding.py borsa_akademi  # Tek kanal
"""
import os, sys, math
sys.path.insert(0, ".")
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ─── Ikonlar (kanal nisine gore) ────────────────────────────────────────────
CHANNEL_ICONS = {
    "kisisel_finans": "compass",    # Pusula
    "borsa":          "chart",      # Grafik
    "kripto":         "bitcoin",    # Bitcoin
    "kariyer":        "compass",    # Pusula
    "girisimcilik":   "rocket",     # Roket
    "saglik":         "heart",      # Kalp
    "teknoloji":      "circuit",    # Devre
    "egitim":         "book",       # Kitap
    "gayrimenkul":    "house",      # Ev
    "psikoloji":      "brain",      # Beyin (spiral)
}


def get_font(size):
    for f in ["/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Arial.ttf",
              "/Library/Fonts/Arial.ttf"]:
        if os.path.exists(f):
            try: return ImageFont.truetype(f, size)
            except: pass
    return ImageFont.load_default()


def gradient_img(w, h, top, bot):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / h
        arr[y, :] = [int(top[i] + (bot[i] - top[i]) * t) for i in range(3)]
    return Image.fromarray(arr)


def draw_icon(draw, cx, cy, r, color, icon_type):
    """Kanal nisine gore simge ciz."""
    w = (255, 255, 255)

    if icon_type == "compass":
        draw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=color, width=max(3, r//18))
        ri = r // 3
        draw.ellipse([(cx-ri, cy-ri), (cx+ri, cy+ri)], fill=color)
        draw.polygon([(cx, cy-r+8), (cx-r//6, cy), (cx+r//6, cy)], fill=w)
        draw.polygon([(cx, cy+r-8), (cx-r//6, cy), (cx+r//6, cy)], fill=color)
        for ang, lbl in [(0,"K"), (90,"D"), (180,"G"), (270,"B")]:
            rad = math.radians(ang - 90)
            tx = int(cx + (r+18) * math.cos(rad))
            ty = int(cy + (r+18) * math.sin(rad))
            f = get_font(18)
            bb = draw.textbbox((0,0), lbl, font=f)
            draw.text((tx-(bb[2]-bb[0])//2, ty-(bb[3]-bb[1])//2), lbl, font=f, fill=color)

    elif icon_type == "chart":
        bars = [0.6, 0.35, 0.75, 0.25, 0.55, 0.8, 0.45]
        bar_w = r * 2 // (len(bars) + 1)
        for i, h_ratio in enumerate(bars):
            bx = cx - r + i * (bar_w + 4) + 4
            bh = int(r * 1.2 * h_ratio)
            draw.rectangle([(bx, cy+r//3-bh), (bx+bar_w, cy+r//3)], fill=color)
        pts = [(cx-r + i*(bar_w+4)+4+bar_w//2, cy+r//3-int(r*1.2*h)-2) for i,h in enumerate(bars)]
        for i in range(len(pts)-1):
            draw.line([pts[i], pts[i+1]], fill=w, width=3)

    elif icon_type == "bitcoin":
        draw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=color, width=max(4, r//20))
        draw.ellipse([(cx-r+20, cy-r+20), (cx+r-20, cy+r-20)], outline=color, width=3)
        f = get_font(int(r * 1.1))
        bb = draw.textbbox((0,0), "B", font=f)
        draw.text((cx-(bb[2]-bb[0])//2+2, cy-(bb[3]-bb[1])//2-5), "B", font=f, fill=color)

    elif icon_type == "rocket":
        draw.polygon([(cx, cy-r), (cx-r//3, cy+r//2), (cx-r//6, cy+r//3), (cx-r//6, cy+r),
                     (cx+r//6, cy+r), (cx+r//6, cy+r//3), (cx+r//3, cy+r//2)], fill=color)
        draw.polygon([(cx-r//6, cy+r), (cx, cy+r+r//3), (cx+r//6, cy+r)], fill=(255,150,0))
        draw.ellipse([(cx-r//5, cy-r//5+5), (cx+r//5, cy+r//5+5)], fill=w)

    elif icon_type == "heart":
        # Kalp sekli
        for i in range(-r, r+1):
            for j in range(-r, r+1):
                if (i*i + (j - abs(i)*0.7)**2) < (r*0.85)**2:
                    draw.point((cx+i, cy+j+r//6), fill=color)

    elif icon_type == "circuit":
        # Devre tahtasi deseni
        draw.ellipse([(cx-r//4, cy-r//4), (cx+r//4, cy+r//4)], fill=color)
        for ang in [0, 60, 120, 180, 240, 300]:
            rad = math.radians(ang)
            ex = int(cx + r * math.cos(rad))
            ey = int(cy + r * math.sin(rad))
            mx = int(cx + r//2 * math.cos(rad))
            my = int(cy + r//2 * math.sin(rad))
            draw.line([(cx, cy), (ex, ey)], fill=color, width=3)
            draw.ellipse([(ex-8, ey-8), (ex+8, ey+8)], fill=color)

    elif icon_type == "book":
        bw = int(r * 1.4)
        bh = int(r * 1.6)
        draw.rectangle([(cx-bw//2, cy-bh//2), (cx+bw//2, cy+bh//2)], outline=color, width=4)
        draw.line([(cx, cy-bh//2), (cx, cy+bh//2)], fill=color, width=3)
        for y_off in [-bh//4, 0, bh//4]:
            draw.line([(cx+8, cy+y_off), (cx+bw//2-8, cy+y_off)], fill=color, width=2)

    elif icon_type == "house":
        hw = int(r * 1.4)
        draw.polygon([(cx, cy-r), (cx-hw//2, cy), (cx+hw//2, cy)], fill=color)
        draw.rectangle([(cx-hw//3, cy), (cx+hw//3, cy+r*2//3)], fill=color)
        draw.rectangle([(cx-hw//8, cy+r//4), (cx+hw//8, cy+r*2//3)], fill=(255,255,255))

    elif icon_type == "brain":
        for i in range(8):
            ang = math.radians(i * 45)
            px = int(cx + r * 0.7 * math.cos(ang))
            py = int(cy + r * 0.7 * math.sin(ang))
            draw.line([(cx, cy), (px, py)], fill=color, width=3)
            draw.ellipse([(px-r//5, py-r//5), (px+r//5, py+r//5)], fill=color)
        draw.ellipse([(cx-r//3, cy-r//3), (cx+r//3, cy+r//3)], fill=color)


def create_logo(cfg, out_path):
    W, H = 800, 800
    bg = tuple(cfg.color_bg)
    primary = tuple(cfg.color_primary)
    dark_bg = tuple(max(0, c-30) for c in bg)

    img = gradient_img(W, H, bg, dark_bg)
    draw = ImageDraw.Draw(img)

    # Dis cerceve - rounded
    draw.rounded_rectangle([(20,20),(780,780)], radius=80, outline=primary, width=6)
    # Ic cerceve ince
    draw.rounded_rectangle([(35,35),(765,765)], radius=70, outline=primary+(80,) if False else (*primary[:3],), width=1)

    # Simge
    icon = CHANNEL_ICONS.get(cfg.niche, "compass")
    draw_icon(draw, 400, 295, 145, primary, icon)

    # Kanal adi - iki satirda
    parts = cfg.name.split()
    y = 475
    for part in parts[:2]:
        size = 68 if len(part) <= 8 else 56
        f = get_font(size)
        bb = draw.textbbox((0,0), part, font=f)
        x = (W-(bb[2]-bb[0]))//2
        # Golgeli
        draw.text((x+3, y+3), part, font=f, fill=(0,0,0))
        # Renk
        color = primary if parts.index(part) == 0 else (255,255,255)
        draw.text((x, y), part, font=f, fill=color)
        y += size + 12

    # Slogan
    slogan = cfg.slogan[:35]
    f_s = get_font(30)
    bb = draw.textbbox((0,0), slogan, font=f_s)
    sx = (W-(bb[2]-bb[0]))//2
    draw.text((sx, y+8), slogan, font=f_s, fill=(*primary[:3],) if False else tuple(min(255, c+80) for c in bg[:3]) + (255,))
    # Beyaz'a yakın renk
    draw.text((sx, y+8), slogan, font=f_s, fill=(200,200,220))

    # Alt cizgi
    draw.line([(120, 720), (W-120, 720)], fill=primary, width=2)

    img.save(out_path, "PNG")


def create_watermark(cfg, out_path):
    W, H = 150, 150
    bg = tuple(cfg.color_bg)
    primary = tuple(cfg.color_primary)

    wm = Image.new("RGBA", (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(wm)
    draw.ellipse([(5,5),(145,145)], fill=(*bg[:3], 200))
    draw.ellipse([(5,5),(145,145)], outline=(*primary[:3], 255), width=3)

    icon = CHANNEL_ICONS.get(cfg.niche, "compass")
    draw_icon(draw, 75, 52, 28, (*primary[:3], 255), icon)

    f = get_font(13)
    parts = cfg.name.split()
    for part, y in zip(parts[:2], [88, 106]):
        bb = draw.textbbox((0,0), part, font=f)
        x = (W-(bb[2]-bb[0]))//2
        draw.text((x, y), part, font=f, fill=(*primary[:3], 255))

    wm.save(out_path, "PNG")


def create_banner(cfg, out_path):
    BW, BH = 2560, 1440
    bg = tuple(cfg.color_bg)
    primary = tuple(cfg.color_primary)
    dark_bg = tuple(max(0, c-25) for c in bg)

    banner = gradient_img(BW, BH, bg, dark_bg)
    draw = ImageDraw.Draw(banner)

    # Sol simge (buyuk, saydam)
    icon = CHANNEL_ICONS.get(cfg.niche, "compass")
    draw_icon(draw, 380, BH//2, 260, (*primary[:3],), icon)

    # Kanal adi
    name = cfg.name
    f_big = get_font(165)
    bb = draw.textbbox((0,0), name, font=f_big)
    x = (BW-(bb[2]-bb[0]))//2
    draw.text((x+4, BH//2-145+4), name, font=f_big, fill=(0,0,0))
    draw.text((x, BH//2-145), name, font=f_big, fill=primary)

    # Slogan
    slogan = cfg.slogan
    f_med = get_font(68)
    bb = draw.textbbox((0,0), slogan, font=f_med)
    x = (BW-(bb[2]-bb[0]))//2
    draw.text((x, BH//2+55), slogan, font=f_med, fill=(255,255,255))

    # Upload saatleri
    times_text = f"Her gun {cfg.upload_times[0]} ve {cfg.upload_times[1]}"
    f_sm = get_font(50)
    bb = draw.textbbox((0,0), times_text, font=f_sm)
    x = (BW-(bb[2]-bb[0]))//2
    draw.text((x, BH//2+150), times_text, font=f_sm, fill=(180,180,200))

    # Alt cizgi ve hashtag
    draw.line([(180, BH-130), (BW-180, BH-130)], fill=primary, width=3)
    hashtags = " ".join(f"#{t.replace(' ','')}" for t in cfg.topics[:6])
    f_h = get_font(44)
    bb = draw.textbbox((0,0), hashtags, font=f_h)
    x = (BW-(bb[2]-bb[0]))//2
    draw.text((x, BH-110), hashtags, font=f_h, fill=tuple(min(255,c+60) for c in bg))

    banner.save(out_path, "PNG", optimize=True)


def create_channel_branding(channel_id):
    from src.channel_manager import get_channel
    cfg = get_channel(channel_id)

    branding_dir = f"channels/{channel_id}/branding"
    os.makedirs(branding_dir, exist_ok=True)

    logo_path = f"{branding_dir}/logo_800x800.png"
    wm_path = f"{branding_dir}/watermark_150x150.png"
    banner_path = f"{branding_dir}/youtube_banner_2560x1440.png"

    create_logo(cfg, logo_path)
    create_watermark(cfg, wm_path)
    create_banner(cfg, banner_path)

    print(f"[{cfg.name}] Logo, watermark ve banner olusturuldu")
    return logo_path, wm_path, banner_path


if __name__ == "__main__":
    from src.channel_manager import list_channels

    if len(sys.argv) > 1:
        channels = sys.argv[1:]
    else:
        channels = list_channels()

    print(f"{len(channels)} kanal icin gorseller olusturuluyor...\n")
    for cid in channels:
        try:
            create_channel_branding(cid)
        except Exception as e:
            print(f"[{cid}] HATA: {e}")

    print(f"\nTamamlandi! {len(channels)} kanal gorseli hazir.")
    print("Dosyalar: channels/<kanal>/branding/ klasorlerinde")
