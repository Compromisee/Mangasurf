#!/usr/bin/env python3
"""Regenerate the deterministic docs screenshots.

Produces docs/tui-{search,manga,downloads,settings}.png by driving the real
MangasurfTUI app headlessly (offline + deterministic), then composes
docs/hero-bento.png from the new dark logo + the four TUI panels.

GUI screenshots (docs/gui-*.png) are captured from the real PyQt6 desktop app
and are not regenerated here -- they are refreshed separately where the app can
run.

Run:  python tests/_build_screenshots.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")


def build_tui():
    subprocess.run([sys.executable, os.path.join(HERE, "_render_tui.py")],
                   check=True)


def build_hero():
    from PIL import Image, ImageDraw, ImageFont

    W, H = 2560, 1440
    BG, BG2 = (20, 20, 27), (25, 25, 33)
    SURF = (30, 30, 40)
    BORDER = (44, 44, 57)
    CYAN = (107, 215, 232)

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(
            int(BG[i] + (BG2[i] - BG[i]) * max(0, (t - 0.3))) for i in range(3)))
    d.ellipse([-300, -300, 900, 900], fill=(24, 26, 40))
    d.ellipse([1900, 700, 2900, 1700], fill=(22, 24, 38))

    def font(sz, bold=False):
        p = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        return ImageFont.truetype(p, sz) if os.path.exists(p) else ImageFont.load_default()

    logo = Image.open(os.path.join(DOCS, "icon-1024.png")).convert("RGBA")
    logo = logo.resize((200, 200), Image.LANCZOS)
    img.paste(logo, (W // 2 - 100, 44), logo)

    def center_text(y, text, sz, color, bold=True):
        f = font(sz, bold)
        d.text((W // 2 - d.textlength(text, font=f) / 2, y), text, font=f, fill=color)
        return y + sz

    y = 44 + 200 + 14
    y = center_text(y, "MANGASURF", 120, (234, 234, 242))
    y = center_text(y, "v1.7.5", 64, CYAN)
    y = center_text(y, "High-Performance Manga Reader, Omnibar Search & "
                       "Downloader across 32 Sources", 34, (162, 162, 182)) + 12

    pills = ["DARK-GREY TUI", "REAL TERMINAL IMAGES", "PHONE PWA",
             "3D CAROUSEL", "OPDS 1.2", "32 SOURCES"]
    f30 = font(26)
    pl = sum(d.textlength("  " + p + "  ", font=f30) + 32 for p in pills)
    px, py = (W - pl) / 2, y
    for p in pills:
        ptext = "  " + p + "  "
        pw = d.textlength(ptext, font=f30) + 32
        d.rounded_rectangle([px, py, px + pw, py + 52], radius=26, fill=SURF,
                            outline=BORDER, width=2)
        d.text((px + 16, py + 11), ptext, font=f30, fill=(162, 162, 182))
        px += pw + 18

    gy = py + 70
    margin, colgap = 100, 40
    pw = (W - 2 * margin - colgap) // 2
    ph = (H - gy - 40 - colgap) // 2
    x0, x1 = margin, margin + pw + colgap

    def fit(im, tw, th):
        ar = im.width / im.height
        if tw / ar <= th:
            w, h = tw, int(tw / ar)
        else:
            h, w = th, int(th * ar)
        return im.resize((w, h), Image.LANCZOS), w, h

    panels = [("tui-search.png", x0, gy), ("tui-manga.png", x1, gy),
              ("tui-downloads.png", x0, gy + ph + colgap),
              ("tui-settings.png", x1, gy + ph + colgap)]
    for name, x, y in panels:
        im = Image.open(os.path.join(DOCS, name)).convert("RGB")
        im, w, h = fit(im, pw, ph)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=16, fill=255)
        d.rounded_rectangle([x - 14, y - 14, x + w + 14, y + h + 14], radius=20,
                            fill=SURF, outline=BORDER, width=2)
        img.paste(im, (x, y), mask)

    img.save(os.path.join(DOCS, "hero-bento.png"))
    print("wrote docs/hero-bento.png", img.size)


if __name__ == "__main__":
    build_tui()
    build_hero()
