"""時間帯ごとの成績: 投稿した時刻（30分ごと）と表示数を比べ、よく見られる時間に少しずつ寄せる。

投稿の時刻は毎日ランダムなので、続けるうちに「同じ夜でも何時ごろが見られるか」が分かってくる。
  ・data/stats/timing.json … 管理画面の「成果」に出す表と、寄せる先の時間（prefs）
  ・autopost.day_plan     … prefs があれば、その枠の時刻を 6割くらいの日はその30分に寄せる
                             （残りはこれまでどおり幅の中でランダム。人っぽさと、ほかの時間の確かめを残す）
数が少ないうちはたまたまの差が大きいので、寄せない。
"""

import datetime
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "data" / "stats" / "timing.json"
DAYS = 60
BUCKET = 30          # 30分ごとに分けて比べる
MIN_POSTS = 3        # 1つの時間帯にこれだけ投稿がたまるまでは比べない
MIN_LIFT = 1.15      # 枠の平均より15%以上よいときだけ寄せる
LEAN = 0.6           # 寄せる日の割合


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _hhmm(m):
    return f"{m // 60}:{m % 60:02d}"


def buckets(window):
    a, b = window
    return [(s, min(s + BUCKET, b)) for s in range(a, b, BUCKET)]


def rows(posted, store, today, days=DAYS):
    """自動で出した投稿の (枠, 時刻[分], 表示, いいね)。"""
    since = (today - datetime.timedelta(days=days)).isoformat()
    out = []
    for p in posted:
        if p.get("manual") or not p.get("ids") or not p.get("at") or p.get("date", "") < since:
            continue
        v = store.get(p["ids"][0])
        if not v:
            continue
        at = datetime.datetime.fromisoformat(p["at"])
        out.append((p.get("slot"), at.hour * 60 + at.minute, v["metrics"].get("views", 0), v["metrics"].get("likes", 0)))
    return out


LATE = 90  # 定期実行の遅れで、幅の終わりより遅く出た分もこの分数までは数える（最後の時間帯に入れる）


def build(posted, store, today, windows, names):
    slots = []
    for slot, window in windows.items():
        # 幅の外の投稿（前の1日5回の時期など）は数えない
        mine = [r for r in rows(posted, store, today) if r[0] == slot and window[0] <= r[1] < window[1] + LATE]
        avg = sum(r[2] for r in mine) / len(mine) if mine else 0
        cells = []
        for a, b in buckets(window):
            hit = [r for r in mine if a <= r[1] < b or (b == window[1] and r[1] >= b)]
            cells.append({"from": a, "to": b, "label": f"{_hhmm(a)}〜{_hhmm(b)}", "posts": len(hit),
                          "views": round(sum(r[2] for r in hit) / len(hit)) if hit else None,
                          "likes": round(sum(r[3] for r in hit) / len(hit), 1) if hit else None})
        enough = [c for c in cells if c["posts"] >= MIN_POSTS]
        best = max(enough, key=lambda c: c["views"], default=None) if len(enough) >= 2 else None
        prefer = best if best and avg and best["views"] >= avg * MIN_LIFT else None
        for c in cells:
            c["best"] = c is prefer
        slots.append({"slot": slot, "name": names[slot], "posts": len(mine), "views": round(avg) if mine else None,
                      "buckets": cells, "prefer": [prefer["from"], prefer["to"]] if prefer else None})
    return {"updated": today.isoformat(), "min_posts": MIN_POSTS, "slots": slots}


def update(posted, store, today, windows, names, path=PATH):
    data = build(posted, store, today, windows, names)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s in data["slots"]:
        if s["prefer"]:
            print(f"⏰ {s['name']}は {_hhmm(s['prefer'][0])}〜{_hhmm(s['prefer'][1])} がよく見られているので、少し寄せます")
    return data


def prefs(path=PATH):
    """{枠: (から, まで)}。寄せる先がなければ空。"""
    return {s["slot"]: tuple(s["prefer"]) for s in _load(path, {}).get("slots", []) if s.get("prefer")}
