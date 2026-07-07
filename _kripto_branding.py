"""Kripto Rehber - Kanal Gorselleri Uretici"""
import os, sys
sys.path.insert(0, ".")
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.makedirs("channels/kripto_rehber/branding", exist_ok=True)

BG = (20, 15, 40)
PRIMARY = (247, 147, 26)  # Bitcoin oranj
WHITE = (255, 255, 255)

def font(size):
    for f in ["/System/Library/Fonts/Helvetica.ttc"]:
        if os.path.exists(f):
            try: return ImageFont.truetype(f, size)
            except: pass
    return ImageFont.load_default()

def gradient(w, h, top, bot):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        t = y / h
        arr[y, :] = [int(top[i] + (bot[i] - top[i]) * t) for i in range(3)]
    return Image.fromarray(arr)

# ── LOGO 800x800 ──────────────────────────────────────────────
W, H = 800, 800
img = gradient(W, H, BG, (10, 8, 25))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([(25,25),(775,775)], radius=70, outline=PRIMARY, width=7)

# Bitcoin sembolü (₿ benzeri)
cx, cy, r = 400, 290, 120
draw.ellipse([(cx-r,cy-r),(cx+r,cy+r)], outline=PRIMARY, width=8)
draw.ellipse([(cx-r+20,cy-r+20),(cx+r-20,cy+r-20)], outline=PRIMARY, width=4)
# B harfi içine
draw.text((cx-25, cy-40), "₿", font=font(90), fill=PRIMARY, anchor="mm" if False else None)
bb = draw.textbbox((0,0), "₿", font=font(90))
draw.text((cx-(bb[2]-bb[0])//2, cy-50), "₿", font=font(90), fill=PRIMARY)

# Kanal adı
for text, y, size, color in [
    ("Kripto", 450, 72, PRIMARY),
    ("Rehber", 530, 72, WHITE),
    ("Kriptoda Kaybolma!", 615, 32, (200,200,200)),
]:
    f = font(size)
    bb = draw.textbbox((0,0), text, font=f)
    x = (W - (bb[2]-bb[0])) // 2
    draw.text((x+2, y+2), text, font=f, fill=(0,0,0))
    draw.text((x, y), text, font=f, fill=color)

draw.line([(120, 665), (W-120, 665)], fill=PRIMARY, width=2)
img.save("channels/kripto_rehber/branding/logo_800x800.png", "PNG")
print("Logo: channels/kripto_rehber/branding/logo_800x800.png")

# ── WATERMARK 150x150 ──────────────────────────────────────────
wm = Image.new("RGBA", (150,150), (0,0,0,0))
wd = ImageDraw.Draw(wm)
wd.ellipse([(5,5),(145,145)], fill=BG+(200,))
wd.ellipse([(5,5),(145,145)], outline=PRIMARY+(255,), width=3)
bb = wd.textbbox((0,0), "₿", font=font(55))
wd.text(((150-(bb[2]-bb[0]))//2, 18), "₿", font=font(55), fill=PRIMARY+(255,))
for text, y in [("Kripto", 88), ("Rehber", 108)]:
    f = font(14)
    bb = wd.textbbox((0,0), text, font=f)
    wd.text(((150-(bb[2]-bb[0]))//2, y), text, font=f, fill=PRIMARY+(255,))
wm.save("channels/kripto_rehber/branding/watermark_150x150.png", "PNG")
print("Watermark: channels/kripto_rehber/branding/watermark_150x150.png")

# ── YOUTUBE BANNER 2560x1440 ───────────────────────────────────
BW, BH = 2560, 1440
banner = gradient(BW, BH, (10, 8, 30), (5, 4, 15))
bd = ImageDraw.Draw(banner)

# Büyük ₿ simgesi sol tarafta
bd.text((200, BH//2-200), "₿", font=font(500), fill=(247,147,26,30))

# Başlık
for text, y, size, color in [
    ("Kripto Rehber", BH//2-140, 160, PRIMARY),
    ("Kriptoda Kaybolma! | Gunluk Analiz ve Rehber", BH//2+50, 65, WHITE),
    ("Her Gun 11:00 ve 23:00 | Bitcoin • Ethereum • Altcoin", BH//2+140, 50, (180,180,180)),
]:
    f = font(size)
    bb = bd.textbbox((0,0), text, font=f)
    x = (BW-(bb[2]-bb[0]))//2
    bd.text((x+3, y+3), text, font=f, fill=(0,0,0))
    bd.text((x, y), text, font=f, fill=color)

bd.line([(200, BH-120), (BW-200, BH-120)], fill=PRIMARY, width=3)
f_sm = font(45)
footer = "#Kripto #Bitcoin #Ethereum #KriptoRehber #BTC #ETH #Blockchain"
bb = bd.textbbox((0,0), footer, font=f_sm)
bd.text(((BW-(bb[2]-bb[0]))//2, BH-100), footer, font=f_sm, fill=(150,150,150))

banner.save("channels/kripto_rehber/branding/youtube_banner_2560x1440.png", "PNG")
print("Banner: channels/kripto_rehber/branding/youtube_banner_2560x1440.png")
print("TAMAMLANDI")
