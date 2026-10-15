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
