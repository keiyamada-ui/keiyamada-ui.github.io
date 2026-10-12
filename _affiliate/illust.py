"""Threads の投稿に、ときどき（7〜10回に1回）ことりの世界観のイラストを付ける。

毎朝の下書き作りのあとに動く。
1. 前回イラストを付けた投稿から、決めた回数（7〜10回）がたっていれば、今日の下書きのうち
   PR 以外（つぶやき・集客投稿・役立つ投稿）から、イラストが合う1本を AI が選び、場面を考える。
2. Gemini の画像の AI で、ことりの画像を見本に、ふんわりしたイラストを1枚描く（文字・商品・実在の人は描かない）。
3. 別の AI が画像を見て、崩れや文字が入っていないかを確認。ダメなら1回だけ描き直し、それでもダメなら付けない。
4. 画像を kotori/illust/ に置き（GitHub Pages で公開される）、下書きに image / image_url を書き込む。
自動投稿は image_url があればイラストつきで出す（失敗したら文章だけ）。管理画面で外すこともできる。
"""

import base64
import datetime
import io
import json
import os
import random
from pathlib import Path

import requests
from PIL import Image

import prompts

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_DIR = ROOT / "kotori" / "illust"
SITE = "https://keiyamada-ui.github.io/kotori/illust/"
STATE = HERE / "data" / "illust.json"
REFS = [ROOT / "kotori" / "avatar.png", ROOT / "kotori" / "header.jpg"]
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = ["gemini-3.1-flash-image", "gemini-2.5-flash-image"]
KEEP = 60

STYLE = """Draw ONE illustration in exactly the same art style as the reference images:
a soft, gentle, hand-drawn picture-book style with delicate thin pencil-like outlines, a pale cream / off-white background,
and muted warm pastel colors (butter yellow, blush pink, soft peach, sage green, light gray).
The characters are cute round cockatiel birds like the reference character "Kotori" (pale yellow body, rosy round cheeks,
a small curled crest). Show the scene with these birds acting it out, like a parent bird and chicks in a cozy home.
Cozy, calm, warm, slightly whimsical. Plenty of soft empty space. Square composition.
Absolutely NO text, letters, numbers, speech bubbles, logos, brand names, or real products. No humans. No realistic photo style."""


class IllustError(Exception):
    pass


# ---------------------------------------------------------------- いつ付けるか

def _load_state(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def posts_since_last_image(posted):
    """最後にイラストつきで出した投稿のあとに、自動で出した投稿の数。"""
    auto = sorted([p for p in posted if not p.get("manual")], key=lambda p: p.get("at", ""))
    n = 0
    for p in auto:
        n = 0 if p.get("image") else n + 1
    return n


def due(posted, state, today):
    """今日の下書きにイラストを付けるか。今日このあと出る数本も見込んで、7〜10回に1回になるようにする。"""
    if state.get("last_made") and (today - datetime.date.fromisoformat(state["last_made"])).days < 1:
        return False
    every = state.get("every") or 8
    return posts_since_last_image(posted) + 2 >= every


# ---------------------------------------------------------------- どの投稿に・どんな絵を

def candidates(drafts_dir, today):
    out = []
    for name in (f"{today.isoformat()}-casual.json", f"{today.isoformat()}-buzz.json", f"{today.isoformat()}.json"):
        path = Path(drafts_dir) / name
        if not path.exists():
            continue
        draft = json.loads(path.read_text(encoding="utf-8"))
        if draft.get("errors"):
            continue
        for i, p in enumerate(draft.get("posts", [])):
            if p.get("type") in ("casual", "buzz", "value") and not p.get("image"):
                out.append({"ref": f"{name}#{i}", "type": p["type"], "text": p["text"][:300]})
    return out


SCHEMA = prompts.obj(ref=prompts.STR, scene=prompts.STR, why=prompts.STR)


def choose(config, items, generate):
    system = f"""あなたは SNS のイラストの企画担当です。{prompts._persona(config['account'])}

今日の投稿の中から、ふんわりした小鳥のイラストを添えると一番「ほっこり・共感」が増える1本を選び、描く場面を考えてください。
- 子育ての日常・あるある・ちょっとした気持ちが伝わる投稿を優先。情報が多い投稿や、商品の話が中心の投稿は避ける。
- scene: 英語で、ことり（小鳥の親子）がその場面を演じる様子を具体的に（場所・小物・表情・時間帯）。
  文字・商品・ロゴ・人間は描かない。季節は、今の季節感のメモに合わせる（季節の話でなければ季節を強調しない）。
- ref: 選んだ投稿の ref をそのまま。why: 選んだ理由（日本語で短く）。
JSON だけを返す。"""
    user = "今日の投稿:\n" + "\n".join(json.dumps(x, ensure_ascii=False) for x in items)
    res = generate(system, user, SCHEMA, tier="standard")
    if res.get("ref") not in {x["ref"] for x in items}:
        res["ref"] = items[0]["ref"]
    return res


# ---------------------------------------------------------------- 描く・確かめる

def _b64(path):
    data = Path(path).read_bytes()
    mime = "image/png" if str(path).endswith(".png") else "image/jpeg"
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}


def draw(scene, models=None, key=None, session=None):
    """Gemini の画像の AI で1枚描く。返り値: PIL の画像。"""
    key = key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise IllustError("GEMINI_API_KEY がないため、イラストを描けません")
    http = session or requests
    parts = [_b64(p) for p in REFS if p.exists()] + [{"text": f"{STYLE}\n\nScene: {scene}"}]
    last = ""
    names = list(models or DEFAULT_MODELS)
    try:  # 名前が変わっていても動くように、使える画像の AI を一覧から探して足す
        listed = http.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 1000},
                          headers={"x-goog-api-key": key}, timeout=30).json().get("models", [])
        found = [m["name"].split("/")[-1] for m in listed
                 if "image" in m["name"] and "flash" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", [])]
        names += [n for n in sorted(found, reverse=True) if n not in names]
    except Exception:  # noqa: BLE001
        pass
    for model in names:
        for config in ({"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}},
                       {"responseModalities": ["TEXT", "IMAGE"]}):
            res = http.post(API.format(model=model), headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                            json={"contents": [{"role": "user", "parts": parts}], "generationConfig": config}, timeout=180)
            if res.status_code == 404:
                last = f"{model}: 見つかりません"
                break  # この名前の AI はない → 次の候補へ
            if res.status_code == 429 and "quota" in res.text.lower():
                raise IllustError("Gemini の無料枠では画像を描けません。Google AI Studio で支払い（課金）の設定をすると描けるようになります")
            if res.status_code != 200:
                last = f"{model}: HTTP {res.status_code} {res.text[:150]}"
                continue
            for p in res.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
                data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
                if data:
                    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
            last = f"{model}: 画像が返ってきませんでした"
    raise IllustError(f"イラストを描けませんでした（{last}）")


CHECK_SCHEMA = prompts.obj(ok={"type": "boolean"}, problems=prompts.STRS)


def check(img, scene, key=None, session=None):
    """別の AI（Gemini）が画像を見て確かめる。返り値: (OK か, 問題のリスト)。"""
    import llm
    key = key or os.environ.get("GEMINI_API_KEY")
    http = session or requests
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    prompt = ("この画像を SNS に載せてよいか厳しく確認してください。NG: 文字・数字・ロゴが入っている／体や顔が崩れている／"
              "鳥以外の生き物や人間が描かれている／怖い・不潔・暗い印象／写真のようにリアル／場面が次の説明と合っていない。"
              f"\n場面の説明: {scene}\n"
              f"JSON だけを返す: {json.dumps(CHECK_SCHEMA, ensure_ascii=False)}")
    body = {"contents": [{"role": "user", "parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}, {"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}}
    res = http.post(llm.GEMINI_URL.format(model=llm.GEMINI_MODEL), json=body, timeout=120,
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    if res.status_code != 200:
        return True, [f"確認できませんでした（HTTP {res.status_code}）"]  # 確認役が混雑しているだけなら通す
    text = "".join(p.get("text", "") for p in res.json()["candidates"][0]["content"]["parts"])
    data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    return bool(data.get("ok")), data.get("problems", [])


def save(img, today, out_dir=OUT_DIR):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img.thumbnail((1080, 1080))
    n = 1
    while (out_dir / f"{today.isoformat()}-{n}.jpg").exists():
        n += 1
    path = out_dir / f"{today.isoformat()}-{n}.jpg"
    img.save(path, "JPEG", quality=90, optimize=True)
    for old in sorted(out_dir.glob("*.jpg"))[:-KEEP]:  # 古いイラストは消す
        old.unlink()
    return path


# ---------------------------------------------------------------- まとめ

def maybe_make(config, today, generate, drafts_dir, posted, state_path=STATE, out_dir=OUT_DIR, drawer=draw, checker=check):
    """必要なら今日の投稿にイラストを付ける。返り値: 付けた投稿の ref（付けなければ None）。"""
    conf = config.get("illust", {})
    if not conf.get("enabled", True):
        return None
    state = _load_state(state_path)
    if not due(posted, state, today):
        return None
    items = candidates(drafts_dir, today)
    if not items:
        return None
    plan = choose(config, items, generate)
    img, problems = None, []
    for _ in range(2):  # ダメなら1回だけ描き直す
        img = drawer(plan["scene"], conf.get("models"))
        ok, problems = checker(img, plan["scene"])
        if ok:
            break
        print(f"🖼️ イラストの確認でひっかかりました（描き直します）: {' / '.join(problems)[:150]}")
        img = None
    if img is None:
        print("🖼️ イラストは今日は付けません（確認で合格しなかったため）")
        return None
    path = save(img, today, out_dir)
    name, index = plan["ref"].split("#")
    draft_path = Path(drafts_dir) / name
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    draft["posts"][int(index)].update(image=f"kotori/illust/{path.name}", image_url=SITE + path.name, image_scene=plan["scene"])
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lo, hi = conf.get("every", [7, 10])
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps({"last_made": today.isoformat(),
                                            "every": random.randint(lo, hi), "ref": plan["ref"], "why": plan.get("why", "")},
                                           ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"🖼️ イラストを付けました: {plan['ref']}（{plan.get('why', '')}）")
    return plan["ref"]


def sample(scenes):
    """見本を描く（管理画面の確認・テイストの調整用）。kotori/illust/sample-N.jpg に保存する。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for n, scene in enumerate(scenes, 1):
        try:
            img = draw(scene)
            ok, problems = check(img, scene)
            img.thumbnail((1080, 1080))
            img.save(OUT_DIR / f"sample-{n}.jpg", "JPEG", quality=90)
            print(f"🖼️ 見本{n}: {'合格' if ok else '不合格 ' + ' / '.join(problems)}（{scene[:60]}）")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ 見本{n}を描けませんでした: {e}")


if __name__ == "__main__":
    sample(["A parent bird hurriedly helping a chick put on a tiny school backpack by the front door in the morning",
            "A parent bird and two chicks reading a picture book together on a cozy sofa in the evening",
            "A chick proudly showing a drawing to a parent bird at a small kitchen table"])
