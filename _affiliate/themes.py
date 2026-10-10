"""悩み起点のテーマ: AI が月に1回考えたテーマ・参考投稿から生まれたテーマ・固定テーマを混ぜて、今日の1つを選ぶ。"""

import datetime
import hashlib
import json
from pathlib import Path


def theme_id(source, keyword):
    return hashlib.sha1(f"{source}:{keyword}".encode()).hexdigest()[:10]


def _make(origin, source, keyword, persona, category="", who="", scene="", urgency=3, months=()):
    return {"id": theme_id(source, keyword), "origin": origin, "source": source, "keyword": keyword,
            "persona": persona, "category": category, "who": who, "scene": scene,
            "urgency": int(urgency), "months": list(months)}


def fixed_themes(config):
    return [_make("固定", p["source"], q["keyword"], q["persona"], category=p["label"])
            for p in config["pillars"] for q in p["queries"]]


def bank_path(directory, day):
    return Path(directory) / f"{day:%Y-%m}.json"


def load_bank(directory, today):
    """今月と先月のテーマを読む（月初めでもストックが空にならないように）。"""
    last_month = today.replace(day=1) - datetime.timedelta(days=1)
    themes = []
    for day in (today, last_month):
        path = bank_path(directory, day)
        if path.exists():
            for t in json.loads(path.read_text(encoding="utf-8")):
                themes.append(_make("AI", t["source"], t["keyword"], t["persona"], t["category"],
                                    t["who"], t["scene"], t["urgency"], t["months"]))
    return themes


def save_bank(directory, today, themes):
    path = bank_path(directory, today)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(themes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def reference_themes(patterns):
    out = []
    for p in patterns:
        t = p.get("theme") or {}
        if t.get("keyword"):
            out.append(_make("参考投稿", t.get("source", "ichiba"), t["keyword"], t.get("persona", ""),
                             category=t.get("who", ""), who=t.get("who", ""), scene=t.get("scene", ""), urgency=4))
    return out


def rank(pool, history, today, reuse_after_days):
    """今日使うテーマの順番。緊急度・季節・参考投稿を優先し、最近使ったテーマと昨日と同じ種類は避ける。"""
    cutoff = today - datetime.timedelta(days=reuse_after_days)
    recent = [h for h in history if datetime.date.fromisoformat(h["date"]) > cutoff]
    used = {h.get("theme_id") for h in recent}
    last_source = max(recent, key=lambda h: h["date"])["source"] if recent else None

    def score(t):
        s = t["urgency"] * 2 + (3 if today.month in t["months"] else 0)
        s += 2 if t["origin"] == "参考投稿" else 0
        s -= 4 if t["source"] == last_source else 0
        # 同点のときは日付ごとに順番が変わるようにする
        jitter = int(hashlib.sha1(f"{today}:{t['id']}".encode()).hexdigest(), 16) % 1000 / 1000
        return s + jitter

    seen, ordered = set(), []
    for t in sorted(pool, key=score, reverse=True):
        if t["id"] in used or t["id"] in seen:
            continue
        seen.add(t["id"])
        ordered.append(t)
    return ordered
