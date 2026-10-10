import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import comments  # noqa: E402
import extras  # noqa: E402
import generate_drafts  # noqa: E402
import insights  # noqa: E402
import prompts  # noqa: E402
import sources  # noqa: E402
import threads  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402

FIXTURES = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))
CONFIG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
TODAY = datetime.date(2026, 10, 25)


class Gen:
    """固定の返答を返す AI。呼ばれた重要度（tier）を記録する。"""

    def __init__(self, **over):
        self.over, self.tiers, self.calls = over, [], []

    def research(self, system, user, tier="important"):
        self.tiers.append(("research", tier))
        return "メモ"

    def __call__(self, system, user, schema, tier="standard"):
        name = {id(prompts.BUZZ_SCHEMA): "buzz", id(prompts.CASUAL_SCHEMA): "casual",
                id(prompts.COMMENT_SCHEMA): "comment"}[id(schema)]
        self.tiers.append((name, tier))
        self.calls.append(user)
        data = json.loads(json.dumps(FIXTURES[name]))
        fix = self.over.get(name)
        return fix(data, len(self.calls)) if fix else data


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTORI_DRAFTS_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    return tmp_path


# ---------------- ニュースの見出し

def test_parse_feed_handles_rss_rdf_and_atom():
    rss = "<rss><channel><item><title>運動会 何時から</title></item><item><title> 秋の 遠足 </title></item></channel></rss>"
    rdf = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">'
           "<item><title>水筒の洗い方</title></item></rdf:RDF>")
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>給食の話</title></entry></feed>'
    assert sources.parse_feed(rss) == ["運動会 何時から", "秋の 遠足"]
    assert sources.parse_feed(rdf) == ["水筒の洗い方"]
    assert sources.parse_feed(atom) == ["給食の話"]
    assert sources.parse_feed("not xml") == []


def test_collect_skips_sad_news_and_failures():
    class S:
        def get(self, url, headers, timeout):
            if "yahoo" in url:
                raise RuntimeError("down")
            r = type("R", (), {})()
            r.raise_for_status = lambda: None
            r.text = ("<rss><channel><item><title>小学生の習い事ランキング</title></item>"
                      "<item><title>通学路で事故 児童けが</title></item></channel></rss>")
            return r
    headlines, failed = sources.collect(session=S(), queries=["子育て"])
    titles = [t for _, t in headlines]
    assert titles == ["小学生の習い事ランキング"]  # 同じ見出しは1回・事故の見出しは外す
    assert any("Yahoo" in f for f in failed)


# ---------------- 自動チェック

def test_simple_post_checks():
    assert checks.check_simple_post("朝から雨で傘が2本", "つぶやき", 5, 140) == []
    errors = checks.check_simple_post("いかがでしたか？ #子育て https://x.co.jp PR", "つぶやき", 5, 140)
    joined = "\n".join(errors)
    assert "リンク" in joined and "ハッシュタグ" in joined and "PR" in joined and "AI" in joined


def test_ai_smell_is_an_error_in_product_posts():
    posts = json.loads(json.dumps(FIXTURES["write"]["posts"]))
    posts[0]["text"] += "\n結論から言うと、これがおすすめ。"
    errors, _ = checks.check_posts(posts)
    assert any("結論から言うと" in e for e in errors)


# ---------------- 集客投稿

def test_buzz_uses_best_model_and_falls_back_to_passing_draft(tmp_path):
    def broken_best(data, n):
        data["drafts"][2]["text"] = "まとめると、洗濯は大変。"  # AI が選んだ案がチェックに通らない
        return data
    gen = Gen(buzz=broken_best)
    data = extras.make_buzz(CONFIG, TODAY, gen, [], tmp_path, collect=lambda *a: ([("x", "運動会")], []))
    assert gen.tiers == [("research", "important"), ("buzz", "important")]
    assert data["errors"] == [] and data["posts"][0]["type"] == "buzz"
    assert data["posts"][0]["angle"] == "あるある共感"  # 次に点数の高い、合格した案
    assert data["topic_tag"] == "子育て" and data["product"]["keyword"] == "体操服 速乾 小学生"
    assert "まとめると" not in data["posts"][0]["text"]


def test_buzz_retries_with_feedback_when_all_fail(tmp_path):
    def all_bad(data, n):
        if n == 1:
            for d in data["drafts"]:
                d["text"] = "必見！" + d["text"]
        return data
    gen = Gen(buzz=all_bad)
    data = extras.make_buzz(CONFIG, TODAY, gen, [], tmp_path, collect=lambda *a: ([], []))
    assert data["errors"] == [] and len(gen.calls) == 2 and "必見" in gen.calls[1]


# ---------------- つぶやき・ネタ帳

def test_casual_uses_cheap_model_and_marks_used_neta(tmp_path):
    def with_memo(data, n):
        data["posts"][0]["memo_used"] = "体操服を忘れて走って取りに帰った"
        data["posts"][0]["text"] = "体操服を忘れて家まで走って戻った朝。息切れ"
        return data
    gen = Gen(casual=with_memo)
    neta = [(12, "朝、体操服を忘れて走って取りに帰った"), (13, "別の話")]
    data = extras.make_casual(CONFIG, TODAY, gen, tmp_path, neta)
    assert gen.tiers == [("casual", "casual")]
    assert len(data["posts"]) == 3 and data["neta_used"] == [12]
    assert data["posts"][0]["angle"] == "ネタ帳" and data["posts"][1]["angle"] == "日常"
    assert "体操服を忘れて走って" in gen.calls[0]


def test_fetch_neta_only_uses_owner_issues():
    class S:
        def get(self, url, headers, timeout, params):
            r = type("R", (), {})()
            r.raise_for_status = lambda: None
            body = "### あったこと\n\n娘が「明日から本気出す」と言った"
            r.json = lambda: [
                {"number": 1, "title": "[ネタ帳] a", "labels": [], "user": {"login": "keiyamada-ui"}, "body": body},
                {"number": 2, "title": "[ネタ帳] b", "labels": [], "user": {"login": "someone"}, "body": body},
                {"number": 3, "title": "[推し商品]", "labels": [], "user": {"login": "keiyamada-ui"}, "body": body},
                {"number": 4, "title": "x", "labels": [{"name": "ネタ帳"}], "user": {"login": "keiyamada-ui"},
                 "body": "### あったこと\n\n_No response_"},
            ]
            return r
    assert extras.fetch_neta("keiyamada-ui/keiyamada-ui.github.io", "t", session=S()) == \
        [(1, "娘が「明日から本気出す」と言った")]
    assert extras.fetch_neta("", "", session=S()) == []


# ---------------- 反響 → PR 投稿

def _store(likes_by_kind):
    store = {}
    for n, (kind, likes, date) in enumerate(likes_by_kind):
        store[f"m{n}"] = {"date": date, "kind": kind, "draft": f"{date}-{kind}.json", "post_index": 0,
                          "permalink": "", "metrics": {"likes": likes, "views": likes * 30}, "fetched": "x"}
    return store


def test_pick_followup_needs_a_clear_spike():
    store = _store([("buzz", 30, "2026-10-23"), ("casual", 3, "2026-10-23"), ("value", 4, "2026-10-24"),
                    ("buzz", 5, "2026-10-24"), ("buzz", 50, "2026-10-25")])
    name, likes, _ = insights.pick_followup(store, TODAY, [], 10)
    assert (name, likes) == ("2026-10-23-buzz.json", 30)  # 当日の投稿はまだ判断しない
    assert insights.pick_followup(store, TODAY, ["2026-10-23-buzz.json"], 10) is None
    assert insights.pick_followup(store, TODAY, [], 40) is None
    flat = _store([("buzz", 12, "2026-10-23"), ("value", 11, "2026-10-23"), ("casual", 12, "2026-10-24")])
    assert insights.pick_followup(flat, TODAY, [], 10) is None  # みんな同じくらいなら「反響あり」ではない


def test_collect_insights_and_summary(tmp_path):
    class C:
        def insights(self, media_id):
            if media_id == "bad":
                raise threads.ThreadsError("x")
            return {"likes": 7, "views": 100}
    posted = [{"date": "2026-10-24", "kind": "buzz", "draft": "a", "post_index": 0, "ids": ["m1"]},
              {"date": "2026-10-24", "kind": "casual", "draft": "b", "post_index": 0, "ids": ["bad"]},
              {"date": "2026-10-01", "kind": "buzz", "draft": "c", "post_index": 0, "ids": ["old"]}]
    store, reason = insights.collect(C(), posted, TODAY, tmp_path / "i.json")
    assert reason is None and list(store) == ["m1"]
    assert "集客投稿: 1件" in insights.summary(store, TODAY)[0]

    class NoPerm:
        def insights(self, media_id):
            raise threads.ThreadsError("permission")
    store, reason = insights.collect(NoPerm(), posted, TODAY, tmp_path / "j.json")
    assert store is None and "反響" in reason


def test_daily_run_turns_a_hit_into_a_followup_pr(out_dir, monkeypatch):
    drafts = Path(out_dir)
    buzz = {"date": "2026-10-09", "kind": "buzz", "topic": "体操服の洗濯", "errors": [],
            "posts": [{"type": "buzz", "text": "体操服が毎日ドロドロ"}],
            "product": {"keyword": "サッカー 練習 子供", "source": "ichiba", "persona": "親"}}
    (drafts / "2026-10-09-buzz.json").write_text(json.dumps(buzz, ensure_ascii=False), encoding="utf-8")
    store = _store([("buzz", 40, "2026-10-09"), ("casual", 2, "2026-10-09"), ("value", 3, "2026-10-08")])
    store["m0"]["draft"] = "2026-10-09-buzz.json"
    monkeypatch.setattr(generate_drafts, "update_insights", lambda today, dry_run=False: (store, None))
    assert generate_drafts.main(["--dry-run", "--date", "2026-10-10"]) == 0
    data = json.loads((drafts / "2026-10-10.json").read_text(encoding="utf-8"))
    assert data["followup"] == {"draft": "2026-10-09-buzz.json", "likes": 40}
    md = (drafts / "2026-10-10.md").read_text(encoding="utf-8")
    assert "🔥" in md and "反響" in md
    assert json.loads((drafts / "2026-10-10-buzz.json").read_text(encoding="utf-8"))["posts"]
    assert len(json.loads((drafts / "2026-10-10-casual.json").read_text(encoding="utf-8"))["posts"]) == 3


# ---------------- コメント

def test_comments_collect_and_suggest(tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "d.json").write_text(json.dumps({"posts": [{"text": "自分の投稿"}]}, ensure_ascii=False), encoding="utf-8")

    class C:
        def replies(self, media_id):
            return [{"id": "c1", "username": "mama", "text": "うちも毎晩洗濯です", "permalink": "p"},
                    {"id": "c2", "username": "kotori.family", "text": "自分の返信"},
                    {"id": "c3", "username": "x", "text": "old"},
                    {"id": "c4", "username": "y", "text": "隠した", "hide_status": "HIDDEN"}]
    posted = [{"date": "2026-10-24", "kind": "buzz", "draft": "d.json", "post_index": 0, "ids": ["m"],
               "permalink": "pp"}]
    items, reason = comments.collect_new(C(), posted, TODAY, {"c3"}, drafts, "kotori.family")
    assert reason is None and [i["id"] for i in items] == ["c1"] and items[0]["post_text"] == "自分の投稿"
    gen = Gen()
    items = comments.suggest(CONFIG, items, gen)
    assert gen.tiers == [("comment", "casual")] and items[0]["action"] == "reply" and items[0]["reply_text"]
    comments.save(tmp_path / "c.json", items, datetime.datetime(2026, 10, 25, 12, 0))
    comments.save(tmp_path / "c.json", items, datetime.datetime(2026, 10, 25, 13, 0))
    assert len(json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))["comments"]) == 1
    assert "1 件" in comments.report(items)


def test_comment_reply_never_contains_links(tmp_path):
    def linky(data, n):
        data["replies"][0]["reply_text"] = "こちらです https://hb.afl.rakuten.co.jp/x"
        return data
    items = [{"id": "c1", "username": "a", "text": "どこで買えますか？", "post_text": "p"}]
    assert comments.suggest(CONFIG, items, Gen(comment=linky))[0]["reply_text"] == ""
