import datetime
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import generate_drafts  # noqa: E402
import issue_forms  # noqa: E402
import llm  # noqa: E402
import patterns  # noqa: E402
import prompts  # noqa: E402
import rakuten  # noqa: E402
import selector  # noqa: E402
import themes  # noqa: E402

TODAY = datetime.date(2026, 10, 10)
CONFIG = generate_drafts.load_config()
FIXTURES = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))


def good_posts():
    return json.loads(json.dumps(FIXTURES["write"]["posts"]))


ROOM = FIXTURES["write"]["room_comment"]


# ---------------- checks ----------------

def test_sample_posts_pass():
    assert checks.check_posts(good_posts(), ROOM) == ([], [])


def test_link_in_body_is_rejected():
    posts = good_posts()
    posts[1]["text"] += "\nhttps://example.com"
    errors, _ = checks.check_posts(posts, ROOM)
    assert any("本文にリンク" in e for e in errors)


def test_pr_label_must_be_on_first_line():
    posts = good_posts()
    posts[2]["text"] = posts[2]["text"].replace("【PR】", "")
    errors, _ = checks.check_posts(posts, ROOM)
    assert any("1行目" in e for e in errors)


def test_reply_needs_exactly_one_link_and_hashtag():
    posts = good_posts()
    posts[2]["reply_text"] = "{{LINK}} {{LINK}}"
    errors, _ = checks.check_posts(posts, ROOM)
    assert any("ちょうど1つ" in e for e in errors) and any("#PR" in e for e in errors)


def test_ng_words_length_and_tree_rules():
    posts = good_posts()
    posts[1]["text"] = "これで必ず上手くなる！" + "あ" * 500
    posts[0]["thread_parts"].append("https://example.com")
    posts[2]["thread_parts"] = ["続き"]
    errors, _ = checks.check_posts(posts, ROOM)
    assert any("必ず" in e for e in errors)
    assert any("文字" in e for e in errors)
    assert any("ツリー" in e and "リンク" in e for e in errors)
    assert any("PR投稿はツリーにしない" in e for e in errors)


def test_room_comment_rules():
    errors, _ = checks.check_posts(good_posts(), "最安です https://x.com")
    assert any("ROOM" in e and "リンク" in e for e in errors)
    assert any("ROOM" in e and "#PR" in e for e in errors)
    assert any("ROOM" in e and "最安" in e for e in errors)


def test_experience_words_are_warnings():
    posts = good_posts()
    posts[1]["text"] += "\n我が家でも使ってみました"
    errors, warnings = checks.check_posts(posts, ROOM)
    assert errors == [] and len(warnings) == 2


# ---------------- selector ----------------

def item(i, reviews=100, avg=4.5, price=3000, source="ichiba", rate=None):
    return {"source": source, "id": f"id{i}", "name": f"商品{i}", "url": f"https://x/{i}", "price": price,
            "review_count": reviews, "review_average": avg, "affiliate_rate": rate}


def test_filter_excludes_recent_low_and_duplicates():
    items = [item(1), item(2, reviews=5), item(3, avg=3.5), item(4), item(4), item(5, reviews=999)]
    history = [{"date": "2026-09-01", "source": "ichiba", "id": "id1"},
               {"date": "2026-01-01", "source": "ichiba", "id": "id5"}]
    picked = selector.filter_items(items, history, TODAY, CONFIG["filters"])
    assert [p["id"] for p in picked] == ["id4", "id5"]


def test_hidden_gem_filter():
    items = [item(1, reviews=30, avg=4.7), item(2, reviews=500, avg=4.7), item(3, reviews=30, avg=4.2)]
    picked = selector.filter_items(items, [], TODAY, CONFIG["filters"], CONFIG["hidden_gems"])
    assert [p["id"] for p in picked] == ["id1"] and picked[0]["is_hidden_gem"]
    assert selector.is_hidden_gem_day(datetime.date(2026, 10, 14), CONFIG["hidden_gems"])  # 水曜


def test_score_prefers_demand_profit_and_trend():
    items = [item(1, reviews=50, price=1000), item(2, reviews=3000, price=1000),
             item(3, reviews=50, price=20000, rate=4.0)]
    scored = selector.score_items([dict(i) for i in items], CONFIG["scoring"])
    by_id = {i["id"]: i for i in scored}
    assert by_id["id2"]["score_detail"]["需要"] > by_id["id1"]["score_detail"]["需要"]
    assert by_id["id3"]["commission"] == 800 and by_id["id1"]["affiliate_rate"] == 2.0
    trended = selector.score_items([dict(i) for i in items], CONFIG["scoring"], {"ichiba:id1": 0.5})
    assert next(i for i in trended if i["id"] == "id1")["score_detail"]["勢い"] > 0
    ranked = selector.score_items([dict(item(1)), dict(item(2))], CONFIG["scoring"], ranks={"id1": 1})
    assert ranked[0]["id"] == "id1" and ranked[0]["ranking"] == 1


def test_snapshots_measure_trend(tmp_path):
    selector.save_snapshot(tmp_path, datetime.date(2026, 10, 1), [item(1, reviews=100)])
    growth = selector.trends(tmp_path, TODAY, [item(1, reviews=190), item(2)])
    assert growth == {"ichiba:id1": pytest.approx(0.1)}


def test_history_one_file_per_day(tmp_path):
    for d, i in [("2026-10-10", "a"), ("2026-10-10", "a"), ("2026-10-11", "b")]:
        selector.save_history_entry(tmp_path, {"date": d, "source": "ichiba", "id": i, "name": i})
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-10-10.json", "2026-10-11.json"]
    assert [h["id"] for h in selector.load_history(tmp_path)] == ["a", "b"]


# ---------------- themes ----------------

def test_theme_rank_prefers_urgent_seasonal_and_skips_recent():
    pool = [themes._make("AI", "ichiba", "a", "", urgency=5, months=[10]),
            themes._make("AI", "ichiba", "b", "", urgency=1),
            themes._make("参考投稿", "books", "c", "", urgency=4)]
    ordered = themes.rank(pool, [], TODAY, 21)
    assert ordered[0]["keyword"] == "a"
    history = [{"date": "2026-10-09", "source": "ichiba", "theme_id": pool[0]["id"]}]
    ordered = themes.rank(pool, history, TODAY, 21)
    assert [t["keyword"] for t in ordered][0] == "c"  # a は最近使った・ichiba が続くので books が先
    assert "a" not in [t["keyword"] for t in ordered]


def test_theme_bank_roundtrip(tmp_path):
    themes.save_bank(tmp_path, TODAY, FIXTURES["themes"]["themes"])
    loaded = themes.load_bank(tmp_path, datetime.date(2026, 11, 3))  # 翌月でも先月分を読む
    assert len(loaded) == 2 and loaded[0]["origin"] == "AI"
    assert len(themes.fixed_themes(CONFIG)) > 5


# ---------------- rakuten ----------------

def test_normalize_ichiba_both_formats():
    raw = {"itemCode": "s:1", "itemName": "ボール", "itemPrice": "2980", "affiliateUrl": "https://hb.afl.rakuten.co.jp/x",
           "reviewCount": 10, "reviewAverage": "4.5", "shopName": "店", "affiliateRate": "4.0", "genreId": 123,
           "mediumImageUrls": [{"imageUrl": "https://img"}]}
    a = rakuten.normalize_ichiba(rakuten._items({"Items": [{"Item": raw}]}, "Items", "Item")[0])
    b = rakuten.normalize_ichiba(rakuten._items({"Items": [raw]}, "Items", "Item")[0])
    assert a == b and a["price"] == 2980 and a["affiliate_rate"] == 4.0 and a["genre_id"] == "123"


def test_normalize_travel_nested():
    data = {"hotels": [[{"hotelBasicInfo": {"hotelNo": 1, "hotelName": "宿", "hotelMinCharge": 8000,
                                            "hotelInformationUrl": "https://hb.afl.rakuten.co.jp/h",
                                            "reviewCount": 50, "reviewAverage": 4.4}}]]}
    hotel = rakuten.normalize_travel(rakuten._hotels(data)[0])
    assert hotel["id"] == "1" and hotel["price"] == 8000 and hotel["is_affiliate_url"]


def test_product_urls():
    assert rakuten.parse_product_url("https://item.rakuten.co.jp/shop/ball-1/?x=1") == ("ichiba", "shop:ball-1")
    assert rakuten.parse_product_url("https://travel.rakuten.co.jp/HOTEL/123/123.html") == ("travel", "123")
    affiliate = "https://hb.afl.rakuten.co.jp/hgc/x/?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fs%2Fi%2F"
    assert rakuten.resolve_url(affiliate) == "https://item.rakuten.co.jp/s/i/"
    with pytest.raises(rakuten.RakutenError):
        rakuten.parse_product_url("https://example.com/")


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, params, headers, timeout):
        self.calls.append((url, params, headers))
        return self.response


def client(response):
    session = FakeSession(response)
    endpoints = {k: f"https://api/{k}" for k in ("ichiba", "books", "travel", "travel_hotel", "ranking")}
    return rakuten.RakutenClient("app", "key", "aff", endpoints, "https://site/", min_interval_seconds=0,
                                 session=session), session


def test_client_sends_keys_and_referer():
    c, session = client(FakeResponse(200, {"Items": []}))
    c.search("ichiba", "ボール")
    _, params, headers = session.calls[0]
    assert params["applicationId"] == "app" and params["accessKey"] == "key" and params["affiliateId"] == "aff"
    assert headers["accessKey"] == "key" and headers["Referer"] == "https://site/" and headers["Origin"] == "https://site"


def test_client_lookup_by_item_url():
    c, session = client(FakeResponse(200, {"Items": [{"itemCode": "shop:ball", "itemName": "ボール", "itemPrice": 1,
                                                      "affiliateUrl": "https://hb.afl.rakuten.co.jp/x"}]}))
    found = c.lookup("https://item.rakuten.co.jp/shop/ball/")
    assert found["id"] == "shop:ball" and session.calls[0][1]["itemCode"] == "shop:ball"


class SequenceSession(FakeSession):
    def __init__(self, responses):
        super().__init__(None)
        self.responses = list(responses)

    def get(self, url, params, headers, timeout):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def test_client_retries_when_rate_limited(monkeypatch):
    monkeypatch.setattr(rakuten.time, "sleep", lambda s: None)
    session = SequenceSession([FakeResponse(429, {"message": "Rate limit is exceeded"}),
                               FakeResponse(200, {"Items": [{"isbn": "978", "title": "図鑑", "itemPrice": 1}]})])
    c = rakuten.RakutenClient("app", "key", None, {"books": "https://api/books"}, "https://site/",
                              min_interval_seconds=0, session=session)
    assert c.search("books", "図鑑")[0]["name"] == "図鑑" and len(session.calls) == 2
    always = SequenceSession([FakeResponse(429, {"message": "slow down"})] * 4)
    c.session = always
    with pytest.raises(rakuten.RakutenError, match="429"):
        c.search("books", "図鑑")
    assert len(always.calls) == 4


def test_client_raises_on_error():
    c, _ = client(FakeResponse(403, {"error": "REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING"}))
    with pytest.raises(rakuten.RakutenError, match="403"):
        c.search("ichiba", "ボール")


# ---------------- llm ----------------

def test_parse_json_strips_code_fence():
    raw = "```json\n" + json.dumps(FIXTURES["reference"]) + "\n```"
    assert llm._parse_json(raw, prompts.REFERENCE_SCHEMA)["hook_type"] == "常識くつがえし型"
    with pytest.raises(llm.LLMError):
        llm._parse_json("{}", prompts.REFERENCE_SCHEMA)


def test_claude_falls_back_to_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")

    def broke(*_):
        raise RuntimeError("Your credit balance is too low to access the Anthropic API")

    calls = []
    monkeypatch.setattr(llm, "_call_claude", broke)
    monkeypatch.setattr(llm, "_call_gemini", lambda *a: calls.append(1) or json.dumps(FIXTURES["reference"]))
    gen = llm.Generator()
    assert gen.provider == "claude"
    assert gen("s", "u", prompts.REFERENCE_SCHEMA)["summary"]
    assert gen.provider == "gemini" and "残高" in gen.notice
    gen("s", "u", prompts.REFERENCE_SCHEMA)  # 2回目からは最初から Gemini
    assert len(calls) == 2


def test_claude_error_without_gemini_key_is_raised(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_call_claude", lambda *a: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        llm.Generator()("s", "u", prompts.REFERENCE_SCHEMA)


def test_gemini_when_no_claude_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.Generator().provider == "gemini"


# ---------------- forms & patterns ----------------

def test_issue_form_parsing():
    body = ("### 商品のURL\n\nhttps://item.rakuten.co.jp/a/b/ \n\n### ISBN（本の場合）\n\n_No response_\n\n"
            "### 実際に使いましたか？\n\n- [X] 使ったことがある")
    form = issue_forms.parse(body)
    assert issue_forms.first_url(form["商品のURL"]) == "https://item.rakuten.co.jp/a/b/"
    assert form["ISBN（本の場合）"] == "" and issue_forms.checked(form["実際に使いましたか？"])


def test_pattern_comment_roundtrip():
    body = patterns.format_comment(FIXTURES["reference"])
    assert patterns.parse_comment(body)["hook_type"] == "常識くつがえし型"
    assert patterns.parse_comment("ふつうのコメント") is None
    assert patterns.fetch_patterns(None, None) == []


# ---------------- end to end（お試し実行） ----------------

@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTORI_DRAFTS_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    return tmp_path


def test_dry_run_daily(out_dir):
    for day in ["2026-10-10", "2026-10-14"]:  # 通常の日と発掘枠の日
        assert generate_drafts.main(["--dry-run", "--date", day]) == 0
        body = (out_dir / f"{day}.md").read_text(encoding="utf-8")
        assert "PR表記・リンク1本" in body and "https://hb.afl.rakuten.co.jp" in body and "{{LINK}}" not in body
        assert "楽天ROOM" in body and "ツリー 2/3" in body and "確認してほしいこと" in body
    assert "title<<__END__" in (out_dir / "out.txt").read_text(encoding="utf-8")


def test_dry_run_keyword_item_and_themes(out_dir, monkeypatch):
    assert generate_drafts.main(["--dry-run", "--date", "2026-10-10", "--keyword", "図鑑", "--source", "books"]) == 0
    monkeypatch.setenv("ISSUE_BODY", "### 商品のURL\n\nhttps://item.rakuten.co.jp/a/b/\n\n### ひとことメモ\n\n毎朝使ってます\n\n"
                                     "### 実際に使いましたか？\n\n- [x] 使ったことがある")
    monkeypatch.setenv("ISSUE_NUMBER", "7")
    assert generate_drafts.main(["--dry-run", "--date", "2026-10-10", "--from-issue"]) == 0
    assert "推し商品" in (out_dir / "2026-10-10-item-7.md").read_text(encoding="utf-8")
    assert generate_drafts.main(["--dry-run", "--date", "2026-10-10", "--generate-themes"]) == 0
    assert "テーマ案" in (out_dir / "2026-10-themes.md").read_text(encoding="utf-8")


def test_dry_run_reference(out_dir, monkeypatch):
    monkeypatch.setenv("ISSUE_BODY", "### 投稿の本文\n\n伸びている投稿の文章\n\n### いいねの数\n\n120")
    assert generate_drafts.main(["--dry-run", "--analyze-reference"]) == 0
    assert patterns.parse_comment((out_dir / "reference_comment.md").read_text(encoding="utf-8"))


def test_rewrite_loop_feeds_errors_back():
    theme = themes.fixed_themes(CONFIG)[0]
    chosen = dict(item(1), shop="店", caption="")
    analysis = json.loads(json.dumps(FIXTURES["analysis"]))
    calls = []

    def generate(system, user, schema):
        calls.append(user)
        result = json.loads(json.dumps(FIXTURES["write"]))
        if len(calls) == 1:
            result["posts"][2]["text"] = "表記を忘れた本文"
        return result

    result, errors, _ = generate_drafts.write_posts(CONFIG, theme, chosen, analysis, [], TODAY, generate)
    assert errors == [] and len(calls) == 2 and "1行目" in calls[1]
    assert result["posts"][2]["reply_text_with_link"].count("https://x/1") == 1


def test_manual_stock_uses_a_different_theme_and_product(out_dir):
    assert generate_drafts.main(["--dry-run", "--date", "2026-10-10"]) == 0
    index = json.loads((generate_drafts.MANUAL / "index.json").read_text(encoding="utf-8"))
    stock = index["sets"][0]
    auto = json.loads((out_dir / "2026-10-10.json").read_text(encoding="utf-8"))
    assert stock["date"] == "2026-10-10" and len(stock["posts"]) == 3
    assert stock["item"]["url"] != auto["chosen"]["url"]
    assert "https://hb.afl.rakuten.co.jp" in stock["posts"][2]["reply_text"] and stock["room_comment"]


def test_room_list_has_three_items_without_travel(out_dir):
    for day in ["2026-10-10", "2026-10-11"]:
        assert generate_drafts.main(["--dry-run", "--date", day]) == 0
    room = json.loads((generate_drafts.MANUAL / "room.json").read_text(encoding="utf-8"))
    today = [e for e in room if e["date"] == "2026-10-11"]
    assert 1 <= len(today) <= 3 and all(e["source"] in ("ichiba", "books") for e in room)
    assert all("#PR" in e["comment"] and "http" not in e["comment"] for e in room)
    assert len({e["key"] for e in room}) == len(room) and room[0]["date"] == "2026-10-11"


def test_check_room_comment():
    assert checks.check_room_comment(ROOM) == []
    assert checks.check_room_comment("") and checks.check_room_comment("必ず効く https://x.com")
