import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import learn  # noqa: E402
import prompts  # noqa: E402
import yaml  # noqa: E402

CONFIG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
TODAY = datetime.date(2026, 10, 26)
RESULT = {"summary": "問いかけで終わる短い投稿ほど返信が多い", "lessons": [
    {"title": "問いかけで終わる", "do": "最後を答えやすい問いかけにする", "avoid": "言い切って終わる", "why": "返信が平均3倍", "applies_to": "つぶやき"}]}


def _store(tmp_path, n):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    store = {}
    for i in range(n):
        name = f"2026-10-{10 + i:02d}-casual.json"
        (drafts / name).write_text(json.dumps({"posts": [{"text": f"投稿{i} " + "あ" * i}]}), encoding="utf-8")
        store[f"id{i}"] = {"date": f"2026-10-{10 + i:02d}", "kind": "casual", "draft": name, "post_index": 0,
                           "metrics": {"views": 100 * i, "likes": i, "replies": i % 3}}
    return store, drafts


def test_learn_needs_enough_posts(tmp_path):
    store, drafts = _store(tmp_path, 5)
    assert learn.learn(CONFIG, TODAY, store, lambda *a, **k: RESULT, drafts, path=tmp_path / "l.json") is None


def test_learn_compares_top_and_bottom_and_saves(tmp_path):
    store, drafts = _store(tmp_path, 14)
    seen = {}

    def gen(system, user, schema, tier="standard"):
        seen.update(user=user, tier=tier, schema=schema)
        return RESULT
    saved = learn.learn(CONFIG, TODAY, store, gen, drafts, {"id13": "20:12"}, path=tmp_path / "l.json")
    assert saved["posts"] == 14 and seen["tier"] == "important" and seen["schema"] is prompts.LEARN_SCHEMA
    top_part, bottom_part = seen["user"].split("## 反響が小さかった投稿")
    assert "投稿13" in top_part and "20:12" in top_part and "投稿0" in bottom_part
    note = learn.note(tmp_path / "l.json")
    assert "問いかけで終わる短い投稿" in note and "[つぶやき]" in note
    # 1週間たつまでは学び直さない
    assert learn.learn(CONFIG, TODAY + datetime.timedelta(days=3), store, gen, drafts, path=tmp_path / "l.json") is None
    assert learn.learn(CONFIG, TODAY + datetime.timedelta(days=7), store, gen, drafts, path=tmp_path / "l.json")


def test_note_empty_without_file(tmp_path):
    assert learn.note(tmp_path / "none.json") == ""
