#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 og:image 社交分享卡（1200×630 PNG）→ assets/og.png。
依赖 Pillow，单独运行（不进 build.py，保持构建零依赖）。品牌绿底 + 白十字 + 站名 + 标语。
用法：python3 make_og.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "assets", "og.png")
W, H = 1200, 630
BG = (12, 117, 96)        # --accent #0c7560
BG2 = (10, 93, 77)        # --accent-ink，做竖向渐变
WHITE = (255, 255, 255)
SOFT = (210, 235, 228)

FONTS = ["/System/Library/Fonts/Hiragino Sans GB.ttc",
         "/System/Library/Fonts/STHeiti Medium.ttc",
         "/Library/Fonts/Arial Unicode.ttf"]


def font(size):
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def center(draw, text, fnt, y, fill, cx=W // 2):
    l, t, r, b = draw.textbbox((0, 0), text, font=fnt)
    draw.text((cx - (r - l) / 2, y), text, font=fnt, fill=fill)
    return b - t


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # 竖向渐变背景
    for y in range(H):
        f = y / H
        d.line([(0, y), (W, y)], fill=(int(BG[0] + (BG2[0] - BG[0]) * f),
                                       int(BG[1] + (BG2[1] - BG[1]) * f),
                                       int(BG[2] + (BG2[2] - BG[2]) * f)))
    # 圆角白十字 logo（居中偏上）
    cx, cy, arm, th = W // 2, 165, 52, 17
    d.rounded_rectangle([cx - th, cy - arm, cx + th, cy + arm], radius=9, fill=WHITE)
    d.rounded_rectangle([cx - arm, cy - th, cx + arm, cy + th], radius=9, fill=WHITE)
    # 站名 + 标语
    center(d, "查过再信", font(104), 250, WHITE)
    center(d, "健康说法核验库", font(40), 380, SOFT)
    center(d, "每条结论都标注证据强度、适用人群和原始出处", font(30), 460, SOFT)
    center(d, "把「听来的」和「有据的」分开", font(30), 508, SOFT)
    img.save(OUT, "PNG", optimize=True)
    print(f"✓ og:image → {OUT}  ({os.path.getsize(OUT)} 字节, {W}×{H})")


if __name__ == "__main__":
    main()
