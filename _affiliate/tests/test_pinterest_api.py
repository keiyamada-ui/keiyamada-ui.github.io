import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import pinterest_api  # noqa: E402

JST = pinterest_api.JST


def _pins(tmp_path):
    data = [{"key": f"k{i}", "date": f"2026-10-2{i}", "title": "t", "description": "d #PR", "board": "b",
             "link": "https://hb.afl/x", "image_url": "https://x/1.png"} for i in range(3)]
    data[0]["posted_by_hand"] = True
    (tmp_path / "pins.json").write_text(json.dumps(data), encoding="utf-8")


def test_post_due_posts_one_per_slot(tmp_path):
    _pins(tmp_path)
    made = []
    create = lambda p: made.append(p["key"]) or f"id{len(made)}"  # noqa: E731
    morning = datetime.datetime(2026, 10, 25, 9, 0, tzinfo=JST)
    assert pinterest_api.post_due(morning, tmp_path, tok={"x": 1}, create=create)["key"] == "k1"
    assert pinterest_api.post_due(morning, tmp_path, tok={"x": 1}, create=create) is None  # 同じ枠では1枚だけ
    night = morning.replace(hour=21)
    assert pinterest_api.post_due(night, tmp_path, tok={"x": 1}, create=create)["key"] == "k2"
    saved = json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))
    assert saved[1]["pin_url"] == "https://www.pinterest.com/pin/id1/" and saved[1]["slot"] == "2026-10-25T08:00+09:00"


def test_post_due_before_first_slot_does_nothing(tmp_path):
    _pins(tmp_path)
    early = datetime.datetime(2026, 10, 25, 7, 0, tzinfo=JST)
    assert pinterest_api.post_due(early, tmp_path, tok={"x": 1}, create=lambda p: "id") is None


def test_post_due_records_errors(tmp_path):
    _pins(tmp_path)

    def boom(p):
        raise pinterest_api.PinterestError("だめ")
    pin = pinterest_api.post_due(datetime.datetime(2026, 10, 25, 9, 0, tzinfo=JST), tmp_path, tok={"x": 1}, create=boom)
    assert pin["tries"] == 1 and "だめ" in pin["error"] and "pin_id" not in pin


def test_not_connected_is_quiet(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTORI_STORE_KEY", raising=False)
    assert pinterest_api.main(["post-due"]) == 0
