"""自分の投稿から学ぶ（週1回）。

直近30日の投稿の反響（data/insights/latest.json）から、伸びた投稿と伸びなかった投稿を選び、
AI に違いを分析させて「このアカウントで伸びる書き方」を data/learned.json に保存する。
保存した学びは、毎朝の文章作りすべてに添える（prompts.LEARNED_NOTE）。
"""

import datetime
import json
import statistics
from pathlib import Path

import prompts

HERE = Path(__file__).resolve().parent
PATH = HERE / "data" / "learned.json"
KINDS = {"buzz": "集客投稿", "casual": "つぶやき", "value": "役立つ投稿", "pr": "PR 投稿"}
MIN_POSTS = 10       # これより少ないと、偶然の差を学んでしまう
EVERY_DAYS = 7


def score(m):
    """反響の点数: 反応（いいね・返信・再投稿・引用）を重く、表示を軽く。"""
    return m.get("likes", 0) + 3 * m.get("replies", 0) + 3 * m.get("reposts", 0) + 2 * m.get("quotes", 0) + m.get("views", 0) / 100


def _text(drafts_dir, v):
    path = Path(drafts_dir) / v["draft"]
    if not path.exists():
        return ""
    posts = json.loads(path.read_text(encoding="utf-8")).get("posts", [])
    return posts[v["post_index"]].get("text", "") if v["post_index"] < len(posts) else ""


def rows(store, today, drafts_dir, posted_times=None):
    out = []
    for media_id, v in store.items():
        if (today - datetime.date.fromisoformat(v["date"])).days < 1:
            continue  # 当日の投稿は、まだ反響が出そろっていない
        text = _text(drafts_dir, v)
        if not text:
            continue
        m = v["metrics"]
        out.append({"kind": KINDS.get(v["kind"], v["kind"]), "date": v["date"], "time": (posted_times or {}).get(media_id, ""),
                    "views": m.get("views", 0), "likes": m.get("likes", 0), "replies": m.get("replies", 0),
                    "reposts": m.get("reposts", 0), "chars": len(text), "text": text[:400], "_score": score(m)})
    return out


def due(today, path=PATH):
    if not Path(path).exists():
        return True
    last = json.loads(Path(path).read_text(encoding="utf-8")).get("updated", "2000-01-01")
    return (today - datetime.date.fromisoformat(last)).days >= EVERY_DAYS


def learn(config, today, store, generate, drafts_dir, posted_times=None, path=PATH, force=False):
    """学ぶ時期で、投稿が十分あれば分析して保存する。返り値: 保存した内容（しなかったら None）。"""
    if not store or not (force or due(today, path)):
        return None
    data = rows(store, today, drafts_dir, posted_times)
    if len(data) < MIN_POSTS:
        print(f"📚 自分の投稿から学ぶのは、反響のわかる投稿が{MIN_POSTS}件たまってから（今は{len(data)}件）")
        return None
    data.sort(key=lambda r: r["_score"], reverse=True)
    n = max(3, min(6, len(data) // 4))
    top, bottom = data[:n], data[-n:]
    averages = {}
    for r in data:
        averages.setdefault(r["kind"], []).append(r)
    averages = {k: {"件数": len(v), "平均いいね": round(statistics.mean(x["likes"] for x in v), 1),
                    "平均表示": round(statistics.mean(x["views"] for x in v))} for k, v in averages.items()}
    strip = lambda rs: [{k: v for k, v in r.items() if k != "_score"} for r in rs]  # noqa: E731
    system, user = prompts.learn_messages(config["account"], today, strip(top), strip(bottom), averages)
    result = generate(system, user, prompts.LEARN_SCHEMA, tier="important")
    saved = {"updated": today.isoformat(), "posts": len(data), "summary": result["summary"],
             "lessons": result["lessons"][:5], "averages": averages}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"📚 自分の投稿{len(data)}件から学びました: {saved['summary']}")
    return saved


def note(path=PATH):
    """文章作りに添える一文。学びがなければ空。"""
    path = Path(path)
    if not path.exists():
        return ""
    d = json.loads(path.read_text(encoding="utf-8"))
    lines = [f"- [{x['applies_to']}] {x['do']}（避ける: {x['avoid']}）" for x in d.get("lessons", [])]
    if not lines:
        return ""
    return (f"このアカウント自身の投稿の分析でわかったこと（{d['updated']}・{d['posts']}件から）: {d['summary']}\n"
            + "\n".join(lines) + "\n当てはまる種類の投稿では、これを参考にする（ルールと人間らしさが優先）。")


def load(path=PATH):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
