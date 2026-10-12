import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import prompts  # noqa: E402
import rulebook  # noqa: E402
import yaml  # noqa: E402

CONFIG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
TODAY = datetime.date(2026, 10, 25)
TIPS = [{"kind": "tips", "rules_for_us": [f"コツ{i}のルール" for i in range(6)]} for _ in range(3)]
LEARNED = {"lessons": [{"applies_to": "つぶやき", "do": "短く書く", "avoid": "長文"}]}


def gen_factory(calls):
    def gen(system, user, schema, tier="standard"):
        calls.append(user)
        assert schema is rulebook.SCHEMA and tier == "important"
        return {"rules": [{"rule": f"ルール{i}", "applies_to": "すべて", "source": "考え方・コツ"} for i in range(12)],
                "dropped": [{"rule": "長文にする", "reason": "自分の投稿の結果とぶつかる"}]}
    return gen


def test_rulebook_caps_and_caches(tmp_path):
    calls = []
    book = rulebook.ensure(CONFIG, TODAY, TIPS, LEARNED, gen_factory(calls), path=tmp_path / "r.json")
    assert len(book["rules"]) == rulebook.MAX_RULES and book["materials"] == 19
    assert "自分の投稿の結果" in calls[0] and "考え方・コツ" in calls[0]
    # 材料が同じなら作り直さない
    rulebook.ensure(CONFIG, TODAY + datetime.timedelta(days=2), TIPS, LEARNED, gen_factory(calls), path=tmp_path / "r.json")
    assert len(calls) == 1
    # 材料が変わったら作り直す
    rulebook.ensure(CONFIG, TODAY, TIPS + [{"kind": "tips", "rules_for_us": ["新しいコツ"]}], LEARNED, gen_factory(calls), path=tmp_path / "r.json")
    assert len(calls) == 2
    note = rulebook.note(json.loads((tmp_path / "r.json").read_text(encoding="utf-8")))
    assert note.count("\n") == rulebook.MAX_RULES and "1. [すべて] ルール0" in note


def test_no_materials_no_rulebook(tmp_path):
    assert rulebook.ensure(CONFIG, TODAY, [], None, gen_factory([]), path=tmp_path / "r.json") is None


def test_tips_not_repeated_as_patterns():
    pats = [{"kind": "tips", "hook_type": "考え方・コツ", "reusable_pattern": "コツの中身"},
            {"hook_type": "問いかけ型", "reusable_pattern": "問いで終わる"}]
    _, user = prompts.buzz_write_messages(CONFIG["account"], TODAY, "メモ", pats)
    assert "問いで終わる" in user and "コツの中身" not in user
