import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import generate_drafts  # noqa: E402
import llm  # noqa: E402
import rakuten  # noqa: E402
import selector  # noqa: E402

TODAY = datetime.date(2026, 10, 10)
FILTERS = {"min_review_count": 20, "min_review_average": 4.0, "reuse_after_days": 60, "max_candidates": 3}


def good_posts():
    data = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))
    return data["posts"]


# --- checks ---

def test_sample_posts_pass():
    errors, warnings = checks.check_posts(good_posts())
    assert errors == [] and warnings == []


def test_link_in_body_is_rejected():
    posts = good_posts()
    posts[0]["text"] += "\nhttps://example.com"
    errors, _ = checks.check_posts(posts)
    assert any("本文にリンク" in e for e in errors)


def test_pr_label_must_be_on_first_line():
    posts = good_posts()
    posts[2]["text"] = posts[2]["text"].replace("【PR】", "")
    errors, _ = checks.check_posts(posts)
    assert any("PR" in e and "1行目" in e for e in errors)


def test_reply_needs_exactly_one_link_and_hashtag():
    posts = good_posts()
    posts[2]["reply_text"] = "{{LINK}} {{LINK}}"
    errors, _ = checks.check_posts(posts)
    assert any("ちょうど1つ" in e for e in errors)
    assert any("#PR" in e for e in errors)


def test_ng_words_and_length():
    posts = good_posts()
    posts[1]["text"] = "これで必ず上手くなる！" + "あ" * 500
    errors, _ = checks.check_posts(posts)
    assert any("必ず" in e for e in errors)
    assert any("文字" in e for e in errors)


def test_experience_words_are_warnings():
    posts = good_posts()
    posts[0]["text"] += "\n我が家でも使ってみました"
    errors, warnings = checks.check_posts(posts)
    assert errors == [] and len(warnings) == 2


def test_post_counts():
    errors, _ = checks.check_posts(good_posts()[:2])
    assert any("PR投稿" in e for e in errors)


# --- selector ---

def item(i, reviews=100, avg=4.5, source="ichiba"):
    return {"source": source, "id": f"id{i}", "name": f"商品{i}", "url": f"https://x/{i}",
            "review_count": reviews, "review_average": avg}


def test_select_filters_and_excludes_recent():
    items = [item(1), item(2, reviews=5), item(3, avg=3.5), item(4), item(4), item(5, reviews=999)]
    history = [{"date": "2026-09-01", "source": "ichiba", "id": "id1"},
               {"date": "2026-01-01", "source": "ichiba", "id": "id5"}]
    picked = selector.select_candidates(items, history, TODAY, FILTERS)
    assert [p["id"] for p in picked] == ["id5", "id4"]


def test_pick_theme_rotates_and_is_stable():
    pillars = generate_drafts.load_config()["pillars"]
    seen = {selector.pick_theme(pillars, TODAY + datetime.timedelta(days=d))[0]["id"] for d in range(len(pillars))}
    assert len(seen) == len(pillars)
    assert selector.pick_theme(pillars, TODAY) == selector.pick_theme(pillars, TODAY)
    assert selector.pick_theme(pillars, TODAY, "family_travel")[0]["source"] == "travel"


# --- rakuten response parsing ---

def test_normalize_ichiba_both_formats():
    raw = {"itemCode": "s:1", "itemName": "ボール", "itemPrice": "2980", "affiliateUrl": "https://hb.afl.rakuten.co.jp/x",
           "itemUrl": "https://item", "reviewCount": 10, "reviewAverage": "4.5", "shopName": "店",
           "mediumImageUrls": [{"imageUrl": "https://img"}]}
    v1 = rakuten._items({"Items": [{"Item": raw}]}, "Items", "Item")
    v2 = rakuten._items({"Items": [raw]}, "Items", "Item")
    a, b = rakuten.normalize_ichiba(v1[0]), rakuten.normalize_ichiba(v2[0])
    assert a == b
    assert a["price"] == 2980 and a["url"].startswith("https://hb.afl") and a["image"] == "https://img"


def test_normalize_travel_nested():
    data = {"hotels": [[{"hotelBasicInfo": {"hotelNo": 1, "hotelName": "宿", "hotelMinCharge": 8000,
                                            "hotelInformationUrl": "https://hb.afl.rakuten.co.jp/h",
                                            "reviewCount": 50, "reviewAverage": 4.4}},
                        {"hotelRatingInfo": {"serviceAverage": 4.5}}]]}
    hotel = rakuten.normalize_travel(rakuten._hotels(data)[0])
    assert hotel["id"] == "1" and hotel["price"] == 8000 and hotel["is_affiliate_url"]


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


def test_client_sends_keys_and_referer():
    session = FakeSession(FakeResponse(200, {"Items": []}))
    client = rakuten.RakutenClient("app", "key", "aff", {"ichiba": "https://api"}, "https://site/",
                                   min_interval_seconds=0, session=session)
    client.search("ichiba", "ボール")
    _, params, headers = session.calls[0]
    assert params["applicationId"] == "app" and params["accessKey"] == "key" and params["affiliateId"] == "aff"
    assert headers["accessKey"] == "key" and headers["Referer"] == "https://site/" and headers["Origin"] == "https://site"


def test_client_raises_on_error():
    session = FakeSession(FakeResponse(403, {"error": "REQUEST_CONTEXT_BODY_HTTP_REFERRER_MISSING"}))
    client = rakuten.RakutenClient("app", "key", None, {"ichiba": "https://api"}, "https://site/",
                                   min_interval_seconds=0, session=session)
    try:
        client.search("ichiba", "ボール")
    except rakuten.RakutenError as e:
        assert "403" in str(e)
    else:
        raise AssertionError("エラーになるはず")


# --- llm ---

def test_parse_json_strips_code_fence():
    raw = "```json\n" + json.dumps({"chosen_candidate_id": "a", "why_this_candidate": "b",
                                    "posts": [], "hook_alternatives": []}) + "\n```"
    assert llm._parse_json(raw)["chosen_candidate_id"] == "a"


def test_provider_switch(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.provider() == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llm.provider() == "claude"
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert llm.provider() == "gemini"


# --- end to end ---

def test_dry_run_writes_draft(tmp_path):
    for pillar in ["kids_learning", "kids_books", "family_travel", "sale_prep"]:
        assert generate_drafts.main(["--dry-run", "--date", "2026-10-10", "--pillar", pillar,
                                     "--out-dir", str(tmp_path)]) == 0
        body = (tmp_path / "2026-10-10.md").read_text(encoding="utf-8")
        assert "✅" in body and "https://hb.afl.rakuten.co.jp" in body and "{{LINK}}" not in body


def test_rewrite_loop_feeds_errors_back():
    config = generate_drafts.load_config()
    pillar, query = selector.pick_theme(config["pillars"], TODAY, "kids_learning")
    candidates = [dict(item(1), price=1000, shop="店", caption="")]
    calls = []

    def generate(system, user):
        calls.append(user)
        posts = good_posts()
        if len(calls) == 1:
            posts[2]["text"] = "表記を忘れた本文"
        return {"chosen_candidate_id": "id1", "why_this_candidate": "", "posts": posts, "hook_alternatives": []}

    result, errors, _ = generate_drafts.write_posts(config, pillar, query, candidates, TODAY, generate)
    assert errors == [] and len(calls) == 2 and "1行目" in calls[1]


def test_history_one_file_per_day(tmp_path):
    selector.save_history_entry(tmp_path, {"date": "2026-10-10", "source": "ichiba", "id": "a", "name": "A", "pillar": "p"})
    selector.save_history_entry(tmp_path, {"date": "2026-10-10", "source": "ichiba", "id": "a", "name": "A", "pillar": "p"})
    selector.save_history_entry(tmp_path, {"date": "2026-10-11", "source": "books", "id": "b", "name": "B", "pillar": "p"})
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-10-10.json", "2026-10-11.json"]
    assert [h["id"] for h in selector.load_history(tmp_path)] == ["a", "b"]
