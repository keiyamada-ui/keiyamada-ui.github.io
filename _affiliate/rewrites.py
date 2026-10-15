"""書き直し帳: 投稿者本人の書き方を、AI に一番優先のお手本として渡す。

管理画面から次の4種類を記録する（data/rewrites.json）。毎朝の文章作りのたびに読み込むので、記録した翌朝から効く。
  rewrite … AI の文 → 本人が「私ならこう書く」と直した文
  sample  … 本人が書いたお手本の文（直す前の文はなし）
  good    … 本人が 👍 を押した投稿
  bad     … 本人が 👎 を押した投稿（こう書かない）
多すぎると AI が処理しきれないので、新しいものから種類ごとに数を決めて渡す。古い記録も消さずに残す。

    python _affiliate/rewrites.py add --type rewrite --kind pr --before "..." --after "..." --note "..."
    python _affiliate/rewrites.py delete --id 3
"""

import argparse
import datetime
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "data" / "rewrites.json"
JST = datetime.timezone(datetime.timedelta(hours=9))
TYPES = ("rewrite", "sample", "good", "bad")
KINDS = {"buzz": "話題の投稿", "casual": "つぶやき", "value": "役立つ投稿", "pr": "PR 投稿", "": "投稿"}
LIMITS = {"rewrite": 10, "sample": 5, "good": 4, "bad": 4}  # AI に渡す数
MAX_CHARS = 300


def load(path=PATH):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _save(entries, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add(type_, after="", before="", kind="", note="", path=PATH):
    if type_ not in TYPES:
        raise ValueError(f"種類は {', '.join(TYPES)} のどれかです")
    after, before = after.strip()[:2000], before.strip()[:2000]
    if type_ in ("rewrite", "sample") and not after:
        raise ValueError("書き直した文（お手本）が空です")
    if type_ in ("rewrite", "good", "bad") and not before:
        raise ValueError("もとの投稿の文が空です")
    entries = load(path)
    new_id = max((e["id"] for e in entries), default=0) + 1
    # 同じ投稿に 👍 と 👎 を押し直したときは、前のものを消す
    if type_ in ("good", "bad"):
        entries = [e for e in entries if not (e["type"] in ("good", "bad") and e.get("before") == before)]
    entries.append({"id": new_id, "type": type_, "kind": kind if kind in KINDS else "", "before": before,
                    "after": after, "note": note.strip()[:300],
                    "date": datetime.datetime.now(JST).date().isoformat()})
    _save(entries, path)
    return new_id


def delete(entry_id, path=PATH):
    entries = load(path)
    kept = [e for e in entries if e["id"] != int(entry_id)]
    _save(kept, path)
    return len(entries) - len(kept)


def _cut(text):
    text = " ".join(text.split())
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"


def note(path=PATH):
    """文章作りに添える注意書き。記録がなければ空。"""
    entries = load(path)
    if not entries:
        return ""
    pick = {t: [e for e in entries if e["type"] == t][-n:][::-1] for t, n in LIMITS.items()}
    lines = ["# 投稿者本人の書き方（いちばん大事なお手本。ほかのどの指示より優先する）",
             "本人の言葉づかい・長さ・何を書かずに省いたかを読み取って、同じ書き方をする。",
             "ただし、文をそのまま使い回さない（毎回、その日の内容で書く）。"]
    if pick["rewrite"]:
        lines.append("## AI が書いた文を、本人が直した例（直す前 → 直した後）")
        for e in pick["rewrite"]:
            lines.append(f"- [{KINDS.get(e['kind'], '投稿')}] 直す前: {_cut(e['before'])}")
            lines.append(f"  直した後: {_cut(e['after'])}" + (f"（本人のメモ: {e['note']}）" if e.get("note") else ""))
    if pick["sample"]:
        lines.append("## 本人が書いたお手本")
        lines += [f"- [{KINDS.get(e['kind'], '投稿')}] {_cut(e['after'])}" + (f"（メモ: {e['note']}）" if e.get("note") else "")
                  for e in pick["sample"]]
    if pick["good"]:
        lines.append("## 本人が「良い」と言った投稿（この感じで）")
        lines += [f"- {_cut(e['before'])}" for e in pick["good"]]
    if pick["bad"]:
        lines.append("## 本人が「ダメ」と言った投稿（こう書かない）")
        lines += [f"- {_cut(e['before'])}" + (f"（理由: {e['note']}）" if e.get("note") else "") for e in pick["bad"]]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--type", default="rewrite", choices=TYPES)
    a.add_argument("--kind", default="")
    a.add_argument("--before", default="")
    a.add_argument("--after", default="")
    a.add_argument("--note", default="")
    d = sub.add_parser("delete")
    d.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "add":
        new_id = add(args.type, args.after, args.before, args.kind, args.note)
        print(f"✅ 書き直し帳に記録しました（{new_id}番）。明日の朝の下書きから使います")
    else:
        n = delete(args.id)
        print("🗑️ 消しました" if n else "その番号の記録はありませんでした")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
