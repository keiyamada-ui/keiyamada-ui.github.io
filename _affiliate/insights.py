"""投稿の反響（いいね・返信など）を Threads から取ってきて記録し、
反響が大きかった集客投稿を見つけて「その話題の商品を紹介する PR 投稿」につなげる。

反響の記録: data/insights/latest.json（投稿ID → 数字）
つなげた記録: data/followups.json（同じ投稿から二度 PR を作らないため）
"""

import datetime
import json
import statistics
from pathlib import Path

LOOKBACK_DAYS = 7


def _date(value):
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value))


def collect(client, posted, today, path):
    """直近の投稿の反響を取って保存する。権限がないなどで取れなければ (None, 理由) を返す。"""
    path = Path(path)
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    recent = [p for p in posted if p.get("ids") and (today - _date(p["date"])).days <= LOOKBACK_DAYS]
    fetched = 0
    for entry in recent:
        media_id = entry["ids"][0]
        try:
            metrics = client.insights(media_id)
        except Exception as e:  # noqa: BLE001
            if fetched == 0:
                return None, f"投稿の反響を取得できませんでした（{str(e)[:120]}）"
            continue
        store[media_id] = {"date": entry["date"], "kind": entry["kind"], "draft": entry["draft"],
                           "post_index": entry["post_index"], "permalink": entry.get("permalink", ""),
                           "metrics": metrics, "own_replies": len(entry["ids"]) - 1, "fetched": today.isoformat()}
        fetched += 1
    # 古い記録は30日で消す
    store = {k: v for k, v in store.items() if (today - _date(v["date"])).days <= 30}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return store, None


def summary(store, today, days=LOOKBACK_DAYS):
    """レポート用: 種類ごとの平均いいね・表示。"""
    rows = {}
    for v in store.values():
        if (today - _date(v["date"])).days > days:
            continue
        rows.setdefault(v["kind"], []).append(v["metrics"])
    names = {"buzz": "集客投稿", "casual": "つぶやき", "value": "役立つ投稿", "pr": "PR 投稿"}
    lines = []
    for kind, ms in rows.items():
        likes = statistics.mean(m.get("likes", 0) for m in ms)
        views = statistics.mean(m.get("views", 0) for m in ms)
        lines.append(f"- {names.get(kind, kind)}: {len(ms)}件 ／ 平均 いいね {likes:.1f}・表示 {views:.0f}")
    return lines


def pick_followup(store, today, done, min_likes):
    """反響が大きかった集客投稿を1つ選ぶ: (下書きファイル名, いいね数, 記録) or None。

    「大きい」= いいねが min_likes 以上、かつ直近の投稿のいいねの中央値の2倍以上。
    """
    recent = [v for v in store.values() if (today - _date(v["date"])).days <= LOOKBACK_DAYS]
    if not recent:
        return None
    median = statistics.median(v["metrics"].get("likes", 0) for v in recent)
    best = None
    for v in recent:
        likes = v["metrics"].get("likes", 0)
        if v["kind"] != "buzz" or v["draft"] in done or (today - _date(v["date"])).days < 1:
            continue  # 投稿した当日はまだ反響が出そろっていない
        if likes >= min_likes and likes >= 2 * median and (best is None or likes > best[1]):
            best = (v["draft"], likes, v)
    return best


def load_done(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def mark_done(path, draft_name):
    path = Path(path)
    done = load_done(path)
    if draft_name not in done:
        done.append(draft_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(done[-100:], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
