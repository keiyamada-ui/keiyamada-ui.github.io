import datetime
import json

import events
import extras

TODAY = datetime.date(2026, 11, 20)


def _store(tmp_path):
    (tmp_path / "d.json").write_text(json.dumps({"posts": [{"text": "朝の支度あるある", "thread_parts": []}]}), encoding="utf-8")
    base = {"draft": "d.json", "post_index": 0, "metrics": {"likes": 3}}
    rows = {"a": dict(base, date="2026-11-15", kind="casual", permalink="A", metrics={"views": 900, "likes": 5}),
            "b": dict(base, date="2026-11-18", kind="buzz", permalink="B", metrics={"views": 2000}),  # 2日前: まだ早い
            "c": dict(base, date="2026-11-14", kind="pr", permalink="C", metrics={"views": 5000}),    # PR は作り直さない
            "d": dict(base, date="2026-11-16", kind="buzz", permalink="D", metrics={"views": 100}),
            "e": dict(base, date="2026-11-16", kind="buzz", permalink="E", metrics={"views": 120}),
            "f": dict(base, date="2026-11-10", kind="casual", permalink="F", metrics={"views": 150}),
            "g": dict(base, date="2026-11-11", kind="value", permalink="G", metrics={"views": 90})}
    return rows


def test_pick_recycle(tmp_path):
    store = _store(tmp_path)
    got = extras.pick_recycle(store, tmp_path, TODAY, [])
    assert got["permalink"] == "A" and got["text"] == "朝の支度あるある" and got["views"] == 900
    assert extras.pick_recycle(store, tmp_path, TODAY, [{"date": "2026-11-01", "permalink": "A"}]) is None
    assert extras.pick_recycle(store, tmp_path, TODAY, [{"date": "2026-11-18", "permalink": "X"}]) is None  # 3日あける
    assert "朝の支度あるある" in extras.recycle_memo(got)


def test_five_zero_days():
    assert "今日は" in events.five_zero(datetime.date(2026, 11, 10))
    assert "明日は" in events.five_zero(datetime.date(2026, 11, 29))
    assert events.five_zero(datetime.date(2026, 11, 12)) == ""
    assert events.five_zero(datetime.date(2026, 12, 31)) == ""  # 31日は対象外
