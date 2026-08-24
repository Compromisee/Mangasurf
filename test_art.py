from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def get_font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD_PATH if bold else FONT_PATH, size)

def create_manga_cover(width, height, title, genre, theme_color, sub=""):
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    
    # Background gradient
    c1, c2, c3 = theme_color
    for y in range(height):
        t = y / height
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
        
    # Dramatic anime energy shapes
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    
    # Stylized anime sun / energy orb
    ov_draw.ellipse([width * 0.2, height * 0.1, width * 0.8, height * 0.5], fill=(c3[0], c3[1], c3[2], 120))
    
    # Geometric dynamic manga cuts
    ov_draw.polygon([(0, int(height * 0.6)), (width, int(height * 0.45)), (width, height), (0, height)], fill=(12, 10, 24, 230))
    ov_draw.line([(0, int(height * 0.6)), (width, int(height * 0.45))], fill=(255, 255, 255, 180), width=3)
    
    # Star glints
    cx, cy = int(width * 0.5), int(height * 0.3)
    ov_draw.line([(cx - 20, cy), (cx + 20, cy)], fill=(255, 255, 255, 220), width=2)
    ov_draw.line([(cx, cy - 20), (cx, cy + 20)], fill=(255, 255, 255, 220), width=2)
    
    im = Image.alpha_composite(im, overlay)
    draw = ImageDraw.Draw(im)
    
    # Genre badge
    draw.rounded_rectangle([16, 16, 16 + len(genre) * 9 + 18, 40], radius=6, fill=(0, 0, 0, 180), outline=(c3[0], c3[1], c3[2], 255))
    draw.text((24, 22), genre.upper(), fill=(255, 255, 255), font=get_font(11, bold=True))
    
    # Title
    font_t = get_font(18, bold=True)
    draw.text((16, height - 60), title, fill=(255, 255, 255), font=font_t)
    if sub:
        draw.text((16, height - 32), sub, fill=(200, 196, 230), font=get_font(12))
        
    return im

cover = create_manga_cover(300, 440, "Solo Leveling", "Action", ((15, 23, 42), (59, 130, 246), (56, 189, 248)), "Ch. 1-179 · MangaDex")
cover.save("test_cover.png")
print("Cover created!")
