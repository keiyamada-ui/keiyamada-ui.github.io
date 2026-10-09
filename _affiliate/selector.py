"""今日のテーマ選びと、商品候補の絞り込み・紹介履歴の管理。"""

import datetime
import json
from pathlib import Path


def pick_theme(pillars, today, pillar_id=None):
    """日付から今日のテーマ（柱とキーワード）を決める。

    柱は毎日1つずつ順番に回り、同じ柱の中ではキーワードが順番に回る。
    同じ日に何度実行しても同じ結果になる。
    """
    if pillar_id:
        matches = [p for p in pillars if p["id"] == pillar_id]
        if not matches:
            raise ValueError(f"config.yaml に柱 '{pillar_id}' がありません")
        pillar = matches[0]
    else:
        pillar = pillars[today.toordinal() % len(pillars)]
    rounds = today.toordinal() // len(pillars)
    query = pillar["queries"][rounds % len(pillar["queries"])]
    return pillar, query


def load_history(directory):
    """紹介履歴を読む。PR を何本 Merge しても競合しないよう、1日1ファイルで保存している。"""
    directory = Path(directory)
    if not directory.exists():
        return []
    history = []
    for path in sorted(directory.glob("*.json")):
        history.extend(json.loads(path.read_text(encoding="utf-8")))
    return history


def save_history_entry(directory, entry):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{entry['date']}.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries = [e for e in entries if (e["source"], e["id"]) != (entry["source"], entry["id"])] + [entry]
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def recently_used_ids(history, today, reuse_after_days):
    cutoff = today - datetime.timedelta(days=reuse_after_days)
    return {
        (h["source"], h["id"])
        for h in history
        if datetime.date.fromisoformat(h["date"]) > cutoff
    }


def select_candidates(items, history, today, filters):
    """レビュー数・評価で絞り込み、最近紹介した商品を除いて上位を返す。"""
    used = recently_used_ids(history, today, filters["reuse_after_days"])
    seen = set()
    picked = []
    for item in items:
        key = (item["source"], item["id"])
        if not item["id"] or not item["url"] or key in used or key in seen:
            continue
        if item["review_count"] < filters["min_review_count"]:
            continue
        if item["review_average"] < filters["min_review_average"]:
            continue
        seen.add(key)
        picked.append(item)
    picked.sort(key=lambda i: (i["review_average"] >= 4.3, i["review_count"]), reverse=True)
    return picked[: filters["max_candidates"]]
