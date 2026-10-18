#!/usr/bin/env python3
"""Gemini TTS のナレーションと図解アニメ・テロップを合成して縦型解説動画（mp4）を作る。

使い方:
  python3 make_video.py                # GEMINI_API_KEY で音声を作って本番生成
  python3 make_video.py --voice Puck   # 声を変える（Kore, Puck, Charon, Aoede など）
  python3 make_video.py --preview      # キーなし・無音で映像だけ確認
"""
import argparse
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS, SS = 1080, 1920, 30, 2  # SS: 2倍で描いて縮小し、輪郭をなめらかにする
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
API = "https://generativelanguage.googleapis.com/v1beta"
STYLE = "明るく親しみやすい声で、釣り番組のナレーターのようにテンポよく読んでください："

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]
FONT = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)

NAVY = (8, 28, 58)
DEEP = (4, 52, 96)
SEA = (22, 104, 168)
SEA_LIGHT = (60, 150, 210)
WHITE = (255, 255, 255)
YELLOW = (255, 210, 63)
ORANGE = (255, 140, 40)
RED = (226, 54, 64)
SILVER = (200, 214, 226)
INK = (16, 30, 50)


# ---------- 補助 ----------

def clamp(t):
    return max(0.0, min(1.0, t))


def ease(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def back(t):
    t = clamp(t)
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def lerp(a, b, t):
    return a + (b - a) * t


@lru_cache(maxsize=None)
def font(size):
    return ImageFont.truetype(FONT, int(size * SS))


class Canvas:
    """1080x1920 の座標で描くと、内部では SS 倍の画像に描く。"""

    def __init__(self, img):
        self.img = img
        self.d = ImageDraw.Draw(img)

    @staticmethod
    def _p(pts):
        return [(x * SS, y * SS) for x, y in pts]

    def poly(self, pts, fill=None, outline=None, width=0):
        self.d.polygon(self._p(pts), fill=fill, outline=outline, width=int(width * SS))

    def line(self, pts, fill, width, joint="curve"):
        self.d.line(self._p(pts), fill=fill, width=int(width * SS), joint=joint)

    def circle(self, cx, cy, r, fill=None, outline=None, width=0, ry=None):
        ry = r if ry is None else ry
        self.d.ellipse([(cx - r) * SS, (cy - ry) * SS, (cx + r) * SS, (cy + ry) * SS],
                       fill=fill, outline=outline, width=int(width * SS))

    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=0):
        self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=r * SS,
                                 fill=fill, outline=outline, width=int(width * SS))

    def text(self, x, y, s, size, fill=WHITE, anchor="mm", stroke=0, stroke_fill=None, bold=True):
        sw = int(stroke * SS) if stroke else (max(1, int(size * SS * 0.03)) if bold else 0)
        self.d.multiline_text((x * SS, y * SS), s, font=font(size), fill=fill, anchor=anchor,
                              align="center", spacing=int(size * SS * 0.25),
                              stroke_width=sw, stroke_fill=stroke_fill or fill)

    def pop_text(self, x, y, s, size, scale, fill=WHITE, stroke=0, stroke_fill=None):
        """拡大縮小しながら出るテキスト。"""
        if scale <= 0.01:
            return
        im = _text_image(s, size, fill, stroke, stroke_fill)
        w, h = max(1, int(im.width * scale)), max(1, int(im.height * scale))
        im = im.resize((w, h), Image.BILINEAR)
        self.img.paste(im, (int(x * SS - w / 2), int(y * SS - h / 2)), im)


@lru_cache(maxsize=None)
def _text_image(s, size, fill, stroke, stroke_fill):
    f = font(size)
    sw = int(stroke * SS) if stroke else max(1, int(size * SS * 0.03))
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = tmp.multiline_textbbox((0, 0), s, font=f, stroke_width=sw, align="center")
    im = Image.new("RGBA", (box[2] - box[0] + 8, box[3] - box[1] + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).multiline_text((4 - box[0], 4 - box[1]), s, font=f, fill=fill, align="center",
                                      stroke_width=sw, stroke_fill=stroke_fill or fill)
    return im


def fish(c, cx, cy, L, body=(40, 90, 160), stripe=YELLOW, belly=(226, 236, 242), flip=False, tail_wag=0.0):
    """右向きの魚。flip=True で左向き。"""
    sx = -1 if flip else 1
    top, bot, mid = [], [], []
    n = 26
    for i in range(n + 1):
        u = i / n
        x = 0.5 * L - u * 0.82 * L
        hh = 0.18 * L * math.sin(math.pi * (u * 0.92)) ** 0.75
        top.append((cx + sx * x, cy - hh))
        bot.append((cx + sx * x, cy + hh * 0.9))
        mid.append((cx + sx * x, cy + hh * 0.15))
    wag = tail_wag * 0.06 * L
    tail = [(-0.30 * L, 0), (-0.53 * L, -0.18 * L + wag), (-0.45 * L, wag * 0.5), (-0.53 * L, 0.18 * L + wag)]
    c.poly([(cx + sx * x, cy + y) for x, y in tail], fill=body)
    c.poly(top + bot[::-1], fill=body)
    c.poly(mid + bot[::-1], fill=belly)
    if stripe:
        sp = [(cx + sx * (0.5 * L - u * 0.82 * L), cy - 0.02 * L) for u in (0.18, 0.5, 0.95)]
        c.line(sp, fill=stripe, width=max(2, 0.028 * L))
    fin = [(0.05 * L, -0.15 * L), (-0.12 * L, -0.26 * L), (-0.16 * L, -0.12 * L)]
    c.poly([(cx + sx * x, cy + y) for x, y in fin], fill=body)
    c.circle(cx + sx * 0.36 * L, cy - 0.045 * L, 0.04 * L, fill=WHITE)
    c.circle(cx + sx * 0.37 * L, cy - 0.045 * L, 0.022 * L, fill=INK)


def waves(c, y, t, color, amp=14, length=260, speed=80, bottom=1360):
    pts = [(x, y + amp * math.sin((x + t * speed) / length * 2 * math.pi)) for x in range(-20, W + 40, 20)]
    c.poly(pts + [(W + 40, bottom), (-20, bottom)], fill=color)


def jig(c, x, y, angle=0.0, size=1.0):
    pts = [(-34, 0), (-10, -11), (30, -7), (38, 0), (30, 7), (-10, 11)]
    ca, sa = math.cos(angle), math.sin(angle)
    rot = [(x + size * (px * ca - py * sa), y + size * (px * sa + py * ca)) for px, py in pts]
    c.poly(rot, fill=SILVER, outline=(120, 140, 160), width=2)


def check(c, x, y, s, t, color=YELLOW):
    pts = [(x - s * 0.5, y), (x - s * 0.15, y + s * 0.35), (x + s * 0.55, y - s * 0.4)]
    t = clamp(t)
    if t <= 0:
        return
    if t < 0.4:
        k = t / 0.4
        c.line([pts[0], (lerp(pts[0][0], pts[1][0], k), lerp(pts[0][1], pts[1][1], k))], color, s * 0.16)
    else:
        k = (t - 0.4) / 0.6
        c.line([pts[0], pts[1], (lerp(pts[1][0], pts[2][0], k), lerp(pts[1][1], pts[2][1], k))], color, s * 0.16)


def label(c, x, y, s, size=46, fg=INK, bg=YELLOW, anchor_x="c"):
    w = font(size).getlength(s) / SS + size * 0.9
    h = size * 1.5
    x0 = x - w / 2 if anchor_x == "c" else x
    c.rrect(x0, y - h / 2, x0 + w, y + h / 2, h / 2, fill=bg)
    c.text(x0 + w / 2, y, s, size, fill=fg)


# ---------- 各シーンの図解 ----------

def scene_title(c, t, dur):
    waves(c, 560, t, SEA, amp=10, bottom=1380)
    waves(c, 600, t * 1.3, DEEP, amp=8, bottom=1380)
    for i in range(9):
        bx = 120 + (i * 137) % 860
        by = 1340 - ((t * 120 + i * 97) % 700)
        c.circle(bx, by, 6 + (i % 3) * 4, outline=(170, 220, 250), width=3)
    k = ease(t / 1.6)
    x = lerp(-320, 540, k)
    fish(c, x, 960 + 14 * math.sin(t * 3), 560, tail_wag=math.sin(t * 9))
    c.pop_text(540, 1250, "BURI", 70, back((t - 1.2) / 0.6), fill=YELLOW)


def scene_shusse(c, t, dur):
    xs = [120, 330, 585, 880]
    lens = [140, 190, 250, 320]
    kanto = ["ワカシ", "イナダ", "ワラサ", "ブリ"]
    kansai = ["ツバス", "ハマチ", "メジロ", "ブリ"]
    label(c, 110, 660, "関東", 40, anchor_x="l", bg=SEA_LIGHT, fg=WHITE)
    label(c, 110, 1200, "関西", 40, anchor_x="l", bg=ORANGE, fg=WHITE)
    for i in range(4):
        start = dur * (0.06 + i * 0.17)
        k = back((t - start) / 0.5)
        if k <= 0:
            continue
        fish(c, xs[i], 930, lens[i] * k, tail_wag=math.sin(t * 8 + i))
        c.pop_text(xs[i], 790, kanto[i], 44, k, fill=WHITE)
        c.pop_text(xs[i], 1070, kansai[i], 44, k, fill=YELLOW)
        if i < 3 and t > start + 0.4:
            ax = (xs[i] + lens[i] / 2 + xs[i + 1] - lens[i + 1] / 2) / 2
            c.line([(ax - 10, 912), (ax + 6, 930), (ax - 10, 948)], fill=(150, 190, 220), width=6)


def scene_aomono(c, t, dur):
    rows = [("ブリ", (40, 90, 160), YELLOW, 700),
            ("ヒラマサ", (46, 118, 150), (240, 220, 90), 930),
            ("カンパチ", (150, 108, 70), (110, 70, 40), 1160)]
    for i, (name, body, stripe, y) in enumerate(rows):
        k = ease((t - dur * (0.05 + i * 0.22)) / 0.7)
        if k <= 0:
            continue
        fish(c, lerp(1400, 680, k), y, 400, body=body, stripe=stripe, tail_wag=math.sin(t * 8 + i))
        label(c, lerp(-200, 230, k), y, name, 46)
    if t > dur * 0.8:
        c.pop_text(540, 1330, "背中が青い回遊魚", 48, back((t - dur * 0.8) / 0.5), fill=SEA_LIGHT)


def scene_shore(c, t, dur):
    c.poly([(0, 1000), (270, 1000), (330, 1380), (0, 1380)], fill=(70, 62, 58))
    waves(c, 1050, t, SEA, amp=8, bottom=1380)
    # 釣り人
    c.circle(170, 870, 26, fill=WHITE)
    c.line([(170, 896), (170, 950)], WHITE, 10)
    c.line([(170, 950), (150, 1000)], WHITE, 10)
    c.line([(170, 950), (192, 1000)], WHITE, 10)
    c.line([(170, 915), (205, 930)], WHITE, 9)
    tip = (330, 790)
    c.line([(200, 940), (265, 860), tip], (230, 200, 120), 7)
    land, bottom_y = (880, 1050), 1300
    k1 = clamp((t - dur * 0.1) / (dur * 0.35))
    k2 = clamp((t - dur * 0.48) / (dur * 0.4))

    def arc(u):
        return lerp(tip[0], land[0], u), lerp(tip[1], land[1], u) - 330 * 4 * u * (1 - u)

    if k1 > 0:
        trail = [arc(u * k1 / 30) for u in range(31)]
        for i in range(0, 30, 2):
            c.line([trail[i], trail[i + 1]], (180, 210, 230), 3)
    if 0 < k1 < 1:
        jx, jy = arc(k1)
        jig(c, jx, jy, angle=k1 * 6)
    elif k1 >= 1:
        jy = lerp(land[1], bottom_y, k2)
        jx = land[0] + 26 * math.sin(k2 * 14)
        c.line([tip, (jx, jy)], (180, 210, 230), 2)
        jig(c, jx, jy, angle=math.pi / 2 + 0.4 * math.sin(k2 * 14))
        label(c, land[0] - 10, 960, "メタルジグ", 40)
        if k2 > 0.5:
            for i in range(3):
                fx = lerp(1150, 640, ease((k2 - 0.5) * 2)) + i * 90
                fish(c, fx, 1270 + (i % 2) * 40, 90, flip=True, tail_wag=math.sin(t * 10 + i))


def scene_tackle(c, t, dur):
    items = [("ロッド", "10フィート前後"), ("ライン", "PE 1.5〜2号"), ("ルアー", "メタルジグ 40〜60g")]
    for i, (head, body) in enumerate(items):
        k = ease((t - dur * (0.08 + i * 0.25)) / 0.5)
        if k <= 0:
            continue
        y = 660 + i * 240
        x0 = lerp(-1000, 80, k)
        c.rrect(x0, y - 95, x0 + 920, y + 95, 28, fill=WHITE)
        ix, iy = x0 + 120, y
        c.circle(ix, iy, 70, fill=(226, 238, 248))
        if i == 0:
            c.line([(ix - 50, iy + 45), (ix + 50, iy - 50)], INK, 8)
            c.circle(ix - 18, iy + 22, 16, fill=SEA)
        elif i == 1:
            c.circle(ix, iy, 46, fill=SEA)
            c.circle(ix, iy, 30, outline=WHITE, width=4)
            c.circle(ix, iy, 12, fill=WHITE)
        else:
            jig(c, ix, iy, angle=-0.6, size=1.5)
        c.text(x0 + 230, y - 34, head, 44, fill=SEA, anchor="lm")
        c.text(x0 + 230, y + 30, body, 52, fill=INK, anchor="lm")


def scene_morning(c, t, dur):
    horizon = 1060
    rise = ease(t / (dur * 0.5))
    sun_y = lerp(horizon + 90, horizon - 60, rise)
    for i in range(12):
        a = i / 12 * 2 * math.pi + t * 0.3
        c.line([(250 + 120 * math.cos(a), sun_y + 120 * math.sin(a)),
                (250 + 160 * math.cos(a), sun_y + 160 * math.sin(a))], (255, 190, 90), 6)
    c.circle(250, sun_y, 90, fill=(255, 170, 60))
    waves(c, horizon, t, SEA, amp=6, bottom=1380)
    if t > dur * 0.1:
        label(c, 250, 760, "朝マヅメ", 42, bg=ORANGE, fg=WHITE)
    bird_k = clamp((t - dur * 0.35) / 0.6)
    if bird_k > 0:
        for i in range(7):
            a = t * 1.4 + i * 2 * math.pi / 7
            bx = 760 + 150 * math.cos(a)
            by = 820 + 50 * math.sin(a) - 30 * (i % 2)
            flap = 14 * math.sin(t * 12 + i)
            c.line([(bx - 24, by - flap), (bx, by), (bx + 24, by - flap)], WHITE, 5)
        for i in range(10):
            ph = (t * 1.8 + i * 0.37) % 1
            sx_ = 640 + i * 26
            c.circle(sx_, horizon - 70 * 4 * ph * (1 - ph), 6, fill=WHITE)
    if t > dur * 0.55:
        k = back((t - dur * 0.55) / 0.5)
        c.pop_text(760, 1180, "ナブラ発見！", 52, k, fill=YELLOW)


def scene_care(c, t, dur):
    cards = [(90, "① 血抜き"), (590, "② 潮氷")]
    for i, (x0, head) in enumerate(cards):
        k = back((t - dur * (0.05 + i * 0.4)) / 0.5)
        if k <= 0:
            continue
        cx = x0 + 200
        s = k
        c.rrect(cx - 200 * s, 980 - 300 * s, cx + 200 * s, 980 + 300 * s, 30 * s, fill=WHITE)
        if k < 0.9:
            continue
        if i == 0:
            fish(c, cx, 900, 280, tail_wag=0)
            for j in range(3):
                dy = ((t * 1.5 + j * 0.33) % 1) * 120
                c.circle(cx + 80, 940 + dy, 12, fill=RED)
        else:
            c.rrect(cx - 130, 820, cx + 130, 1010, 18, fill=SEA)
            c.rrect(cx - 110, 850, cx + 110, 990, 10, fill=(150, 210, 240))
            for j, (ox, oy) in enumerate([(-60, 900), (10, 880), (60, 930), (-20, 950)]):
                c.rrect(cx + ox - 22, oy - 22, cx + ox + 22, oy + 22, 6, fill=WHITE, outline=(120, 180, 220), width=3)
        c.text(cx, 1140, head, 48, fill=INK)
        if i == 1:
            c.text(cx, 1210, "海水＋氷", 36, fill=SEA, bold=False)
    if t > dur * 0.4:
        k = ease((t - dur * 0.4) / 0.4)
        c.line([(500, 980), (500 + 80 * k, 980)], YELLOW, 12)
        if k >= 1:
            c.poly([(585, 980), (555, 955), (555, 1005)], fill=YELLOW)


def scene_safety(c, t, dur):
    k = back(t / 0.7)
    cx, cy = 540, 860
    if k > 0:
        s = k
        c.rrect(cx - 150 * s, cy - 210 * s, cx - 80 * s, cy - 120 * s, 16 * s, fill=ORANGE)
        c.rrect(cx + 80 * s, cy - 210 * s, cx + 150 * s, cy - 120 * s, 16 * s, fill=ORANGE)
        c.rrect(cx - 170 * s, cy - 150 * s, cx + 170 * s, cy + 190 * s, 40 * s, fill=ORANGE)
        c.poly([(cx - 70 * s, cy - 152 * s), (cx + 70 * s, cy - 152 * s), (cx, cy - 30 * s)], fill=NAVY)
        for yy in (40, 120):
            c.line([(cx - 170 * s, cy + yy * s), (cx + 170 * s, cy + yy * s)], WHITE, 12 * s)
            c.rrect(cx - 22 * s, cy + (yy - 16) * s, cx + 22 * s, cy + (yy + 16) * s, 5 * s, fill=INK)
    items = ["ライフジャケット", "滑りにくい靴"]
    for i, s_ in enumerate(items):
        st = dur * (0.25 + i * 0.25)
        if t < st:
            continue
        y = 1170 + i * 100
        check(c, 300, y, 60, (t - st) / 0.5)
        c.text(360, y, s_, 52, fill=WHITE, anchor="lm")


SCENES = [
    dict(narration="海釣りの王様、ブリ。岸からでも釣れるって知ってましたか？",
         telop="岸から釣れる！\nブリの釣り方", draw=scene_title),
    dict(narration="ブリは成長すると名前が変わる出世魚。関東ではワカシ、イナダ、ワラサ、そしてブリ。関西ではツバス、ハマチ、メジロ、ブリと呼ばれます。",
         telop="出世魚\n関東と関西で呼び名が違う", draw=scene_shusse),
    dict(narration="ブリ、ヒラマサ、カンパチ。背中の青い回遊魚をまとめて「青物」と呼びます。",
         telop="青物＝\nブリ・ヒラマサ・カンパチ", draw=scene_aomono),
    dict(narration="岸から狙うならショアジギング。金属のルアー「メタルジグ」を遠くへ投げて、群れのいる層を探ります。",
         telop="基本は\nショアジギング", draw=scene_shore),
    dict(narration="道具の目安は、10フィート前後のロッド、PE1.5から2号の糸、40から60グラムのジグ。",
         telop="道具の目安", draw=scene_tackle),
    dict(narration="狙い目は秋の朝マヅメ。鳥が群れて海面がざわつく「ナブラ」を見つけたら大チャンスです。",
         telop="秋の朝マヅメ＋ナブラ\n＝チャンス", draw=scene_morning),
    dict(narration="釣れたらすぐに血抜きをして、海水と氷で冷やす。これだけで味が大きく変わります。",
         telop="釣れたら\n血抜き→潮氷", draw=scene_care),
    dict(narration="ライフジャケットと滑りにくい靴は必ず着けて、安全に大物を狙いましょう！",
         telop="安全第一で\n大物を狙おう！", draw=scene_safety),
]


# ---------- テロップ・字幕 ----------

def draw_telop(c, text, t):
    k = ease(t / 0.45)
    size = 64 if max(len(s) for s in text.split("\n")) <= 12 else 54
    lines = text.count("\n") + 1
    h = lines * size * 1.3 + 60
    y0 = lerp(80, 190, k)
    c.rrect(60, y0, W - 60, y0 + h, 36, fill=WHITE)
    c.rrect(60, y0, 76, y0 + h, 8, fill=YELLOW)
    c.text(W / 2, y0 + h / 2, text, size, fill=INK)


def subtitle_chunks(narration, max_len=17):
    parts = re.findall(r"[^、。？！]+[、。？！]?", narration)
    chunks = []
    for p in parts:
        if chunks and len(chunks[-1]) + len(p) <= max_len:
            chunks[-1] += p
        else:
            chunks.append(p)
    return chunks


def draw_subtitle(c, chunks, t, speech):
    total = sum(len(s) for s in chunks)
    acc = 0
    for s in chunks:
        acc += len(s)
        if t <= speech * acc / total or s is chunks[-1]:
            break
    s = s.rstrip("、")
    if len(s) > 17:  # 1行に収まらないときは真ん中で2行に分ける
        mid = (len(s) + 1) // 2
        s = s[:mid] + "\n" + s[mid:]
    c.text(W / 2, 1540, s, 54, fill=WHITE, stroke=6, stroke_fill=INK)


# ---------- Gemini TTS ----------

def api(path, key, body=None):
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def tts_models(key):
    """使える TTS モデルを新しい順に返す（Pro は無料枠外のことが多いので除く）。"""
    names, token = [], ""
    while True:
        res = api(f"models?pageSize=1000{'&pageToken=' + token if token else ''}", key)
        for m in res.get("models", []):
            n = m["name"].split("/")[-1]
            if "tts" in n and "pro" not in n and "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(n)
        token = res.get("nextPageToken")
        if not token:
            break

    def rank(n):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return (float(v.group(1)) if v else 0, "lite" not in n, "preview" not in n)

    return sorted(set(names), key=rank, reverse=True)


def synthesize(key, model, text, voice):
    body = {
        "contents": [{"parts": [{"text": STYLE + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    for attempt in range(6):
        try:
            res = api(f"models/{model}:generateContent", key, body)
            part = next(p["inlineData"] for p in res["candidates"][0]["content"]["parts"] if "inlineData" in p)
            rate = int(re.search(r"rate=(\d+)", part["mimeType"]).group(1)) if "rate=" in part["mimeType"] else 24000
            return base64.b64decode(part["data"]), rate
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")
            if e.code == 429 and "limit: 0" not in msg and attempt < 5:
                wait = re.search(r'"retryDelay":\s*"(\d+)', msg)
                wait = int(wait.group(1)) + 2 if wait else 20 * (attempt + 1)
                print(f"  回数制限にかかったので {wait} 秒待ちます…")
                time.sleep(wait)
                continue
            raise RuntimeError(f"{model}: HTTP {e.code} {msg[:300]}")
    raise RuntimeError(f"{model}: 回数制限が解けませんでした")


def make_narration(key, voice, model_override):
    audio_dir = OUT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    models = [model_override] if model_override else tts_models(key)
    if not models:
        sys.exit("TTS モデルが見つかりませんでした。--model で指定してください。")
    print("TTS モデル候補:", ", ".join(models))
    results = []
    for i, sc in enumerate(SCENES):
        h = hashlib.sha1(f"{voice}|{STYLE}|{sc['narration']}".encode()).hexdigest()[:10]
        pcm_path, meta_path = audio_dir / f"scene{i + 1}_{h}.pcm", audio_dir / f"scene{i + 1}_{h}.json"
        if pcm_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            results.append((pcm_path.read_bytes(), meta["rate"]))
            continue
        while True:
            try:
                print(f"シーン{i + 1}: {models[0]} で音声を作成中…")
                pcm, rate = synthesize(key, models[0], sc["narration"], voice)
                break
            except RuntimeError as err:
                print("  失敗:", err)
                models.pop(0)
                if not models:
                    sys.exit("どの TTS モデルでも音声を作れませんでした。")
        pcm_path.write_bytes(pcm)
        meta_path.write_text(json.dumps({"rate": rate, "model": models[0], "voice": voice}))
        results.append((pcm, rate))
    return results


# ---------- 合成 ----------

LEAD, TAIL = 0.3, 0.6  # 各シーンの話し始め前・話し終わり後の間（秒）


def build(args):
    if FONT is None:
        sys.exit("日本語フォントが見つかりません。")
    OUT.mkdir(exist_ok=True)
    if args.preview:
        speeches = [len(sc["narration"]) / 6.5 for sc in SCENES]
        wav = None
    else:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            sys.exit("GEMINI_API_KEY が設定されていません（--preview なら無音で映像だけ作れます）。")
        audio = make_narration(key, args.voice, args.model)
        rate = audio[0][1]
        speeches = [len(pcm) / 2 / r for pcm, r in audio]
        wav = OUT / "narration.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            for pcm, _ in audio:
                w.writeframes(b"\0\0" * int(LEAD * rate) + pcm + b"\0\0" * int(TAIL * rate))
    durs = [LEAD + s + TAIL for s in speeches]
    out = OUT / (args.out or ("preview.mp4" if args.preview else "buri_short.mp4"))

    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if wav:
        cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-shortest" if wav else "-an", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    bg = Image.new("RGB", (W * SS, H * SS))
    gd = ImageDraw.Draw(bg)
    for y in range(H * SS):
        k = y / (H * SS)
        gd.line([(0, y), (W * SS, y)], fill=tuple(int(lerp(NAVY[i], DEEP[i], k)) for i in range(3)))

    total = sum(durs)
    nframes = int(math.ceil(total * FPS))
    starts = [sum(durs[:i]) for i in range(len(durs))]
    chunks = [subtitle_chunks(sc["narration"]) for sc in SCENES]
    only = args.frame
    for fi in range(nframes):
        T = fi / FPS
        if only is not None and abs(T - only) > 0.5 / FPS:
            continue
        i = max(j for j, s in enumerate(starts) if s <= T)
        t = T - starts[i]
        img = bg.copy()
        c = Canvas(img)
        SCENES[i]["draw"](c, t, durs[i])
        draw_telop(c, SCENES[i]["telop"], t)
        if LEAD <= t <= LEAD + speeches[i] + 0.3:
            draw_subtitle(c, chunks[i], t - LEAD, speeches[i])
        c.rrect(60, 40, 60 + (W - 120) * T / total, 52, 6, fill=YELLOW)
        frame = img.reduce(SS)
        if only is not None:
            frame.save(OUT / f"frame_{only:.1f}.png")
            proc.stdin.close()
            proc.kill()
            return
        proc.stdin.write(frame.tobytes())
        if fi % (FPS * 5) == 0:
            print(f"  映像 {T:5.1f}/{total:.1f} 秒")
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg でエラーが出ました。")
    print(f"完成: {out}（{total:.1f} 秒）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preview", action="store_true", help="キーなし・無音で映像だけ作る")
    ap.add_argument("--voice", default="Kore", help="Gemini TTS の声の名前（既定: Kore）")
    ap.add_argument("--model", help="TTS モデルを固定する（既定: 一覧から最新を自動選択）")
    ap.add_argument("--out", help="出力ファイル名")
    ap.add_argument("--frame", type=float, help="指定秒の1コマだけ PNG で書き出す（確認用）")
    build(ap.parse_args())
