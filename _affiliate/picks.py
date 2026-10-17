"""PR で紹介した物の一覧（サイトの /picks/ ページ）: 投稿した順に【1】【2】…と番号を付けて並べる。

Threads の投稿は流れていくので、プロフィールのリンクからこの一覧を見れば、あとからでも商品が見つかる。
PR 投稿をするたびに autopost.py から作り直す（手で投稿した印を付けたときも）。
番号は一度付けたら変えない（投稿で「【12】」と書いた番号がずれないように）。

    python _affiliate/picks.py    # 投稿の記録から一覧を作り直す
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "_data" / "picks.json"
POSTED = HERE / "data" / "posted"
DRAFTS = HERE / "drafts"
ROOM = HERE / "manual" / "room.json"  # 古い下書きには画像がないので、ROOM の一覧から探す
NAME_CHARS = 34
THREADS_LIMIT = 500

_BRACKETS = re.compile(r"[【\[（(＜<《★☆].*?[】\]）)＞>》★☆]")
_NOISE = re.compile(r"(送料無料|クーポン\S*|ポイント\d*倍|\d+%OFF|半額|先着\S*|公式|楽天\S*位|あす楽|即納)")


def short_name(name, limit=NAME_CHARS):
    """長い商品名を、一覧で読める長さにする（宣伝の言葉や【】を外す）。"""
    words = _NOISE.sub(" ", _BRACKETS.sub(" ", name or "")).split()
    out = ""
    for w in words:
        if out and len(out) + 1 + len(w) > limit:
            break
        out = f"{out} {w}".strip()
    return out[:limit] or (name or "")[:limit]


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def build(posted_dir=POSTED, drafts_dir=DRAFTS, out=OUT, room=ROOM):
    """投稿の記録から一覧を作る。前の一覧の番号はそのまま使い、新しい物に続きの番号を付ける。"""
    old = _load(out, [])
    by_id = {p["id"]: p for p in old}
    images = {r["id"]: r["image"] for r in _load(room, []) if r.get("id") and r.get("image")}
    entries = []
    for path in sorted(Path(posted_dir).glob("*.json")) if Path(posted_dir).exists() else []:
        entries += [e for e in json.loads(path.read_text(encoding="utf-8")) if e.get("kind") == "pr"]
    entries.sort(key=lambda e: e.get("at", e.get("date", "")))
    seen = set()
    for e in entries:
        draft = _load(Path(drafts_dir) / e.get("draft", ""), {})
        item = draft.get("chosen") or {}
        if not item.get("id") or not item.get("url"):
            continue
        seen.add(item["id"])
        if item["id"] in by_id:  # 同じ物をもう一度紹介したときは、番号はそのまま。新しい投稿へのリンクにする
            if e.get("permalink"):
                by_id[item["id"]]["threads"] = e["permalink"]
            by_id[item["id"]]["image"] = by_id[item["id"]]["image"] or item.get("image") or images.get(item["id"], "")
            continue
        by_id[item["id"]] = {
            "no": max((p["no"] for p in by_id.values()), default=0) + 1,
            "id": item["id"], "name": short_name(item.get("name", "")), "url": item["url"],
            "image": item.get("image") or images.get(item["id"], ""), "date": e.get("date", ""), "threads": e.get("permalink", ""),
        }
    # 「手で投稿した」を取り消した物は外す（番号は詰めない）
    picks = sorted((p for p in by_id.values() if p["id"] in seen), key=lambda p: p["no"])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(picks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return picks


def with_number(text, item_id, out=OUT, limit=THREADS_LIMIT):
    """リンクの返信に「一覧の【12】」を書き足す。Threads の文字数の上限を超えるときは足さない。"""
    line = f"プロフィールのリンクの一覧【{number_for(item_id, out)}】にも載せています"
    return f"{text}\n{line}" if text and len(text) + 1 + len(line) <= limit else text


def number_for(item_id, out=OUT):
    """この商品の一覧での番号（まだ載っていなければ、次に付く番号）。"""
    picks = _load(out, [])
    for p in picks:
        if p["id"] == item_id:
            return p["no"]
    return max((p["no"] for p in picks), default=0) + 1


if __name__ == "__main__":
    print(f"✅ 紹介した物の一覧: {len(build())} 件")
