import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import pins  # noqa: E402
import prompts  # noqa: E402
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

FIXTURE = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))["pins"]["pins"][0]
CONFIG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
TODAY = datetime.date(2026, 10, 25)
ITEMS = [{"id": f"shop:{n}", "name": f"商品{n}", "url": f"https://hb.afl.rakuten.co.jp/x{n}",
          "price": 1280, "review_average": 4.6, "review_count": 250, "source": "ichiba"} for n in range(3)]


def gen(system, user, schema, tier="standard"):
    assert schema is prompts.PIN_SCHEMA
    ids = [json.loads(line)["id"] for line in user.splitlines() if line.startswith("{")]
    return {"pins": [dict(FIXTURE, id=i) for i in ids]}


def test_render_makes_tall_image(tmp_path):
    out = pins.render({"headline": FIXTURE["headline"], "points": FIXTURE["points"], "facts": "★4.6"}, tmp_path / "a.png")
    assert Image.open(out).size == (pins.W, pins.H)


def test_check_pin():
    assert pins.check_pin(FIXTURE) == []
    bad = dict(FIXTURE, description="とても良い https://example.com")
    errors = pins.check_pin(bad)
    assert any("#PR" in e for e in errors) and any("URL" in e for e in errors)


def test_make_pins_writes_images_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(pins, "ROOT", tmp_path)
    made = pins.make_pins(CONFIG, TODAY, ITEMS, gen, pin_dir=tmp_path / "kotori" / "pins", manual_dir=tmp_path / "manual")
    assert len(made) == CONFIG["pinterest"]["per_day"]
    saved = json.loads((tmp_path / "manual" / "pins.json").read_text(encoding="utf-8"))
    assert [p["key"] for p in saved] == [p["key"] for p in made]
    for p in saved:
        assert (tmp_path / p["image"]).exists()
        assert p["image_url"].startswith(pins.SITE) and p["link"].startswith("https://hb.afl")
        assert p["board"] in CONFIG["pinterest"]["boards"]


def test_make_pins_disabled():
    assert pins.make_pins({**CONFIG, "pinterest": {"enabled": False}}, TODAY, ITEMS, gen) == []


def test_make_pins_twice_same_day_keeps_images(tmp_path, monkeypatch):
    monkeypatch.setattr(pins, "ROOT", tmp_path)
    kw = dict(pin_dir=tmp_path / "kotori" / "pins", manual_dir=tmp_path / "manual")
    first = pins.make_pins(CONFIG, TODAY, ITEMS[:1], gen, **kw)
    second = pins.make_pins(CONFIG, TODAY, ITEMS[1:2], gen, **kw)
    assert first[0]["image"] != second[0]["image"]
    assert len(json.loads((tmp_path / "manual" / "pins.json").read_text(encoding="utf-8"))) == 2


def test_pins_only_uses_latest_room_items(tmp_path, monkeypatch):
    import generate_drafts
    monkeypatch.setattr(generate_drafts, "MANUAL", tmp_path / "manual")
    monkeypatch.setattr(generate_drafts, "DATA", tmp_path)
    monkeypatch.setattr(pins, "ROOT", tmp_path)
    (tmp_path / "manual").mkdir()
    room = [dict(ITEMS[0], date="2026-10-24", key="a"), dict(ITEMS[1], date="2026-10-25", key="b")]
    (tmp_path / "manual" / "room.json").write_text(json.dumps(room), encoding="utf-8")
    assert generate_drafts.run_pins_only(CONFIG, TODAY, gen, dry_run=True) == 0
    saved = json.loads((tmp_path / "manual" / "pins.json").read_text(encoding="utf-8"))
    assert [p["key"] for p in saved] == [f"{TODAY}:{ITEMS[1]['id']}"]
    generate_drafts.run_pins_only(CONFIG, TODAY, gen, dry_run=True)  # 2回目は作らない
    assert len(json.loads((tmp_path / "manual" / "pins.json").read_text(encoding="utf-8"))) == 1
