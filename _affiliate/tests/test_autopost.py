import datetime
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import autopost  # noqa: E402
import threads  # noqa: E402

FIXTURES = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))
TODAY = datetime.date(2026, 10, 25)
JST = autopost.JST


def config(**over):
    auto = {"enabled": True, "pr_posts_from": datetime.date(2026, 10, 24), "pr_min_interval_days": 2}
    auto.update(over)
    return {"auto_post": auto}


def write_draft(directory, name, date="2026-10-25", errors=(), gem=False):
    posts = [dict(p, reply_text=p["reply_text"].replace("{{LINK}}", "https://hb.afl.rakuten.co.jp/x"))
             for p in FIXTURES["write"]["posts"]]
    data = {"date": date, "title": "t", "kind": "daily", "errors": list(errors), "warnings": [],
            "chosen": {"source": "ichiba", "id": "a", "name": "n", "url": "u", "is_hidden_gem": gem},
            "posts": posts, "room_comment": "c #PR"}
    (directory / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class FakeThreads:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def post_text(self, text, reply_to=None):
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise threads.ThreadsError("boom")
        self.calls.append((text, reply_to))
        return f"id{len(self.calls)}"

    def permalink(self, media_id):
        return f"https://www.threads.com/@kotori.family/post/{media_id}"


@pytest.fixture
def dirs(tmp_path):
    drafts, posted = tmp_path / "drafts", tmp_path / "posted"
    drafts.mkdir()
    return drafts, posted


def test_slot_by_time_of_day():
    at = lambda h: datetime.datetime(2026, 10, 25, h, 30, tzinfo=JST)  # noqa: E731
    assert [autopost.slot_for(at(h)) for h in (7, 10, 12, 16, 20, 23)] == [1, 1, 2, 2, 3, 3]


def test_morning_and_noon_post_value_posts_with_tree(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    client = FakeThreads()
    report, ok = autopost.run(1, TODAY, config(), drafts, posted, client)
    assert ok and "✅" in report and len(client.calls) == 3  # 本文＋ツリー2つ
    assert client.calls[1][1] == "id1" and client.calls[2][1] == "id2"  # ツリーは順につながる
    report, ok = autopost.run(1, TODAY, config(), drafts, posted, FakeThreads())
    assert not ok and "すでに出しています" in report  # 二重投稿しない
    client = FakeThreads()
    assert autopost.run(2, TODAY, config(), drafts, posted, client)[1] and len(client.calls) == 1


def test_pr_post_puts_link_in_reply(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json", gem=True)
    client = FakeThreads()
    report, ok = autopost.run(3, TODAY, config(), drafts, posted, client)
    assert ok and "💎" in report
    (body, _), (reply, parent) = client.calls
    assert "【PR】" in body and "https://" not in body
    assert "https://hb.afl.rakuten.co.jp/x" in reply and parent == "id1"


def test_pr_gates(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-20.json", date="2026-10-20")
    report, ok = autopost.run(3, datetime.date(2026, 10, 20), config(), drafts, posted, FakeThreads())
    assert not ok and "育てる期間" in report
    write_draft(drafts, "2026-10-25.json")
    write_draft(drafts, "2026-10-26.json", date="2026-10-26")
    assert autopost.run(3, TODAY, config(), drafts, posted, FakeThreads())[1]
    report, ok = autopost.run(3, datetime.date(2026, 10, 26), config(), drafts, posted, FakeThreads())
    assert not ok and "お休み" in report
    assert autopost.run(3, datetime.date(2026, 10, 26), config(pr_min_interval_days=1), drafts, posted,
                        FakeThreads())[1]


def test_recommended_item_goes_first_and_errors_are_skipped(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    write_draft(drafts, "2026-10-24-item-7.json", date="2026-10-24")
    autopost.run(3, TODAY, config(), drafts, posted, FakeThreads())
    assert autopost.load_posted(posted)[0]["draft"] == "2026-10-24-item-7.json"
    write_draft(drafts, "2026-10-27.json", date="2026-10-27", errors=["NG"])
    report, ok = autopost.run(1, datetime.date(2026, 10, 27), config(), drafts, posted, FakeThreads())
    assert not ok and "エラー" in report


def test_noon_catches_up_on_missed_morning(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    autopost.run(2, TODAY, config(), drafts, posted, FakeThreads())
    autopost.run(2, TODAY, config(), drafts, posted, FakeThreads())
    assert [p["post_index"] for p in autopost.load_posted(posted)] == [0, 1]


def test_missing_draft_and_dry_run(dirs):
    drafts, posted = dirs
    assert "まだありません" in autopost.run(1, TODAY, config(), drafts, posted, FakeThreads())[0]
    write_draft(drafts, "2026-10-25.json")
    report, ok = autopost.run(1, TODAY, config(), drafts, posted, None, dry_run=True)
    assert not ok and "お試し" in report and autopost.load_posted(posted) == []


def test_partial_failure_is_recorded(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    with pytest.raises(threads.ThreadsError):
        autopost.run(1, TODAY, config(), drafts, posted, FakeThreads(fail_on=1))
    entry = autopost.load_posted(posted)[0]
    assert entry["partial"] and entry["ids"] == ["id1"]
    assert not autopost.run(1, TODAY, config(), drafts, posted, FakeThreads())[1]


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data


class Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params, timeout):
        self.calls.append((method, url, dict(params)))
        if url.endswith("/me"):
            return Resp(200, {"id": "42", "username": "kotori.family"})
        if url.endswith("/threads"):
            return Resp(200, {"id": "container1"})
        return Resp(200, {"id": "media1"})


def test_threads_client_two_step_publish(monkeypatch):
    monkeypatch.setattr(threads.time, "sleep", lambda s: None)
    session = Session()
    client = threads.ThreadsClient("tok", session=session)
    assert client.post_text("こんにちは", reply_to="p1") == "media1"
    _, create_url, create = session.calls[1]
    assert create_url.endswith("/42/threads") and create["reply_to_id"] == "p1" and create["media_type"] == "TEXT"
    _, publish_url, publish = session.calls[2]
    assert publish_url.endswith("/42/threads_publish") and publish["creation_id"] == "container1"
    with pytest.raises(threads.ThreadsError):
        threads.ThreadsClient("")


def test_token_age_warning():
    assert "token_updated" in autopost.token_age_warning(config(), TODAY)
    assert autopost.token_age_warning(config(token_updated=datetime.date(2026, 10, 1)), TODAY) is None
    warning = autopost.token_age_warning(config(token_updated=datetime.date(2026, 9, 1)), TODAY)
    assert "54 日" in warning and "あと約 6 日" in warning


def test_no_token_is_a_quiet_skip(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTORI_THREADS_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    assert autopost.main(["--slot", "1"]) == 0
    assert "まだ登録されていません" in (tmp_path / "out").read_text(encoding="utf-8")
