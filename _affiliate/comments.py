"""自分の投稿についたコメントを集めて、対応（返信・いいねだけ・返さない）と返信文の案を作る。

    python _affiliate/comments.py

返信は自動ではせず、スマホの管理画面「💬 コメント」に案を並べて、本人がコピーして返す。
（自動返信は機械っぽく見えやすく、楽天のルール上も返信での宣伝はできないため）
結果は manual/comments.json に保存する。
"""

import datetime
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import autopost  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
from threads import ThreadsClient  # noqa: E402

LOOKBACK_DAYS = 3
KEEP = 100
ACTIONS = {"reply": "💬 返信する", "like": "❤️ いいねだけ", "ignore": "🙈 返さない"}


def _post_text(drafts_dir, entry):
    path = Path(drafts_dir) / entry["draft"]
    if not path.exists():
        return ""
    posts = json.loads(path.read_text(encoding="utf-8"))["posts"]
    return posts[entry["post_index"]]["text"] if entry["post_index"] < len(posts) else ""


def collect_new(client, posted, today, known_ids, drafts_dir, own_name):
    """まだ見ていないコメントを集める。権限がないときは (None, 理由)。"""
    recent = [p for p in posted if p.get("ids")
              and (today - datetime.date.fromisoformat(p["date"])).days <= LOOKBACK_DAYS]
    new, checked = [], 0
    for entry in recent:
        try:
            replies = client.replies(entry["ids"][0])
        except Exception as e:  # noqa: BLE001
            if checked == 0:
                return None, f"コメントを取得できませんでした（権限 threads_read_replies が必要です: {str(e)[:100]}）"
            continue
        checked += 1
        for r in replies:
            if r.get("id") in known_ids or r.get("username") == own_name or not (r.get("text") or "").strip():
                continue
            if r.get("hide_status") not in (None, "", "NOT_HUSHED", "UNHUSHED"):
                continue  # 非表示にしたコメント
            new.append({"id": r["id"], "username": r.get("username", ""), "text": r["text"],
                        "permalink": r.get("permalink", ""), "timestamp": r.get("timestamp", ""),
                        "post_text": _post_text(drafts_dir, entry), "post_permalink": entry.get("permalink", ""),
                        "post_kind": entry["kind"]})
    return new, None


def suggest(config, items, generate):
    """AI に対応と返信文の案を考えてもらう。失敗したら「返信する」で案なしにする。"""
    if not items:
        return items
    try:
        system, user = prompts.comment_messages(config["account"], items)
        replies = {r["id"]: r for r in generate(system, user, prompts.COMMENT_SCHEMA, tier="casual")["replies"]}
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 返信文の案を作れませんでした: {e}")
        replies = {}
    for item in items:
        r = replies.get(item["id"], {})
        action = r.get("action") if r.get("action") in ACTIONS else "reply"
        reply = (r.get("reply_text") or "").strip() if action == "reply" else ""
        if "http" in reply or "PR" in reply:
            reply = ""  # 返信でリンク・宣伝はしない
        item.update(action=action, reason=r.get("reason", ""), reply_text=reply)
    return items


def save(path, items, now):
    path = Path(path)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"comments": []}
    merged = items + [c for c in old["comments"] if c["id"] not in {i["id"] for i in items}]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated": now.isoformat(timespec="minutes"), "comments": merged[:KEEP]},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def report(items):
    if not items:
        return ""
    counts = {a: sum(1 for i in items if i["action"] == a) for a in ACTIONS}
    lines = [f"💬 **新しいコメントが {len(items)} 件** あります（" +
             "・".join(f"{ACTIONS[a]} {n}" for a, n in counts.items() if n) + "）",
             "管理画面の「💬 コメント」で返信文の案をコピーして返してください: https://keiyamada-ui.github.io/kotori/stock.html#comments"]
    for i in items[:5]:
        lines.append(f"- @{i['username']}: {i['text'][:40]} → {ACTIONS[i['action']]}")
    return "\n" + "\n".join(lines) + "\n"


def main():
    token = os.environ.get("KOTORI_THREADS_TOKEN")
    if not token:
        print("Threads のトークンがないため、コメントは確認しません")
        return 0
    config = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    now = datetime.datetime.now(autopost.JST)
    path = HERE / "manual" / "comments.json"
    known = {c["id"] for c in json.loads(path.read_text(encoding="utf-8"))["comments"]} if path.exists() else set()
    client = ThreadsClient(token)
    posted = autopost.load_posted(HERE / "data" / "posted")
    items, reason = collect_new(client, posted, now.date(), known, HERE / "drafts", client.me().get("username"))
    if items is None:
        print(f"⚠️ {reason}")
        return 0
    items = suggest(config, items, llm.Generator(config.get("ai")))
    if items:
        save(path, items, now)
    text = report(items)
    print(text or "新しいコメントはありません")
    autopost.write_output(report=text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
