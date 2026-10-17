"""体験メモ: 投稿者本人に実際にあったこと・使ってみた感想を書きためて、投稿に本人の体験として入れる。

人は「誰かが実際に体験したこと」をいちばん信じる。AI には体験が作れないので、本人のメモだけを体験として使う。
  ・PR 投稿・役立つ投稿 … その日の話題に合うメモがあれば、AI が1つだけ本人の体験として入れる（合わなければ使わない）
  ・つぶやき          … 話題を問わず、まだ使っていないメモから選ぶ
  ・商品名があるメモ   … その商品を楽天で探して、PR 投稿の候補にする（1日1つまで・一度だけ）
同じメモは、間を2週間あけて3回まで使う。メモに書いていないこと（感想・数字・結果）を足すのは禁止。
管理画面の「入力 → 体験メモ」から書く（data/experiences.json に保存）。

    python _affiliate/experiences.py add --text "..." --item "水筒 2way"
    python _affiliate/experiences.py edit --id 3 --text "..." --item ""
    python _affiliate/experiences.py delete --id 3
"""

import argparse
import datetime
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "data" / "experiences.json"
JST = datetime.timezone(datetime.timedelta(hours=9))
MAX_USES = 3
GAP_DAYS = 14
MAX_CHARS = 400

_HIRA = re.compile(r"^[ぁ-んー、。！？!?\s]+$")


def load(path=PATH):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def save(entries, path=PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _today():
    return datetime.datetime.now(JST).date()


def add(text, item="", path=PATH, today=None):
    text, item = text.strip()[:MAX_CHARS], item.strip()[:80]
    if not text:
        raise ValueError("体験メモが空です")
    entries = load(path)
    new_id = max((e["id"] for e in entries), default=0) + 1
    entries.append({"id": new_id, "text": text, "item": item, "date": (today or _today()).isoformat(),
                    "uses": [], "themed": ""})
    save(entries, path)
    return new_id


def edit(entry_id, text, item="", path=PATH):
    entries = load(path)
    for e in entries:
        if e["id"] == int(entry_id):
            if not text.strip():
                raise ValueError("体験メモが空です")
            if item.strip() != e.get("item", ""):
                e["themed"] = ""  # 商品が変わったら、もう一度 PR 候補にする
            e["text"], e["item"] = text.strip()[:MAX_CHARS], item.strip()[:80]
            save(entries, path)
            return True
    return False


def delete(entry_id, path=PATH):
    entries = load(path)
    kept = [e for e in entries if e["id"] != int(entry_id)]
    save(kept, path)
    return len(entries) - len(kept)


def _bigrams(text):
    """言葉の近さを見るための2文字の組（ひらがなだけの組は「の」「が」などで当たりやすいので除く）。"""
    text = re.sub(r"\s+", "", text or "")
    return {text[i:i + 2] for i in range(len(text) - 1) if not _HIRA.match(text[i:i + 2])}


def relevance(topic, entry):
    return len(_bigrams(topic) & _bigrams(entry["text"] + " " + entry.get("item", "")))


def usable(entry, today):
    uses = entry.get("uses", [])
    if len(uses) >= MAX_USES:
        return False
    return not uses or (today - datetime.date.fromisoformat(max(uses))).days >= GAP_DAYS


def candidates(entries, today, topic=None, limit=3, min_score=2):
    """使ってよいメモ。topic があれば話題に近いものだけ（近い順）、なければ使った回数の少ない・新しい順。"""
    ok = [e for e in entries if usable(e, today)]
    if topic is None:
        return sorted(ok, key=lambda e: (len(e.get("uses", [])), -e["id"]))[:limit]
    scored = [(relevance(topic, e), e) for e in ok]
    return [e for s, e in sorted(scored, key=lambda x: -x[0]) if s >= min_score][:limit]


def mark_used(entries, ids, today):
    ids = {int(i) for i in ids}
    for e in entries:
        if e["id"] in ids:
            e.setdefault("uses", []).append(today.isoformat())
    return entries


def item_themes(entries, today, make):
    """商品名が書いてあるメモから、PR 投稿のテーマを作る（まだテーマにしていないもの・古い順）。"""
    return [(e, make("体験", "ichiba", e["item"], "", category="体験メモの商品", urgency=5))
            for e in entries if e.get("item") and not e.get("themed") and usable(e, today)]


def lines(entries):
    """AI に渡す形: 「[3] メモ（商品: ...）」"""
    return [f"[{e['id']}] {e['text']}" + (f"（使っている物: {e['item']}）" if e.get("item") else "") for e in entries]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--text", required=True)
    a.add_argument("--item", default="")
    e = sub.add_parser("edit")
    e.add_argument("--id", required=True)
    e.add_argument("--text", required=True)
    e.add_argument("--item", default="")
    d = sub.add_parser("delete")
    d.add_argument("--id", required=True)
    args = p.parse_args(argv)
    if args.cmd == "add":
        print(f"✅ 体験メモに入れました（{add(args.text, args.item)}番）。翌朝の投稿から使います")
    elif args.cmd == "edit":
        print("✏️ 直しました" if edit(args.id, args.text, args.item) else "その番号のメモはありませんでした")
    else:
        print("🗑️ 消しました" if delete(args.id) else "その番号のメモはありませんでした")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
