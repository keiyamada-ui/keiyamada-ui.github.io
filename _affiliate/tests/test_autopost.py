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

    def post_text(self, text, reply_to=None, topic_tag=None):
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise threads.ThreadsError("boom")
        self.calls.append((text, reply_to))
        self.tags = getattr(self, "tags", []) + [topic_tag]
        return f"id{len(self.calls)}"

    def permalink(self, media_id):
        return f"https://www.threads.com/@kotori.family/post/{media_id}"


@pytest.fixture
def dirs(tmp_path):
    drafts, posted = tmp_path / "drafts", tmp_path / "posted"
    drafts.mkdir()
    return drafts, posted


def write_simple(directory, kind, texts, date="2026-10-25", errors=(), tag=""):
    suffix = "-buzz" if kind == "buzz" else "-casual"
    data = {"date": date, "kind": kind, "title": "t", "errors": list(errors), "warnings": [],
            "posts": [{"type": kind, "angle": "", "text": t, "thread_parts": [], "reply_text": "", "topic_tag": tag}
                      for t in texts]}
    (directory / f"{date}{suffix}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_slot_by_time_of_day():
    at = lambda h, m=30: datetime.datetime(2026, 10, 25, h, m, tzinfo=JST)  # noqa: E731
    assert [autopost.slot_for(at(h)) for h in (9, 12, 18, 21, 23)] == [1, 1, 2, 3, 3]


def test_day_plan_is_random_within_windows_and_stable():
    plans = [autopost.day_plan(TODAY + datetime.timedelta(days=d)) for d in range(70)]
    for plan in plans:
        assert [p["slot"] for p in plan] == [1, 2, 3]
        for p in plan:
            a, b = autopost.SLOT_WINDOW[p["slot"]]
            assert a <= p["minute"] <= b
        assert not plan[1]["rest"] and sum(p["rest"] for p in plan) <= 1  # 夕方は休まない
    assert len({p[0]["time"] for p in plans}) > 10  # 毎日ちがう時刻
    rests = sum(any(p["rest"] for p in plan) for plan in plans)
    assert 3 <= rests <= 20  # だいたい週1回は2回だけの日
    assert autopost.day_plan(TODAY) == autopost.day_plan(TODAY)  # 何度呼んでも同じ


def test_due_slot_follows_the_days_plan(monkeypatch):
    at = lambda h, m=0: datetime.datetime(2026, 10, 25, h, m, tzinfo=JST)  # noqa: E731
    entry = lambda slot, h, m=0, **k: dict({"date": "2026-10-25", "slot": slot, "draft": "d", "post_index": slot,  # noqa: E731
                                             "kind": "x", "at": at(h, m).isoformat()}, **k)
    plan = [{"slot": 1, "minute": 12 * 60, "rest": False}, {"slot": 2, "minute": 18 * 60, "rest": False},
            {"slot": 3, "minute": 21 * 60, "rest": False}]
    monkeypatch.setattr(autopost, "day_plan", lambda day: plan)
    assert autopost.due_slot(at(11, 50), []) == (None, "今出す枠はありません")
    assert autopost.due_slot(at(12, 0), [])[0] == 1
    assert autopost.due_slot(at(14, 20), [])[0] == 1  # 遅れても、幅の終わりから90分までは出す
    assert autopost.due_slot(at(14, 40), []) == (None, "今出す枠はありません")
    assert autopost.due_slot(at(18, 10), [entry(1, 12, 5)])[0] == 2
    slot, reason = autopost.due_slot(at(18, 30), [entry(2, 18, 0)])
    assert slot is None
    slot, reason = autopost.due_slot(at(21, 20), [entry(2, 20, 50)])
    assert slot is None and "60分" in reason  # 続けて出さない
    assert autopost.due_slot(at(21, 55), [entry(2, 20, 50)])[0] == 3
    assert autopost.due_slot(at(7, 50), [entry(0, 7, 45, manual=True)]) == (None, "今出す枠はありません")
    # 2回だけの日: 休みの枠は出さず、2回出したら終わり
    plan[2]["rest"] = True
    assert autopost.due_slot(at(21, 30), [entry(1, 12, 0)]) == (None, "今出す枠はありません")
    assert "すべて出しました" in autopost.due_slot(at(21, 30), [entry(1, 12, 0), entry(2, 18, 0)])[1]


def test_save_plan(tmp_path):
    autopost.save_plan(TODAY, tmp_path / "s.json")
    data = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert data["date"] == "2026-10-25" and len(data["slots"]) == 3 and data["slots"][0]["window"] == "11:30〜13:00"


def test_auto_mode_is_quiet_when_nothing_is_due(monkeypatch, tmp_path):
    monkeypatch.setenv("KOTORI_THREADS_TOKEN", "t")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setattr(autopost, "due_slot", lambda now, posted: (None, "今出す枠はありません"))
    monkeypatch.setattr(autopost, "save_plan", lambda day, path: None)
    assert autopost.main([]) == 0
    out = (tmp_path / "out").read_text(encoding="utf-8")
    assert "posted<<__END__\nfalse" in out and "report<<__END__\n\n" in out


def test_mark_manual_and_undo(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-24.json", date="2026-10-24")
    now = datetime.datetime(2026, 10, 25, 9, 0, tzinfo=JST)
    assert autopost.mark_manual(drafts, posted, "2026-10-24.json", 2, now) == 0
    entry = autopost.load_posted(posted)[0]
    assert entry["manual"] and entry["kind"] == "pr" and entry["date"] == "2026-10-25"
    assert autopost.mark_manual(drafts, posted, "2026-10-24.json", 2, now) == 0  # 2回押しても1件
    assert len(autopost.load_posted(posted)) == 1
    # 手で出した PR は、自動投稿の PR の間隔にも数える
    write_draft(drafts, "2026-10-25.json")
    assert "お休み" in autopost._pick_pr(TODAY, config(), drafts, autopost.load_posted(posted), set())[2]
    assert autopost.mark_manual(drafts, posted, "2026-10-24.json", 2, now, undo=True) == 0
    assert autopost.load_posted(posted) == []
    assert autopost.mark_manual(drafts, posted, "../config.json", 0, now) == 1
    assert autopost.mark_manual(drafts, posted, "2026-10-24.json", 9, now) == 1


def test_evening_posts_value_post_with_tree_when_no_pr(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    client = FakeThreads()
    report, ok = autopost.run(2, TODAY, config(pr_posts_from=datetime.date(2026, 11, 1)), drafts, posted, client)
    assert ok and "✅" in report and len(client.calls) == 3  # 本文＋ツリー2つ
    assert client.calls[1][1] == "id1" and client.calls[2][1] == "id2"  # ツリーは順につながる
    assert autopost.load_posted(posted)[0]["post_index"] == 0


def test_night_buzz_with_topic_tag_and_casual_fallback(dirs):
    drafts, posted = dirs
    write_simple(drafts, "casual", ["朝から雨"])
    client = FakeThreads()
    report, ok = autopost.run(3, TODAY, config(), drafts, posted, client)  # 話題の投稿がない日はつぶやき
    assert ok and "つぶやき" in report
    write_simple(drafts, "buzz", ["運動会の練習で体操服が毎日ドロドロ"], tag="子育て")
    client = FakeThreads()
    assert autopost.run(3, TODAY, config(), drafts, posted, client)[1]
    assert client.calls == [("運動会の練習で体操服が毎日ドロドロ", None)] and client.tags == ["子育て"]
    assert not autopost.run(3, TODAY, config(), drafts, posted, FakeThreads())[1]  # 二重投稿しない


def test_noon_casual_and_evening_fallback(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-21.json", date="2026-10-21")
    write_simple(drafts, "casual", ["朝から雨", "夕飯なにしよう", "長袖どこ"], date="2026-10-21")
    day = datetime.date(2026, 10, 21)  # PR 投稿の開始日より前
    report, ok = autopost.run(1, day, config(), drafts, posted, FakeThreads())
    assert ok and "朝から雨" in report
    for kind in ("役立つ投稿", "役立つ投稿", "つぶやき"):  # PR のない夕方は役立つ投稿 → つぶやき
        report, ok = autopost.run(2, day, config(), drafts, posted, FakeThreads())
        assert ok and kind in report
    autopost.run(2, day, config(), drafts, posted, FakeThreads())
    report, ok = autopost.run(2, day, config(), drafts, posted, FakeThreads())
    assert not ok and "育てる期間" in report and "すべて出しました" in report


def test_followup_pr_has_priority(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    write_draft(drafts, "2026-10-23.json", date="2026-10-23")
    data = json.loads((drafts / "2026-10-23.json").read_text(encoding="utf-8"))
    data["followup"] = {"draft": "2026-10-22-buzz.json", "likes": 30}
    (drafts / "2026-10-23.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report, ok = autopost.run(2, TODAY, config(), drafts, posted, FakeThreads())
    assert ok and "🔥" in report and autopost.load_posted(posted)[0]["draft"] == "2026-10-23.json"


def test_pr_post_puts_link_in_reply(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json", gem=True)
    client = FakeThreads()
    report, ok = autopost.run(2, TODAY, config(), drafts, posted, client)
    assert ok and "💎" in report
    (body, _), (reply, parent) = client.calls
    assert "【PR】" in body and "https://" not in body
    assert "https://hb.afl.rakuten.co.jp/x" in reply and parent == "id1"


def test_pr_gates(dirs):
    drafts, posted = dirs
    kinds = lambda: [p["kind"] for p in autopost.load_posted(posted)]  # noqa: E731
    write_draft(drafts, "2026-10-20.json", date="2026-10-20")
    autopost.run(2, datetime.date(2026, 10, 20), config(), drafts, posted, FakeThreads())
    assert kinds() == ["value"]  # 育てる期間は PR の代わりに役立つ投稿
    _, reason = autopost.pick(2, datetime.date(2026, 10, 20), config(), drafts, [])[1:]
    assert reason is None
    assert "育てる期間" in autopost._pick_pr(datetime.date(2026, 10, 20), config(), drafts, [], set())[2]
    write_draft(drafts, "2026-10-25.json")
    write_draft(drafts, "2026-10-26.json", date="2026-10-26")
    autopost.run(2, TODAY, config(), drafts, posted, FakeThreads())
    assert kinds()[-1] == "pr"
    autopost.run(2, datetime.date(2026, 10, 26), config(), drafts, posted, FakeThreads())
    assert kinds()[-1] == "value"  # 間隔があいていない日はお休み
    autopost.run(2, datetime.date(2026, 10, 26), config(pr_min_interval_days=1), drafts, posted, FakeThreads())
    assert kinds()[-1] == "pr"


def test_recommended_item_goes_first_and_errors_are_skipped(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    write_draft(drafts, "2026-10-24-item-7.json", date="2026-10-24")
    autopost.run(2, TODAY, config(), drafts, posted, FakeThreads())
    assert autopost.load_posted(posted)[0]["draft"] == "2026-10-24-item-7.json"
    write_draft(drafts, "2026-10-27.json", date="2026-10-27", errors=["NG"])
    report, ok = autopost.run(2, datetime.date(2026, 10, 27), config(), drafts, posted, FakeThreads())
    assert not ok and "エラー" in report


def test_missing_draft_and_dry_run(dirs):
    drafts, posted = dirs
    assert "下書きがありません" in autopost.run(1, TODAY, config(), drafts, posted, FakeThreads())[0]
    write_draft(drafts, "2026-10-25.json")
    report, ok = autopost.run(2, TODAY, config(), drafts, posted, None, dry_run=True)
    assert not ok and "お試し" in report and autopost.load_posted(posted) == []


def test_partial_failure_is_recorded(dirs):
    drafts, posted = dirs
    write_draft(drafts, "2026-10-25.json")
    with pytest.raises(threads.ThreadsError):
        autopost.run(2, TODAY, config(pr_posts_from=datetime.date(2026, 11, 1)), drafts, posted, FakeThreads(fail_on=1))
    entry = autopost.load_posted(posted)[0]
    assert entry["partial"] and entry["ids"] == ["id1"] and entry["post_index"] == 0
    autopost.run(2, TODAY, config(pr_posts_from=datetime.date(2026, 11, 1)), drafts, posted, FakeThreads())
    assert autopost.load_posted(posted)[1]["post_index"] == 1  # 本文が出た投稿は二度出さない


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


def test_token_days_left():
    assert autopost.token_days_left(config(), TODAY) is None
    assert autopost.token_days_left(config(token_updated=datetime.date(2026, 9, 1)), TODAY) == 6
