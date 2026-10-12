import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import autopost  # noqa: E402
import illust  # noqa: E402
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

CONFIG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
CONFIG = {**CONFIG, "illust": {**CONFIG["illust"], "enabled": True}}  # 本番では保留中でも、仕組みは確かめる
TODAY = datetime.date(2026, 10, 25)


def _drafts(tmp_path):
    d = tmp_path / "drafts"
    d.mkdir()
    (d / "2026-10-25-casual.json").write_text(json.dumps({"posts": [{"type": "casual", "text": "朝の支度でバタバタ"}]}), encoding="utf-8")
    (d / "2026-10-25.json").write_text(json.dumps({"errors": [], "posts": [
        {"type": "value", "text": "役立つ話"}, {"type": "pr", "text": "PR の話"}]}), encoding="utf-8")
    return d


def _posted(n, image_at=None):
    out = [{"date": "2026-10-2x", "at": f"2026-10-20T{h:02d}:00", "slot": 1} for h in range(n)]
    if image_at is not None:
        out[image_at]["image"] = True
    return out


def test_due_counts_posts_since_last_image():
    state = {"every": 8}
    assert illust.due(_posted(6), state, TODAY)                   # 6 + 今日の分2 = 8
    assert not illust.due(_posted(9, image_at=4), state, TODAY)   # 画像のあと4本 + 2 = 6
    assert not illust.due(_posted(20), {"every": 8, "last_made": "2026-10-25"}, TODAY)  # 今日はもう作った


def test_candidates_exclude_pr(tmp_path):
    refs = [c["ref"] for c in illust.candidates(_drafts(tmp_path), TODAY)]
    assert refs == ["2026-10-25-casual.json#0", "2026-10-25.json#0"]


def test_maybe_make_attaches_image(tmp_path):
    d = _drafts(tmp_path)
    gen = lambda s, u, schema, tier="standard": {"ref": "2026-10-25-casual.json#0", "scene": "birds packing a school bag", "why": "あるある"}  # noqa: E731
    calls = []

    def checker(img, scene):
        calls.append(scene)
        return len(calls) > 1, ["文字が入っている"]  # 1回目は不合格 → 描き直し
    ref = illust.maybe_make(CONFIG, TODAY, gen, d, _posted(10), state_path=tmp_path / "s.json", out_dir=tmp_path / "out",
                            drawer=lambda scene, models: Image.new("RGB", (1200, 1200), (250, 240, 220)), checker=checker)
    assert ref == "2026-10-25-casual.json#0" and len(calls) == 2
    post = json.loads((d / "2026-10-25-casual.json").read_text(encoding="utf-8"))["posts"][0]
    assert post["image_url"].startswith(illust.SITE) and (tmp_path / "out" / Path(post["image"]).name).exists()
    state = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert 7 <= state["every"] <= 10 and state["last_made"] == "2026-10-25"


def test_maybe_make_gives_up_when_check_fails(tmp_path):
    d = _drafts(tmp_path)
    gen = lambda s, u, schema, tier="standard": {"ref": "2026-10-25.json#0", "scene": "x", "why": ""}  # noqa: E731
    ref = illust.maybe_make(CONFIG, TODAY, gen, d, _posted(10), state_path=tmp_path / "s.json", out_dir=tmp_path / "out",
                            drawer=lambda scene, models: Image.new("RGB", (10, 10)), checker=lambda img, scene: (False, ["崩れ"]))
    assert ref is None and "image_url" not in json.loads((d / "2026-10-25.json").read_text(encoding="utf-8"))["posts"][0]


class Client:
    def __init__(self, fail_image=False):
        self.calls, self.fail_image = [], fail_image

    def post_text(self, text, reply_to=None, topic_tag=None, image_url=None):
        if image_url and self.fail_image:
            raise RuntimeError("image error")
        self.calls.append((text, image_url))
        return f"id{len(self.calls)}"

    def permalink(self, media_id):
        return "https://threads/" + media_id


def test_publish_with_image_and_fallback():
    post = {"type": "casual", "text": "朝", "image_url": "https://x/1.jpg"}
    c = Client()
    autopost.publish(c, post, [])
    assert c.calls == [("朝", "https://x/1.jpg")] and post["_with_image"]
    c2 = Client(fail_image=True)
    post2 = {"type": "casual", "text": "朝", "image_url": "https://x/1.jpg"}
    autopost.publish(c2, post2, [])
    assert c2.calls == [("朝", None)] and "_with_image" not in post2
    pr = {"type": "pr", "text": "PR", "image_url": "https://x/1.jpg", "reply_text": "リンク"}
    c3 = Client()
    autopost.publish(c3, pr, [])
    assert c3.calls[0] == ("PR", None)  # PR 投稿には付けない


def test_remove_image(tmp_path):
    d = _drafts(tmp_path)
    p = d / "2026-10-25-casual.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["posts"][0].update(image="kotori/illust/a.jpg", image_url="https://x/a.jpg")
    p.write_text(json.dumps(data), encoding="utf-8")
    assert autopost.remove_image(d, "2026-10-25-casual.json", 0) == 0
    assert "image_url" not in json.loads(p.read_text(encoding="utf-8"))["posts"][0]
    assert autopost.remove_image(d, "../x.json", 0) == 1
