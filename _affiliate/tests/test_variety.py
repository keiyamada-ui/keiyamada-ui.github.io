import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import learn  # noqa: E402
import variety  # noqa: E402

DAY = datetime.date(2026, 10, 16)


def test_overused_finds_repeated_phrases():
    texts = [f"『{n}円なら安い』→え、そんなに？ってなる。正直ちょっと面倒なんだよね。ツリーに書いておくね" for n in range(5)]
    texts += ["夕方の公園で、どんぐりを拾って帰った。"]
    found = variety.overused(texts)
    for word in ["え、", "ってなる", "正直", "なんだよね", "ツリーに書いておく"]:
        assert word in found
    assert variety.overused(texts[:2]) == []  # 投稿が少ないうちは判断しない


def test_recent_texts_reads_posted(tmp_path):
    (tmp_path / "posted").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "d.json").write_text(json.dumps({"posts": [{"text": "本文", "thread_parts": ["続き"]}]}), encoding="utf-8")
    (tmp_path / "posted" / "2026-10-15.json").write_text(json.dumps([{"draft": "d.json", "post_index": 0}]), encoding="utf-8")
    (tmp_path / "posted" / "2026-10-01.json").write_text(json.dumps([{"draft": "d.json", "post_index": 0}]), encoding="utf-8")
    assert variety.recent_texts(DAY, tmp_path / "posted", tmp_path / "drafts") == ["本文\n続き"]


def test_openings_change_every_day_and_by_kind():
    a, b = variety.openings(DAY), variety.openings(DAY + datetime.timedelta(days=1))
    assert len(set(a.values())) == len(a) and a != b
    assert "使わない" in variety.note(DAY, ["正直"]) and "「正直」" in variety.note(DAY, ["正直"])


def test_overused_phrases_are_rewritten_but_never_block(monkeypatch):
    monkeypatch.setattr(checks, "OVERUSED", ["正直"])
    errors = checks.check_simple_post("正直、夕方は眠い。", "つぶやき", 5, 140)
    assert errors and checks.VARIETY_TAG in errors[0]
    hard, soft = checks.soften(errors + ["NG"])
    assert hard == ["NG"] and soft == errors


def test_learning_ignores_own_replies(tmp_path):
    (tmp_path / "d.json").write_text(json.dumps({"posts": [{"type": "value", "text": "本文", "thread_parts": ["a", "b", "c"]}]}),
                                     encoding="utf-8")
    store = {"1": {"date": "2026-10-14", "kind": "value", "draft": "d.json", "post_index": 0,
                   "metrics": {"views": 50, "likes": 0, "replies": 4}}}
    row = learn.rows(store, DAY, tmp_path)[0]
    assert row["replies"] == 1  # 4件のうち3件は自分のツリー
    store["1"]["own_replies"] = 4
    assert learn.rows(store, DAY, tmp_path)[0]["replies"] == 0


def test_rewrites_note(tmp_path):
    import rewrites
    path = tmp_path / "r.json"
    assert rewrites.note(path) == ""
    rewrites.add("rewrite", "2枚3180円で送料無料！", "2枚で3,180円、送料0円。『え、〜？』ってなった。", "pr", "驚かない", path=path)
    rewrites.add("sample", "ロンT1枚1590円！", path=path)
    rewrites.add("good", before="いい投稿", path=path)
    rewrites.add("bad", before="ダメな投稿", note="長い", path=path)
    rewrites.add("good", before="ダメな投稿", path=path)  # 押し直すと前のは消える
    text = rewrites.note(path)
    assert "直した後: 2枚3180円で送料無料！" in text and "ロンT1枚1590円！" in text
    assert "ダメな投稿" in text.split("「良い」")[1] and "「ダメ」" not in text
    entries = rewrites.load(path)
    assert [e["id"] for e in entries] == [1, 2, 3, 5]
    assert rewrites.delete(1, path=path) == 1 and len(rewrites.load(path)) == 3
    import pytest
    with pytest.raises(ValueError):
        rewrites.add("rewrite", "", "x", path=path)


def test_events_calendar():
    import events
    names = lambda d: [e["name"] for e in events.active(datetime.date.fromisoformat(d))]  # noqa: E731
    assert "クリスマス" in names("2026-11-25") and "クリスマス" not in names("2026-10-01")
    assert "入学準備" in names("2027-01-10")  # 年をまたぐ行事
    assert "ハロウィン" in names("2026-10-16")
    assert "あと" in events.note(datetime.date(2026, 10, 16))
    ts = events.themes(datetime.date(2026, 12, 1))
    assert ts and all(t["origin"] == "行事" and t["urgency"] == 5 for t in ts)


def test_weekly_report(tmp_path):
    import weekly
    (tmp_path / "stats").mkdir()
    (tmp_path / "insights").mkdir()
    (tmp_path / "stats" / "daily.json").write_text(json.dumps({
        "2026-10-08": {"followers": 5}, "2026-10-10": {"views": 100, "likes": 2, "followers": 7, "posts": 5},
        "2026-10-11": {"views": 50, "clicks": 1, "followers": 8}}), encoding="utf-8")
    (tmp_path / "insights" / "latest.json").write_text(json.dumps({"1": {"date": "2026-10-10", "draft": "d.json", "post_index": 0,
        "metrics": {"views": 300, "likes": 1}, "permalink": "p"}}), encoding="utf-8")
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "d.json").write_text(json.dumps({"posts": [{"text": "靴下を片方だけ"}]}), encoding="utf-8")
    r = weekly.build(datetime.date(2026, 10, 11), data=tmp_path, drafts=drafts)
    assert r["views"] == 150 and r["likes"] == 2 and r["followers"] == 8 and r["followers_diff"] == 3
    assert r["best"]["text"] == "靴下を片方だけ"
    text = weekly.message(r)
    assert "フォロワー +3" in text and "靴下" in text
