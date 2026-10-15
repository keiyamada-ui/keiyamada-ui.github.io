import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import matome  # noqa: E402

TODAY = datetime.date(2026, 11, 20)
CONFIG = {"account": {"name": "ことり", "persona": "子育て中の親"},
          "filters": {"min_review_count": 20, "min_review_average": 4.0, "reuse_after_days": 60, "max_candidates": 5},
          "scoring": {"weights": {"demand": 0.4, "rating": 0.3, "reward": 0.2, "trend": 0.1}},
          "pillars": [{"label": "入学", "source": "ichiba", "queries": [{"keyword": "上履き", "persona": "親"}]}]}


def items(n=8):
    names = ["お名前シール 防水", "学習机 木製 シンプル", "上履き 洗える 軽い", "体操服袋 キッズ", "ランドセルカバー 透明",
             "鉛筆削り 電動", "連絡袋 A4", "水筒 2way 子供"]
    return [{"source": "ichiba", "id": f"s:{i}", "name": names[i], "price": 1000 + i, "url": f"https://hb.afl.rakuten.co.jp/{i}",
             "review_count": 100 + i, "review_average": 4.5, "image": f"https://thumbnail.image.rakuten.co.jp/{i}.jpg",
             "affiliate_rate": 4.0, "shop": "s", "caption": ""} for i in range(n)]


def gen(system, user, schema, tier="standard"):
    ids = [json.loads(line)["id"] for line in user.splitlines() if line.startswith("{")]
    return {"title": "入学準備で買ってよかった物まとめ", "description": "説明" * 20, "slug": "School Prep!!",
            "intro": "名前付け、終わらない。", "closing": "早めに準備しておくと安心。",
            "items": [{"id": i, "heading": "洗っても落ちない", "body": "レビューで評判。", "good_for": "名前付けが苦手な人"}
                      for i in ids[:5]] + [{"id": "unknown", "heading": "x", "body": "x", "good_for": ""}]}


def test_writes_article(tmp_path, monkeypatch):
    monkeypatch.setattr(matome.selector, "score_items", lambda c, s: c)
    path = matome.write(CONFIG, TODAY, gen, lambda s, k: items(), history_path=tmp_path / "h.json", posts_dir=tmp_path / "_posts")
    text = path.read_text(encoding="utf-8")
    assert path.name == "2026-11-20-school-prep.md"
    assert text.startswith("---\ntitle: \"入学準備で買ってよかった物まとめ\"") and "event:" in text
    assert text.count('rel="sponsored noopener"') == 5 and "1,000円（11/20時点）" in text and "★4.5（100件）" in text
    assert "こんな人に: 名前付けが苦手な人" in text and "## まとめ" in text
    hist = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
    assert hist[0]["file"] == path.name
    # 同じテーマは60日あけて、別のテーマを選ぶ
    topics = matome.pick_topics(CONFIG, TODAY, hist)
    assert hist[0]["keyword"] not in [t[1] for t in topics]
    # 2本目は別のファイル名
    path2 = matome.write(CONFIG, TODAY, gen, lambda s, k: items(), keyword=hist[0]["keyword"],
                         history_path=tmp_path / "h.json", posts_dir=tmp_path / "_posts")
    assert path2.name == "2026-11-20-school-prep-2.md"


def test_no_article_when_too_few_items(tmp_path, monkeypatch):
    monkeypatch.setattr(matome.selector, "score_items", lambda c, s: c)
    assert matome.write(CONFIG, TODAY, gen, lambda s, k: items(2), keyword="x",
                        history_path=tmp_path / "h.json", posts_dir=tmp_path / "_posts") is None
