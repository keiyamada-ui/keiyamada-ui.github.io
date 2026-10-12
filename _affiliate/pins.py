"""Pinterest のピン（縦長の画像＋タイトル＋説明＋楽天のリンク）を作る。

画像は商品写真を使わず、ことりのアイコンと文字で作る（権利の心配がないように）。
作った画像は kotori/pins/ に置くと GitHub Pages で公開され、
管理画面の「📌 Pinterest で作成」から、その画像とリンクが入った状態でピンの作成画面を開ける。
"""

import datetime
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import checks
import prompts

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PIN_DIR = ROOT / "kotori" / "pins"
AVATAR = ROOT / "kotori" / "avatar.png"
ILLUST = ROOT / "kotori" / "header.jpg"
SITE = "https://keiyamada-ui.github.io/kotori/pins/"
KEEP = 90
W, H = 1000, 1500
COLORS = {"bg": (255, 248, 230), "card": (255, 255, 255), "text": (58, 46, 31), "sub": (122, 106, 85),
          "accent": (245, 166, 35), "line": (240, 226, 192)}
# 丸みのある日本語フォント（ワークフローで用意する）→ なければ入っている日本語フォント
FONT_CANDIDATES = [
    os.environ.get("KOTORI_FONT", ""),
    str(HERE / "fonts" / "ZenMaruGothic-Bold.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
DEFAULT_BOARDS = ["小学生の習い事・知育", "子どもの本・図鑑", "子連れ旅行・おでかけ", "季節の準備・暮らし"]


def _font_path():
    return next((p for p in FONT_CANDIDATES if p and Path(p).exists()), None)


def _font(size):
    path = _font_path()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _wrap(draw, text, font, width):
    """日本語は単語の区切りがないので、1文字ずつ足して幅で折り返す。「/」は強制改行。"""
    lines = []
    for part in text.replace("／", "/").split("/"):
        line = ""
        for ch in part.strip():
            if draw.textlength(line + ch, font=font) > width and line:
                lines.append(line)
                line = ch
            else:
                line += ch
        if line:
            lines.append(line)
    return lines


def render(spec, out_path):
    """縦長（2:3）のピン画像を作る。"""
    img = Image.new("RGB", (W, H), COLORS["bg"])
    d = ImageDraw.Draw(img)
    pad = 80
    d.text((pad, 80), "子育て家族の“買ってよかった”", font=_font(40), fill=COLORS["sub"])
    d.rounded_rectangle((pad, 140, pad + 140, 150), radius=5, fill=COLORS["accent"])

    # 大きな見出し
    big = _font(92)
    y = 200
    for line in _wrap(d, spec["headline"], big, W - pad * 2)[:4]:
        d.text((pad, y), line, font=big, fill=COLORS["text"])
        y += 122

    # 特徴（白いカード）
    y += 30
    small = _font(52)
    rows = [(i == 0, line) for p in spec["points"][:3] for i, line in enumerate(_wrap(d, p, small, W - pad * 2 - 120)[:2])]
    card_h = 60 + len(rows) * 78
    d.rounded_rectangle((pad, y, W - pad, y + card_h), radius=36, fill=COLORS["card"], outline=COLORS["line"], width=3)
    ty = y + 34
    for first, line in rows:
        if first:  # 箇条書きの丸
            d.ellipse((pad + 40, ty + 20, pad + 64, ty + 44), fill=COLORS["accent"])
        d.text((pad + 88, ty), line, font=small, fill=COLORS["text"])
        ty += 78
    y += card_h + 36

    # 評価・価格（商品情報から分かる事実だけ）
    if spec.get("facts"):
        d.text((pad, y), spec["facts"], font=_font(42), fill=COLORS["sub"])
        y += 70

    # あいた所に、ことりのイラスト（ヘッダー画像）を入れる
    room = (H - 290) - (y + 20)
    if ILLUST.exists() and room > 160:
        art = Image.open(ILLUST).convert("RGB")
        width = W - pad * 2
        art = art.resize((width, round(width * art.height / art.width)))
        if art.height > room:  # 高さが足りなければ、真ん中のことりを中心に切り取る
            top = (art.height - room) // 2
            art = art.crop((0, top, width, top + room))
        mask = Image.new("L", art.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, art.width - 1, art.height - 1), radius=36, fill=255)
        img.paste(art, (pad, y + 20 + (room - art.height) // 2), mask)

    # 下: ことりのアイコンと名前
    if AVATAR.exists():
        av = Image.open(AVATAR).convert("RGBA").resize((170, 170))
        img.paste(av, (pad, H - 250), av)
    d.text((pad + 200, H - 225), "ことり", font=_font(56), fill=COLORS["text"])
    d.text((pad + 200, H - 152), "@kotori.family", font=_font(38), fill=COLORS["sub"])
    d.text((W - pad - 90, H - 140), "PR", font=_font(44), fill=COLORS["sub"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)
    return out_path


def _facts(item):
    out = []
    if item.get("review_average") and item.get("review_count"):
        out.append(f"★{item['review_average']}（レビュー{item['review_count']:,}件）")
    if item.get("price"):
        out.append(f"{item['price']:,}円〜")
    return "　".join(out)


def check_pin(pin):
    errors = []
    label = f"ピン「{pin.get('title', '')[:15]}」"
    if not (10 <= len(pin["title"]) <= 100):
        errors.append(f"{label}: タイトルの長さ（{len(pin['title'])}文字）")
    if len(pin["description"]) > 500:
        errors.append(f"{label}: 説明が長すぎます")
    if "#PR" not in pin["description"]:
        errors.append(f"{label}: 説明に「#PR」がありません")
    for text in (pin["title"], pin["description"], pin["headline"], *pin["points"]):
        if checks.URL_PATTERN.search(text):
            errors.append(f"{label}: URL は入れないでください")
        errors += [f"{label}: NGワード「{w}」" for w, _ in checks._ng_hits(text)]
        errors += [f"{label}: {e}" for e in checks._ai_smell(text)]
    return errors


def make_pins(config, today, items, generate, pin_dir=PIN_DIR, manual_dir=None):
    """商品ごとにピンを作り、manual/pins.json に追加する。返り値: 作ったピンの一覧。"""
    conf = config.get("pinterest", {})
    if not conf.get("enabled", True) or not items:
        return []
    items = items[: conf.get("per_day", 2)]
    boards = conf.get("boards") or DEFAULT_BOARDS
    system, user = prompts.pin_messages(config["account"], today, items, boards)
    result = {p["id"]: p for p in generate(system, user, prompts.PIN_SCHEMA, tier="standard")["pins"]}
    made = []
    for n, item in enumerate(items, 1):
        pin = result.get(item["id"])
        if not pin:
            continue
        problems = check_pin(pin)
        if problems:
            print("⚠️ ピンを1枚見送りました: " + " / ".join(problems[:3]))
            continue
        name = f"{today.isoformat()}-{n}.png"
        render({"headline": pin["headline"], "points": pin["points"], "facts": _facts(item)}, Path(pin_dir) / name)
        made.append({
            "key": f"{today.isoformat()}:{item['id']}", "date": today.isoformat(),
            "title": pin["title"], "description": pin["description"],
            "board": pin["board"] if pin["board"] in boards else boards[0],
            "link": item["url"], "image": f"kotori/pins/{name}", "image_url": SITE + name,
            "product": item.get("name", ""), "source": item.get("source", ""),
            "keywords": [k.strip() for k in pin.get("keywords", []) if k.strip()][:5],
        })
    if made and manual_dir:
        path = Path(manual_dir) / "pins.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        keys = {m["key"] for m in made}
        keep = made + [p for p in old if p["key"] not in keys]
        for gone in keep[KEEP:]:  # 古いピンの画像は消す
            (ROOT / gone["image"]).unlink(missing_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keep[:KEEP], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"📌 Pinterest のピンを{len(made)}枚作りました")
    return made


if __name__ == "__main__":  # 見た目の確認用
    render({"headline": "なわとびが続かない子に/軽いビーズロープ", "points": ["軽くて回しやすい", "長さを調整できる", "練習が楽しくなる"],
            "facts": "★4.6（レビュー250件）　1,280円〜"}, Path("/tmp/pin-sample.png"))
    print(_font_path(), datetime.date.today())
