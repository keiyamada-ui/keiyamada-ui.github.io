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
# ボードごとの色（並んだときに見分けやすく、どれも ことり らしい柔らかい色）
THEMES = {
    "小学生の習い事・知育": {"bg": (232, 244, 236), "accent": (76, 160, 112), "mark": (198, 236, 210)},
    "子どもの本・図鑑": {"bg": (231, 239, 250), "accent": (74, 126, 196), "mark": (200, 220, 248)},
    "子連れ旅行・おでかけ": {"bg": (253, 236, 228), "accent": (226, 112, 84), "mark": (252, 210, 196)},
    "季節の準備・暮らし": {"bg": (255, 245, 222), "accent": (232, 150, 30), "mark": (255, 224, 150)},
}
INK, SUB, WHITE, LINE = (52, 42, 30), (120, 104, 84), (255, 255, 255), (234, 224, 204)
DEFAULT_BOARDS = list(THEMES)
# 丸みのある日本語フォント（ワークフローで用意する）→ なければ入っている日本語フォント
FONT_DIR = HERE / "fonts"
FONT_FALLBACK = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]


def _font_path(weight="Bold"):
    names = [os.environ.get("KOTORI_FONT_DIR", "") and str(Path(os.environ["KOTORI_FONT_DIR"]) / f"ZenMaruGothic-{weight}.ttf"),
             str(FONT_DIR / f"ZenMaruGothic-{weight}.ttf"), str(FONT_DIR / "ZenMaruGothic-Bold.ttf"),
             os.environ.get("KOTORI_FONT", "")] + FONT_FALLBACK
    return next((p for p in names if p and Path(p).exists()), None)


def _font(size, weight="Bold"):
    path = _font_path(weight)
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


NO_LINE_START = "、。，．,.!！?？)）」』】ーっゃゅょぁぃぅぇぉッャュョァィゥェォ〜"


def _fit_headline(draw, text, width, max_lines=3):
    """見出しが3行以内に収まる、いちばん大きい文字の大きさを選ぶ。
    「/」で区切ってあれば、区切りごとに1行で収まる大きさにする（言葉の途中で折り返さない）。"""
    parts = [x.strip() for x in text.replace("／", "/").split("/") if x.strip()]
    for size in (104, 96, 88, 80, 72, 66, 60):
        f = _font(size, "Black")
        if len(parts) > 1:
            if len(parts) <= max_lines and all(draw.textlength(x, font=f) <= width for x in parts):
                return f, size, parts
            continue
        lines = _wrap(draw, text, f, width)
        for i in range(1, len(lines)):  # 行の頭に「、」や小さい「っ」が来ないように
            while lines[i] and lines[i][0] in NO_LINE_START and len(lines[i - 1]) > 1:
                lines[i] = lines[i - 1][-1] + lines[i]
                lines[i - 1] = lines[i - 1][:-1]
        if len(lines) <= max_lines:
            return f, size, lines
    f = _font(60, "Black")
    return f, 60, _wrap(draw, " ".join(parts), f, width)[:max_lines]


def _star(draw, cx, cy, r, fill):
    import math
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy - rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


def _check(draw, x, y, size, color):
    draw.ellipse((x, y, x + size, y + size), fill=color)
    w = max(4, size // 7)
    draw.line([(x + size * 0.27, y + size * 0.52), (x + size * 0.44, y + size * 0.68), (x + size * 0.74, y + size * 0.34)],
              fill=WHITE, width=w, joint="curve")


def _rounded(img, radius):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    return mask


def render(spec, out_path):
    """縦長（2:3）のピン画像を作る。

    spec: headline（「/」で改行）・points（3つ）・board・rating・reviews・price・photo（商品写真。PIL の画像か None）
    商品写真は楽天のルールに合わせて、切り取らず・上に文字を重ねず、大きさだけ変えて白い台紙に置く。
    """
    theme = THEMES.get(spec.get("board"), THEMES["季節の準備・暮らし"])
    img = Image.new("RGB", (W, H), theme["bg"])
    d = ImageDraw.Draw(img)
    pad = 64

    # 上: 小さなラベル
    label = spec.get("label") or "子育て家族の“買ってよかった”"
    lf = _font(34, "Bold")
    lw = d.textlength(label, font=lf)
    d.rounded_rectangle((pad, 56, pad + lw + 48, 112), radius=28, fill=WHITE)
    d.text((pad + 24, 64), label, font=lf, fill=theme["accent"])

    # 見出し（いちばん目立つ所）。最後の行に蛍光ペンの線
    hf, hs, lines = _fit_headline(d, spec["headline"], W - pad * 2)
    y = 146
    for i, line in enumerate(lines):
        if i == len(lines) - 1:
            lw = d.textlength(line, font=hf)
            d.rounded_rectangle((pad - 6, y + hs * 0.58, pad + lw + 6, y + hs * 1.08), radius=10, fill=theme["mark"])
        d.text((pad, y), line, font=hf, fill=INK)
        y += int(hs * 1.24)

    # 商品写真（白い台紙の中に、切り取らずに収める）
    footer_top = H - 150
    points = spec.get("points", [])[:3]
    pts_h = 56 * len(points) + 24
    info_h = 64 if (spec.get("rating") or spec.get("price")) else 0
    card_top = y + 48  # 台紙の角の ことり が見出しに重ならないように
    card_bottom = footer_top - pts_h - info_h - 40
    card = (pad, card_top, W - pad, card_bottom)
    d.rounded_rectangle((card[0] + 6, card[1] + 10, card[2] + 6, card[3] + 10), radius=40, fill=tuple(max(0, c - 18) for c in theme["bg"]))
    d.rounded_rectangle(card, radius=40, fill=WHITE)
    inner_w, inner_h = card[2] - card[0] - 80, card[3] - card[1] - 80
    photo = spec.get("photo")
    if photo is not None and inner_h > 120:
        ph = photo.convert("RGB")
        scale = min(inner_w / ph.width, inner_h / ph.height)
        ph = ph.resize((max(1, int(ph.width * scale)), max(1, int(ph.height * scale))), Image.LANCZOS)
        img.paste(ph, (card[0] + 40 + (inner_w - ph.width) // 2, card[1] + 40 + (inner_h - ph.height) // 2))
    elif ILLUST.exists() and inner_h > 120:  # 写真がないときは、ことりのイラスト
        art = Image.open(ILLUST).convert("RGB")
        scale = min(inner_w / art.width, inner_h / art.height)
        art = art.resize((int(art.width * scale), int(art.height * scale)), Image.LANCZOS)
        img.paste(art, (card[0] + 40 + (inner_w - art.width) // 2, card[1] + 40 + (inner_h - art.height) // 2),
                  _rounded(art, 24))
    if AVATAR.exists():  # 台紙の角から ことり がのぞく（写真には重ねない）
        av = Image.open(AVATAR).convert("RGBA").resize((128, 128), Image.LANCZOS)
        ring = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((0, 0, 139, 139), fill=WHITE)
        ring.paste(av, (6, 6), av)
        img.paste(ring, (card[2] - 120, card[1] - 56), ring)
    sf = _font(26, "Medium")
    if photo is not None:
        d.text((card[2] - 24 - d.textlength("画像：楽天市場", font=sf), card[3] - 40), "画像：楽天市場", font=sf, fill=(170, 160, 150))

    # 評価と価格（商品情報から分かる事実だけ）
    y = card_bottom + 30
    if info_h:
        x = pad
        if spec.get("rating"):
            r = float(spec["rating"])
            for i in range(5):
                _star(d, x + 22 + i * 46, y + 24, 20, theme["accent"] if i < int(r + 0.5) else LINE)
            x += 5 * 46 + 14
            t = f"{r:.2f}".rstrip("0").rstrip(".") + (f"（{spec['reviews']:,}件）" if spec.get("reviews") else "")
            d.text((x, y), t, font=_font(38, "Bold"), fill=INK)
        if spec.get("price"):
            pt = f"{spec['price']:,}円〜"
            pf = _font(38, "Black")
            pw = d.textlength(pt, font=pf)
            d.rounded_rectangle((W - pad - pw - 40, y - 6, W - pad, y + 52), radius=29, fill=theme["accent"])
            d.text((W - pad - pw - 20, y), pt, font=pf, fill=WHITE)
        y += info_h

    # 良いところ（チェックつき）
    pf = _font(42, "Bold")
    for p in points:
        _check(d, pad, y + 6, 40, theme["accent"])
        d.text((pad + 58, y), _wrap(d, p, pf, W - pad * 2 - 60)[0] if p else "", font=pf, fill=INK)
        y += 56

    # 下: ことり と PR
    d.line((pad, footer_top, W - pad, footer_top), fill=tuple(max(0, c - 24) for c in theme["bg"]), width=2)
    d.text((pad, footer_top + 30), "ことり", font=_font(40, "Black"), fill=INK)
    d.text((pad, footer_top + 80), "@kotori.family", font=_font(30, "Medium"), fill=SUB)
    cta = "楽天でチェック ›"
    cf = _font(36, "Black")
    cw = d.textlength(cta, font=cf)
    d.rounded_rectangle((W - pad - cw - 56, footer_top + 38, W - pad, footer_top + 108), radius=35, fill=INK)
    d.text((W - pad - cw - 28, footer_top + 52), cta, font=cf, fill=WHITE)
    d.text((W - pad - cw - 56 - 70, footer_top + 56), "PR", font=_font(32, "Bold"), fill=SUB)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)
    return out_path


def fetch_photo(item, timeout=15):
    """楽天の商品写真を大きめのサイズで取る。取れなければ None。"""
    url = item.get("image") or ""
    if not url.startswith("https://"):
        return None
    if "thumbnail.image.rakuten.co.jp" in url:
        url = url.split("?")[0] + "?_ex=600x600"
    try:
        import io
        import requests
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 商品写真を取れませんでした（イラストにします）: {str(e)[:80]}")
        return None


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


def make_pins(config, today, items, generate, pin_dir=PIN_DIR, manual_dir=None, fetch=True):
    """商品ごとにピンを作り、manual/pins.json に追加する。返り値: 作ったピンの一覧。"""
    conf = config.get("pinterest", {})
    if not conf.get("enabled", True) or not items:
        return []
    items = items[: conf.get("per_day", 2)]
    boards = conf.get("boards") or DEFAULT_BOARDS
    system, user = prompts.pin_messages(config["account"], today, items, boards)
    result = {p["id"]: p for p in generate(system, user, prompts.PIN_SCHEMA, tier="standard")["pins"]}
    made, n = [], 0
    for item in items:
        pin = result.get(item["id"])
        if not pin:
            continue
        problems = check_pin(pin)
        if problems:
            print("⚠️ ピンを1枚見送りました: " + " / ".join(problems[:3]))
            continue
        n += 1
        while (Path(pin_dir) / f"{today.isoformat()}-{n}.png").exists():  # 同じ日に2回作っても上書きしない
            n += 1
        name = f"{today.isoformat()}-{n}.png"
        board = pin["board"] if pin["board"] in boards else boards[0]
        render({"headline": pin["headline"], "points": pin["points"], "board": board,
                "rating": item.get("review_average") if item.get("review_count") else None,
                "reviews": item.get("review_count"), "price": item.get("price"),
                "photo": fetch_photo(item) if fetch else None}, Path(pin_dir) / name)
        made.append({
            "key": f"{today.isoformat()}:{item['id']}", "date": today.isoformat(),
            "title": pin["title"], "description": pin["description"],
            "board": board,
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


# ---------------------------------------------------------------- 週1回のまとめて予約（.csv）

CSV_HEAD = ["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link", "Publish date", "Keywords"]
SLOTS = [(8, 0), (20, 30)]  # 日本時間で 1日2枚
JST = datetime.timezone(datetime.timedelta(hours=9))


def _slots_after(start):
    day = start.date()
    while True:
        for h, m in SLOTS:
            t = datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=JST)
            if t > start:
                yield t
        day += datetime.timedelta(days=1)


def export_csv(now, limit=14, exclude=(), manual_dir=None, csv_path=None):
    """まだ予約していないピンに日時を割り当て、Pinterest に読み込ませる .csv を作る。返り値: 予約したピン。"""
    path = Path(manual_dir or ROOT / "_affiliate" / "manual") / "pins.json"
    pins = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    for p in pins:
        if p["key"] in exclude and not p.get("scheduled_at"):
            p["posted_by_hand"] = True
    todo = sorted([p for p in pins if not p.get("scheduled_at") and not p.get("posted_by_hand") and not p.get("pin_id")], key=lambda p: p["date"])[:limit]
    # 前に予約した最後の枠のあとから、明日の朝より前にはしない
    last = max([datetime.datetime.fromisoformat(p["scheduled_at"]) for p in pins if p.get("scheduled_at")], default=None)
    tomorrow = datetime.datetime.combine(now.astimezone(JST).date(), datetime.time(0, 0), JST) + datetime.timedelta(days=1)
    start = max(last, tomorrow - datetime.timedelta(minutes=1)) if last else tomorrow - datetime.timedelta(minutes=1)
    rows = []
    for p, t in zip(todo, _slots_after(start)):
        p["scheduled_at"] = t.isoformat(timespec="minutes")
        utc = t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        rows.append([p["title"], p["image_url"], p["board"], "", p["description"], p["link"], utc, ", ".join(p.get("keywords", []))])
    import csv
    import io
    buf = io.StringIO()
    buf.write(",".join(CSV_HEAD) + "\r\n")  # 見出しは Pinterest のサンプルと同じ形（" で囲まない）
    csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n").writerows(rows)
    out = Path(csv_path or PIN_DIR / "upload.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(buf.getvalue(), encoding="utf-8")
    path.write_text(json.dumps(pins, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"📥 {len(todo)}枚を予約するファイルを作りました" + (f"（{todo[0]['scheduled_at']} から）" if todo else ""))
    return todo


def waiting_count(manual_dir=None):
    path = Path(manual_dir or ROOT / "_affiliate" / "manual") / "pins.json"
    pins = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return sum(1 for p in pins if not p.get("scheduled_at") and not p.get("posted_by_hand") and not p.get("pin_id"))


def main(argv=None):
    import argparse
    import subprocess
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true", help="1週間分の予約ファイルを作る")
    ap.add_argument("--exclude", default="", help="手で出したピンの key（カンマ区切り）")
    ap.add_argument("--remind", action="store_true", help="日曜日に、予約を待っているピンがあれば通知する")
    a = ap.parse_args(argv)
    now = datetime.datetime.now(JST)
    if a.export:
        made = export_csv(now, exclude={k for k in a.exclude.split(",") if k})
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as f:
            f.write(f"count={len(made)}\n")
        return 0
    if a.remind:
        n = waiting_count()
        if now.weekday() == 6 and n:
            subprocess.run([sys.executable, str(HERE / "push.py"), "send", "--title", f"📌 今週のピン {n} 枚",
                            "--body", "1週間分のファイルを作って Pinterest に読み込みましょう（1分）",
                            "--url", "https://keiyamada-ui.github.io/kotori/pins.html", "--add", "1"], check=False)
        return 0
    return 1


if __name__ == "__main__" and len(__import__("sys").argv) > 1:
    raise SystemExit(main())

if __name__ == "__main__":  # 見た目の確認用
    render({"headline": "なわとびが続かない/軽いロープで再挑戦", "points": ["軽くて回しやすい", "長さを調整できる", "練習が楽しくなる"],
            "board": "小学生の習い事・知育", "rating": 4.6, "reviews": 250, "price": 1280}, Path("/tmp/pin-sample.png"))
    print(_font_path(), datetime.date.today())
