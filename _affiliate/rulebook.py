"""書き方のルール帳: 登録した「考え方・コツ」と「自分の投稿から学んだこと」を、少数のルールにまとめ直す。

考え方・コツを増やしていくと、ルールが多すぎたり、ぶつかり合ったりして、AI が全部を守りきれなくなる。
そこで、材料が変わったとき（または7日おき）に AI（Opus）が全部を読み、
- 似たものはまとめる・ぶつかるものは優先順位で決める（アカウントの決まり ＞ 自分の投稿の結果 ＞ 考え方・コツ）
- 大事なものだけ最大 MAX_RULES 個に絞る
という「ルール帳」（data/rulebook.json）を作る。毎日の文章作りには、このルール帳だけを添える。
"""

import datetime
import hashlib
import json
from pathlib import Path

import prompts

HERE = Path(__file__).resolve().parent
PATH = HERE / "data" / "rulebook.json"
MAX_RULES = 7
MAX_CHARS = 70
EVERY_DAYS = 7

SCHEMA = prompts.obj(
    rules={"type": "array", "items": prompts.obj(rule=prompts.STR, applies_to=prompts.STR, source=prompts.STR)},
    dropped={"type": "array", "items": prompts.obj(rule=prompts.STR, reason=prompts.STR)},
)


def materials(patterns, learned):
    """ルール帳の材料: [(出どころ, ルール)]。"""
    out = []
    for p in patterns:
        if p.get("kind") == "tips":
            out += [("考え方・コツ", r) for r in p.get("rules_for_us", [])]
    for x in (learned or {}).get("lessons", []):
        out.append(("自分の投稿の結果", f"[{x.get('applies_to', 'すべて')}] {x['do']}（避ける: {x['avoid']}）"))
    return out


def _hash(items):
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def build(config, today, items, generate):
    system = f"""あなたは SNS 運用の編集長です。{prompts._persona({**config['account']})}

このアカウントの投稿を書く AI に渡す「書き方のルール帳」を作ります。
材料のルールをすべて読み、次の手順で最大{MAX_RULES}個に絞ってください。
1. 同じ意味・似た意味のルールは1つにまとめる。
2. ぶつかるルールは、優先順位で決める: アカウントの決まり（人間らしさ・効果を断定しない・体験を作らない・PR表記）
   ＞ 自分の投稿の結果（実際のデータ） ＞ 考え方・コツ（一般論）。下位のほうを外す。
3. アカウントの決まりに反するもの、あいまいで守れないものは外す。
4. 残ったものから、投稿の伸びに効きそうな順に最大{MAX_RULES}個。各ルールは{MAX_CHARS}文字以内の「〜する」の形で具体的に。
- rules: rule（ルール）, applies_to（すべて / 集客投稿 / つぶやき / 役立つ投稿 / PR 投稿）, source（どの材料から来たか）
- dropped: 外したルールと理由（まとめた・ぶつかった・守れない など）
JSON だけを返す。"""
    user = "材料:\n" + "\n".join(f"- （{src}）{rule}" for src, rule in items)
    res = generate(system, user, SCHEMA, tier="important")
    rules = [r for r in res.get("rules", []) if r.get("rule")][:MAX_RULES]
    for r in rules:
        r["rule"] = r["rule"][:MAX_CHARS * 2]
    return {"rules": rules, "dropped": res.get("dropped", [])[:20]}


def ensure(config, today, patterns, learned, generate, path=PATH, force=False):
    """材料が変わった・7日たったときだけ作り直す。返り値: ルール帳（材料がなければ None）。"""
    items = materials(patterns, learned)
    path = Path(path)
    if not items:
        return None
    key = _hash(items)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    fresh = old.get("hash") == key and (today - datetime.date.fromisoformat(old.get("updated", "2000-01-01"))).days < EVERY_DAYS
    if fresh and not force:
        return old
    book = build(config, today, items, generate)
    book.update(hash=key, updated=today.isoformat(), materials=len(items))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(book, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"📏 ルール帳を作り直しました（材料{len(items)}個 → {len(book['rules'])}個）")
    return book


def note(book):
    if not book or not book.get("rules"):
        return ""
    return ("このアカウントの書き方のルール帳（大事な順・当てはまる種類の投稿で守る。アカウントの決まりと人間らしさが最優先）:\n"
            + "\n".join(f"{n}. [{r.get('applies_to', 'すべて')}] {r['rule']}" for n, r in enumerate(book["rules"], 1)))


def load(path=PATH):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
