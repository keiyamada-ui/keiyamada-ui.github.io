import datetime

import autopost
import timing

TODAY = datetime.date(2026, 11, 30)
WIN = {3: (20 * 60 + 30, 22 * 60)}
NAMES = {3: "夜"}


def _data(times_views):
    posted, store = [], {}
    for i, (hhmm, views) in enumerate(times_views):
        posted.append({"date": "2026-11-20", "slot": 3, "ids": [str(i)], "at": f"2026-11-20T{hhmm}+09:00"})
        store[str(i)] = {"metrics": {"views": views, "likes": 1}}
    return posted, store


def test_prefers_clearly_better_half_hour():
    posted, store = _data([("20:40", 100)] * 3 + [("21:10", 300)] * 3 + [("21:50", 100)] * 2 + [("23:40", 999)])
    s = timing.build(posted, store, TODAY, WIN, NAMES)["slots"][0]
    assert s["posts"] == 8  # 23:40 は幅の外（遅れの許容も超える）なので数えない
    assert s["prefer"] == [21 * 60, 21 * 60 + 30]
    assert [c["posts"] for c in s["buckets"]] == [3, 3, 2]


def test_no_preference_with_few_posts_or_small_gap():
    posted, store = _data([("20:40", 100)] * 2 + [("21:10", 300)] * 3)
    assert timing.build(posted, store, TODAY, WIN, NAMES)["slots"][0]["prefer"] is None
    posted, store = _data([("20:40", 100)] * 3 + [("21:10", 105)] * 3)
    assert timing.build(posted, store, TODAY, WIN, NAMES)["slots"][0]["prefer"] is None


def test_day_plan_leans_to_preferred_window_on_most_days():
    days = [TODAY + datetime.timedelta(days=d) for d in range(200)]
    inside = sum(21 * 60 <= autopost.day_plan(d, {3: (21 * 60, 21 * 60 + 30)})[2]["minute"] <= 21 * 60 + 30 for d in days)
    assert 0.6 < inside / 200 < 0.85  # 6割は寄せる + 残りの日もたまたま入る。全部ではない
    plain = [autopost.day_plan(d, {}) for d in days[:5]]
    assert plain == [autopost.day_plan(d, {}) for d in days[:5]]
    # 寄せても、休む枠や昼・夕方の時刻は変わらない
    for d in days[:30]:
        a, b = autopost.day_plan(d, {}), autopost.day_plan(d, {3: (21 * 60, 21 * 60 + 30)})
        assert [p["rest"] for p in a] == [p["rest"] for p in b] and a[0]["minute"] == b[0]["minute"]
