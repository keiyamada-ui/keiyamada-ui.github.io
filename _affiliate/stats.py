"""成果の記録（毎日の反響と、毎月の売上）。将来の実績・アプリの宣伝にも使えるように、日ごとに残しておく。

    data/stats/daily.json     日付 → Threads の表示・いいね・リンクのクリック・フォロワー、投稿数、ピンの数
    data/stats/earnings.json  月（YYYY-MM）→ 楽天アフィリエイトのクリック・件数・報酬（管理画面から入力）

    python _affiliate/stats.py earnings 2026-10 --clicks 120 --orders 3 --reward 450 --memo "..."
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATS = HERE / "data" / "stats"
JST = datetime.timezone(datetime.timedelta(hours=9))


def _load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _counts(day, posted_dir, pins_path):
    """その日に出した Threads の投稿の数と、公開した（予定の）ピンの数。"""
    path = Path(posted_dir) / f"{day}.json"
    posts = len(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else 0
    pins = _load(Path(pins_path), [])
    n_pins = sum(1 for p in pins if (p.get("posted_at") or p.get("scheduled_at") or "")[:10] == day)
    return posts, n_pins


def record_day(client, day, stats_dir=STATS, posted_dir=HERE / "data" / "posted", pins_path=HERE / "manual" / "pins.json"):
    """day（日本時間の1日）の反響を記録する。client が None なら数だけ記録する。"""
    start = datetime.datetime.combine(day, datetime.time(0, 0), JST)
    row = {}
    if client is not None:
        row.update(client.account_insights(start.timestamp(), (start + datetime.timedelta(days=1)).timestamp()))
        row["followers"] = client.followers()
    row["posts"], row["pins"] = _counts(day.isoformat(), posted_dir, pins_path)
    path = Path(stats_dir) / "daily.json"
    daily = _load(path, {})
    daily[day.isoformat()] = {**daily.get(day.isoformat(), {}), **row}
    _save(path, daily)
    return row


def record_earnings(month, clicks, orders, reward, memo="", stats_dir=STATS):
    datetime.date.fromisoformat(month + "-01")  # 形の確認
    path = Path(stats_dir) / "earnings.json"
    data = _load(path, {})
    data[month] = {"clicks": int(clicks), "orders": int(orders), "reward": int(reward), "memo": memo[:200],
                   "updated": datetime.datetime.now(JST).isoformat(timespec="minutes")}
    _save(path, data)
    print(f"✅ {month} の成果を記録しました（報酬 {int(reward):,}円・{int(orders)}件・クリック {int(clicks)}）")
    return data[month]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["earnings"])
    ap.add_argument("month")
    ap.add_argument("--clicks", type=int, default=0)
    ap.add_argument("--orders", type=int, default=0)
    ap.add_argument("--reward", type=int, default=0)
    ap.add_argument("--memo", default="")
    a = ap.parse_args(argv)
    record_earnings(a.month, a.clicks, a.orders, a.reward, a.memo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
