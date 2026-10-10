"""商品候補の絞り込み・点数付け（需要・評価・報酬・勢い）・発掘枠・紹介履歴。"""

import datetime
import json
import math
from pathlib import Path


# ---------- 紹介履歴（PR を何本 Merge しても競合しないよう、1日1ファイル） ----------

def load_history(directory):
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


def recently_used(history, today, days, key):
    cutoff = today - datetime.timedelta(days=days)
    return {key(h) for h in history if datetime.date.fromisoformat(h["date"]) > cutoff}


# ---------- 勢い（レビュー数の伸び）を測るための記録 ----------

def _key(item):
    return f"{item['source']}:{item['id']}"


def save_snapshot(directory, today, items):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{today.isoformat()}.json"
    snap = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    snap.update({_key(i): i["review_count"] for i in items if i.get("id")})
    path.write_text(json.dumps(snap, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def trends(directory, today, items, min_days=3):
    """3日以上前の記録と比べて、1日あたり何%レビューが増えたか。記録がなければ載せない。"""
    directory = Path(directory)
    if not directory.exists():
        return {}
    past = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        day = datetime.date.fromisoformat(path.stem)
        if (today - day).days >= min_days:
            past.append((day, json.loads(path.read_text(encoding="utf-8"))))
    out = {}
    for item in items:
        for day, snap in past:
            if _key(item) in snap:
                before = snap[_key(item)]
                out[_key(item)] = (item["review_count"] - before) / max(before, 10) / (today - day).days
                break
    return out


# ---------- 絞り込みと点数付け ----------

def is_hidden_gem_day(today, gem_cfg):
    return today.weekday() in gem_cfg.get("weekdays", [])


def filter_items(items, history, today, filters, gem_cfg=None):
    used = recently_used(history, today, filters["reuse_after_days"], lambda h: (h["source"], h["id"]))
    seen, out = set(), []
    for item in items:
        key = (item["source"], item["id"])
        if not item["id"] or not item["url"] or key in used or key in seen:
            continue
        if gem_cfg:
            ok = (item["review_average"] >= gem_cfg["min_review_average"]
                  and gem_cfg["min_review_count"] <= item["review_count"] <= gem_cfg["max_review_count"])
        else:
            ok = (item["review_count"] >= filters["min_review_count"]
                  and item["review_average"] >= filters["min_review_average"])
        if ok:
            seen.add(key)
            out.append(dict(item, is_hidden_gem=bool(gem_cfg)))
    return out


def _normalize(values):
    lo, hi = min(values), max(values)
    return [1.0 if hi == lo else (v - lo) / (hi - lo) for v in values]


def score_items(items, scoring, trend_map=None, ranks=None):
    """需要・評価・報酬・勢いを0〜1に揃えて重み付けし、0〜100点にする。"""
    if not items:
        return []
    trend_map, ranks = trend_map or {}, ranks or {}
    w = scoring["weights"]
    rates = scoring["default_affiliate_rate"]
    for item in items:
        rate = item.get("affiliate_rate") or rates.get(item["source"], 1.0)
        item["affiliate_rate"] = rate
        item["commission"] = round(item["price"] * rate / 100)
        rank = ranks.get(item["id"])
        item["ranking"] = rank
        # ランキング入りしていれば、順位が高いほど需要を上乗せする
        item["_demand"] = math.log1p(item["review_count"]) + (3 - min(rank, 30) / 10 if rank else 0)
    demand = _normalize([i["_demand"] for i in items])
    quality = [min(max((i["review_average"] - 3.5) / 1.5, 0), 1) for i in items]
    profit = _normalize([math.log1p(i["commission"]) for i in items])
    trend_raw = [trend_map.get(_key(i), 0.0) for i in items]
    trend = _normalize(trend_raw) if any(trend_raw) else [0.0] * len(items)
    for n, item in enumerate(items):
        parts = {"需要": demand[n] * w["demand"], "評価": quality[n] * w["quality"],
                 "報酬": profit[n] * w["profit"], "勢い": trend[n] * w["trend"]}
        item["score"] = round(sum(parts.values()) * 100)
        item["score_detail"] = {k: round(v * 100) for k, v in parts.items()}
        item["trend_per_day"] = trend_map.get(_key(item))
        del item["_demand"]
    return sorted(items, key=lambda i: i["score"], reverse=True)
