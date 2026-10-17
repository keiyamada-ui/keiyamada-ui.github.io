import datetime

import experiences as ex
import generate_drafts as gd
import prompts
import themes

TODAY = datetime.date(2026, 10, 20)


def test_add_edit_delete(tmp_path):
    path = tmp_path / "e.json"
    a = ex.add("長男の水筒を2wayにしたら洗うのが楽になった", "水筒 2way", path, TODAY)
    b = ex.add("朝、体操服を忘れて走って取りに帰った", path=path, today=TODAY)
    assert (a, b) == (1, 2)
    ex.load(path)[0]["themed"] = "x"
    assert ex.edit(1, "直した", "水筒", path) and ex.load(path)[0]["text"] == "直した"
    assert ex.delete(2, path) == 1 and [e["id"] for e in ex.load(path)] == [1]
    assert ex.add("次", path=path, today=TODAY) == 2


def _e(i, text, item="", uses=()):
    return {"id": i, "text": text, "item": item, "date": "2026-10-01", "uses": list(uses), "themed": ""}


def test_candidates_by_topic_and_reuse_limits():
    entries = [_e(1, "水筒のパッキンが1個少なくて洗うのが楽", "水筒 2way"),
               _e(2, "体操服を忘れて取りに帰った"),
               _e(3, "水筒の話", uses=["2026-10-15"]),                      # 2週間たっていない
               _e(4, "水筒の話2", uses=["2026-08-01", "2026-09-01", "2026-09-20"])]  # 3回使った
    assert [e["id"] for e in ex.candidates(entries, TODAY, "子供 水筒 2way 洗いやすい")] == [1]
    assert [e["id"] for e in ex.candidates(entries, TODAY, "ランドセル 軽量")] == []
    assert [e["id"] for e in ex.candidates(entries, TODAY)] == [2, 1]
    ex.mark_used(entries, [1], TODAY)
    assert entries[0]["uses"] == ["2026-10-20"] and not ex.usable(entries[0], TODAY)


def test_item_themes_only_once():
    entries = [_e(1, "よかった", "水筒 2way"), _e(2, "メモだけ"), dict(_e(3, "前に探した", "マグ"), themed="2026-10-01")]
    got = ex.item_themes(entries, TODAY, themes._make)
    assert [(e["id"], t["keyword"], t["origin"]) for e, t in got] == [(1, "水筒 2way", "体験")]


def test_write_posts_keeps_only_offered_ids(monkeypatch):
    memos = [_e(5, "水筒を2wayにしたら洗うのが楽")]
    seen = {}

    def fake(system, user, schema, tier=None):
        seen["user"] = user
        out = gd.FakeGenerator()(system, user, schema, tier)
        out["experience_ids"] = [5, 99]
        return out
    theme = themes._make("固定", "ichiba", "水筒", "")
    analysis = gd.FakeGenerator().fixtures["analysis"]
    chosen = {"name": "水筒", "url": "https://example.com", "price": 1000, "review_count": 10, "review_average": 4.5,
              "id": "a:1", "source": "ichiba"}
    monkeypatch.setattr(prompts, "_candidate_line", lambda c: "水筒")
    config = gd.load_config()
    result, _, _ = gd.write_posts(config, theme, chosen, analysis, [], TODAY, fake, memos=memos)
    assert result["experience_ids"] == [5]
    assert "[5] 水筒を2wayにしたら洗うのが楽" in seen["user"]
