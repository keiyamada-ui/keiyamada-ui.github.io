"""週1回のふり返り（日曜の夜）: この1週間の数字と、いちばん見られた投稿、来週の行事をスマホに知らせる。

    data/weekly/YYYY-MM-DD.json に保存（管理画面の「成果」で見られる）
    python _affiliate/weekly.py            # 作って通知する
    python _affiliate/weekly.py --no-push  # 作るだけ
"""

import argparse
import datetime
import json
from pathlib import Path

import events
import push

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
JST = datetime.timezone(datetime.timedelta(hours=9))


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def build(today, data=DATA, drafts=HERE / "drafts"):
    since = today - datetime.timedelta(days=6)
    days = [(since + datetime.timedelta(days=i)).isoformat() for i in range(7)]
    daily = _load(Path(data) / "stats" / "daily.json", {})
    rows = [daily[d] for d in days if d in daily]
    followers = [daily[d]["followers"] for d in sorted(daily) if daily[d].get("followers") is not None]
    week_f = [daily[d]["followers"] for d in days if daily.get(d, {}).get("followers") is not None]
    before = [daily[d]["followers"] for d in sorted(daily) if d < days[0] and daily[d].get("followers") is not None]
    start_f = before[-1] if before else (week_f[0] if week_f else None)
    store = _load(Path(data) / "insights" / "latest.json", {})
    week_posts = [v for v in store.values() if days[0] <= v["date"] <= days[-1]]
    best = max(week_posts, key=lambda v: v["metrics"].get("views", 0), default=None)
    best_text = ""
    if best:
        d = _load(Path(drafts) / best["draft"], {})
        posts = d.get("posts", [])
        if best["post_index"] < len(posts):
            best_text = " ".join(posts[best["post_index"]]["text"].split())[:60]
    rewrites = [e for e in _load(Path(data) / "rewrites.json", []) if e.get("date", "") >= days[0]]
    return {
        "week": f"{days[0]}〜{days[-1]}",
        "views": sum(r.get("views", 0) for r in rows),
        "likes": sum(r.get("likes", 0) for r in rows),
        "replies": sum(r.get("replies", 0) for r in rows),
        "clicks": sum(r.get("clicks", 0) for r in rows),
        "posts": sum(r.get("posts", 0) for r in rows),
        "followers": followers[-1] if followers else None,
        "followers_diff": (week_f[-1] - start_f) if week_f and start_f is not None else None,
        "best": {"text": best_text, "views": best["metrics"].get("views", 0), "likes": best["metrics"].get("likes", 0),
                 "permalink": best.get("permalink", "")} if best else None,
        "taught": len(rewrites),
        "next_events": events.upcoming(today + datetime.timedelta(days=1)),
    }


def message(r):
    """通知の文（短く）。"""
    diff = r["followers_diff"]
    head = f"表示 {r['views']:,}・いいね {r['likes']}・リンク {r['clicks']}"
    if diff is not None:
        head += f"・フォロワー {'+' if diff >= 0 else ''}{diff}"
    lines = [head]
    if r["best"] and r["best"]["text"]:
        lines.append(f"いちばん見られた投稿: 「{r['best']['text'][:30]}…」（表示 {r['best']['views']:,}）")
    if r["next_events"]:
        lines.append("これからの行事: " + "、".join(r["next_events"][:3]))
    lines.append(f"今週 AI に教えた数: {r['taught']}" if r["taught"] else "気になる投稿は「私ならこう書く」で教えてね")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--date")
    a = p.parse_args(argv)
    today = datetime.date.fromisoformat(a.date) if a.date else datetime.datetime.now(JST).date()
    r = build(today)
    path = DATA / "weekly" / f"{today.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    text = message(r)
    print(text)
    if not a.no_push:
        push.send("📮 今週のふり返り", text, url="https://keiyamada-ui.github.io/kotori/stats.html", add=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
