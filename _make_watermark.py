from PIL import Image, ImageDraw, ImageFont
import os

W, H = 150, 150
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

draw.ellipse([(5, 5), (145, 145)], fill=(15, 25, 60, 200))
draw.ellipse([(5, 5), (145, 145)], outline=(212, 175, 55, 255), width=3)

cx, cy, r = 75, 55, 28
draw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], outline=(212, 175, 55, 220), width=2)
ri = r // 3
draw.ellipse([(cx-ri, cy-ri), (cx+ri, cy+ri)], fill=(212, 175, 55, 255))
draw.polygon([(cx, cy-r+4), (cx-7, cy), (cx+7, cy)], fill=(255, 255, 255, 255))
draw.polygon([(cx, cy+r-4), (cx-7, cy), (cx+7, cy)], fill=(212, 175, 55, 255))

try:
    font_big = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
except Exception:
    font_big = ImageFont.load_default()
    font_sm = font_big

items = [
    ("Para", 90, (212, 175, 55, 255), font_big),
    ("Pusulasi", 108, (255, 255, 255, 220), font_big),
    ("@ParaPusulasi", 128, (180, 180, 180, 180), font_sm),
]
for text, y, color, f in items:
    bb = draw.textbbox((0, 0), text, font=f)
    x = (W - (bb[2] - bb[0])) // 2
    draw.text((x, y), text, font=f, fill=color)

os.makedirs("assets/branding", exist_ok=True)
img.save("assets/branding/watermark_150x150.png", "PNG")
print("OK: assets/branding/watermark_150x150.png")
