import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import stats  # noqa: E402
import threads  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self.status_code, self._data, self.text = 200, data, json.dumps(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, timeout=None):
        self.calls.append((url, params))
        if url.endswith("/me"):
            return FakeResponse({"id": "1", "username": "kotori.family"})
        if params.get("metric") == "followers_count":
            return FakeResponse({"data": [{"name": "followers_count", "total_value": {"value": 321}}]})
        return FakeResponse({"data": [
            {"name": "views", "values": [{"value": 100}, {"value": 50}]},
            {"name": "likes", "total_value": {"value": 12}},
            {"name": "clicks", "link_total_values": [{"value": 3}, {"value": 4}]},
        ]})


def test_record_day(tmp_path):
    (tmp_path / "posted").mkdir()
    (tmp_path / "posted" / "2026-10-24.json").write_text(json.dumps([{}, {}, {}]), encoding="utf-8")
    (tmp_path / "pins.json").write_text(json.dumps([{"scheduled_at": "2026-10-24T08:00+09:00"}, {"posted_at": "2026-10-23T08:00"}]))
    client = threads.ThreadsClient("t", session=FakeSession())
    row = stats.record_day(client, datetime.date(2026, 10, 24), tmp_path, tmp_path / "posted", tmp_path / "pins.json")
    assert row == {"views": 150, "likes": 12, "clicks": 7, "followers": 321, "posts": 3, "pins": 1}
    saved = json.loads((tmp_path / "daily.json").read_text(encoding="utf-8"))
    assert saved["2026-10-24"]["followers"] == 321


def test_record_earnings(tmp_path):
    stats.record_earnings("2026-10", 120, 3, 450, "初成果", stats_dir=tmp_path)
    stats.record_earnings("2026-10", 130, 4, 600, stats_dir=tmp_path)  # 同じ月は上書き
    data = json.loads((tmp_path / "earnings.json").read_text(encoding="utf-8"))
    assert data["2026-10"]["reward"] == 600 and data["2026-10"]["orders"] == 4
