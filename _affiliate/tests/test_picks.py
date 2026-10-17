import json

import picks


def _setup(tmp_path, entries, chosen):
    (tmp_path / "posted").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "posted" / "2026-10-12.json").write_text(json.dumps(entries), encoding="utf-8")
    for name, item in chosen.items():
        (tmp_path / "drafts" / name).write_text(json.dumps({"chosen": item, "posts": []}), encoding="utf-8")
    return tmp_path / "posted", tmp_path / "drafts", tmp_path / "picks.json"


def _pr(draft, at, link=""):
    return {"date": at[:10], "draft": draft, "post_index": 2, "kind": "pr", "at": at, "permalink": link}


def test_numbers_are_kept_and_removed_items_leave_gap(tmp_path):
    items = {"a.json": {"id": "s:1", "name": "【送料無料】木製 ラック キッズ", "url": "u1"},
             "b.json": {"id": "s:2", "name": "水筒", "url": "u2", "image": "img2"}}
    posted, drafts, out = _setup(tmp_path, [_pr("a.json", "2026-10-12T18:00"), _pr("b.json", "2026-10-13T18:00", "t2"),
                                           {"kind": "buzz", "draft": "x.json", "at": "2026-10-13T12:00"}], items)
    got = picks.build(posted, drafts, out, room=tmp_path / "none.json")
    assert [(p["no"], p["name"], p["image"], p["threads"]) for p in got] == [(1, "木製 ラック キッズ", "", ""), (2, "水筒", "img2", "t2")]
    assert picks.number_for("s:2", out) == 2 and picks.number_for("s:9", out) == 3
    # 1つ目を取り消しても、2つ目の番号は変わらない
    (posted / "2026-10-12.json").write_text(json.dumps([_pr("b.json", "2026-10-13T18:00", "t2")]), encoding="utf-8")
    assert [p["no"] for p in picks.build(posted, drafts, out, room=tmp_path / "none.json")] == [2]


def test_image_from_room_list(tmp_path):
    posted, drafts, out = _setup(tmp_path, [_pr("a.json", "2026-10-12T18:00")], {"a.json": {"id": "s:1", "name": "x", "url": "u"}})
    (tmp_path / "room.json").write_text(json.dumps([{"id": "s:1", "image": "img"}]), encoding="utf-8")
    assert picks.build(posted, drafts, out, room=tmp_path / "room.json")[0]["image"] == "img"


def test_with_number_respects_threads_limit(tmp_path):
    out = tmp_path / "picks.json"
    out.write_text(json.dumps([{"no": 4, "id": "s:1"}]), encoding="utf-8")
    assert picks.with_number("リンクです", "s:1", out).endswith("一覧【4】にも載せています")
    long = "あ" * 480
    assert picks.with_number(long, "s:1", out) == long
