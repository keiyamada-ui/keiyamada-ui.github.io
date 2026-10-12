import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import prompts  # noqa: E402
import season  # noqa: E402

DAY = datetime.date(2026, 10, 12)


def test_warm_october_avoids_winter_words(tmp_path):
    days = [{"date": f"2026-10-{d:02d}", "max": 24, "min": 16} for d in range(9, 20)]
    info = season.get(DAY, store=tmp_path, fetcher=lambda d: days)
    assert info["avg_max"] == 24 and "ダウン" in info["avoid"] and "猛暑" not in info["avoid"]
    assert "24℃" in info["note"] and "運動会" in info["note"]
    assert json.loads((tmp_path / "2026-10-12.json").read_text(encoding="utf-8"))["avg_max"] == 24
    # 同じ日は保存したものを使う（予報を取り直さない）
    assert season.get(DAY, store=tmp_path, fetcher=lambda d: 1 / 0)["avg_max"] == 24


def test_fallback_uses_normal_temperature(tmp_path):
    info = season.get(datetime.date(2026, 1, 15), store=tmp_path, fetcher=lambda d: None)
    assert info["avg_max"] == 10 and "熱中症" in info["avoid"] and "ダウン" not in info["avoid"]


def test_hits_ignore_download():
    assert season.hits("アプリをダウンロードした", season.WINTER_WORDS) == []
    assert season.hits("そろそろダウンを出す？", season.WINTER_WORDS) == ["ダウン"]


def test_checks_and_prompts_use_season(monkeypatch):
    monkeypatch.setitem(checks.SEASON, "avoid", season.WINTER_WORDS)
    monkeypatch.setitem(checks.SEASON, "avg_max", 23)
    errors = checks.check_simple_post("朝からこたつが恋しい", "つぶやき")
    assert any("こたつ" in e and "23℃" in e for e in errors)
    monkeypatch.setattr(prompts, "SEASON_NOTE", "今の季節感: テスト")
    assert "今の季節感: テスト" in prompts._persona({"name": "ことり", "persona": "親"})
