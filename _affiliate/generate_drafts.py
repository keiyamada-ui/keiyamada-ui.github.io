"""ことり｜Threads・楽天ROOM の投稿下書きを作る本体。

    python _affiliate/generate_drafts.py                     # 毎朝の下書き
    python _affiliate/generate_drafts.py --item-url URL      # 推し商品の下書き（--memo, --used, --isbn）
    python _affiliate/generate_drafts.py --generate-themes   # 今月のテーマを作り直す
    python _affiliate/generate_drafts.py --analyze-reference # 参考投稿の分析（ISSUE_BODY から読む）
    python _affiliate/generate_drafts.py --check-api         # 楽天API の接続確認
    python _affiliate/generate_drafts.py --dry-run           # サンプルデータで動作確認（API を使わない）

失敗したときは終了コード1で止まる（GitHub Actions が「失敗」になり、通知が届く）。
"""

import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import autopost  # noqa: E402
import checks  # noqa: E402
import extras  # noqa: E402
import insights  # noqa: E402
import issue_forms  # noqa: E402
import llm  # noqa: E402
import patterns as patterns_mod  # noqa: E402
import pins as pins_mod  # noqa: E402
import season  # noqa: E402
import prompts  # noqa: E402
import selector  # noqa: E402
import sources  # noqa: E402
import themes as themes_mod  # noqa: E402
from rakuten import RakutenClient, RakutenError  # noqa: E402
from threads import ThreadsClient  # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9))
MAX_ATTEMPTS = 3
DATA = HERE / "data"
MANUAL = HERE / "manual"
MANUAL_INDEX_SIZE = 40
CRITERIA = {"seasonal": "季節", "repurchase": "買い替え", "comparable": "比較しやすさ",
            "visual": "写真映え", "pain_fit": "悩み直結"}


def load_config():
    return yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))


def make_client(config):
    r = config["rakuten"]
    return RakutenClient(
        app_id=os.environ.get("RAKUTEN_APP_ID"),
        access_key=os.environ.get("RAKUTEN_ACCESS_KEY"),
        affiliate_id=os.environ.get("RAKUTEN_AFFILIATE_ID"),
        endpoints=r["endpoints"],
        referer=r["referer"],
        min_interval_seconds=r.get("min_interval_seconds", 1.2),
    )


def write_output(**values):
    """GitHub Actions の次の手順（PR 作成など）に値を渡す。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}<<__END__\n{value}\n__END__\n")


# ---------------------------------------------------------------- 楽天API の接続確認

def check_api(config):
    client = make_client(config)
    probes = {"ichiba": "サッカー ボール", "books": "図鑑", "travel": "舞浜"}
    failed = False
    for source, keyword in probes.items():
        try:
            items = client.search(source, keyword, hits=3)
            affiliate = sum(1 for i in items if i["is_affiliate_url"])
            print(f"✅ {source}: {len(items)}件取得（うちアフィリエイトURL {affiliate}件）")
            for i in items:
                print(f"   - {i['name'][:40]} / レビュー{i['review_count']}件 ★{i['review_average']}")
        except Exception as e:  # 接続確認なので全部の結果を表示してから失敗にする
            failed = True
            print(f"❌ {source}: {e}")
    try:
        ranks = client.ranking_codes("0")
        print(f"✅ ranking: {len(ranks)}件取得")
    except Exception as e:  # ランキングはなくても下書きは作れる
        print(f"⚠️ ranking（なくても動きます）: {e}")
    headlines, failed_sources = sources.collect(config.get("buzz", {}).get("feeds"), config.get("buzz", {}).get("queries"))
    print(f"✅ ニュース・トレンドの見出し: {len(headlines)}件（集客投稿のネタ集め）")
    for name in failed_sources:
        print(f"   ⚠️ 取得できなかった出どころ: {name}")
    if not os.environ.get("RAKUTEN_AFFILIATE_ID"):
        print("⚠️ RAKUTEN_AFFILIATE_ID が未設定です。リンクから購入されても報酬になりません")
    check_ai(config)
    return 1 if failed else 0


def check_ai(config):
    """AI がつながるか、重要度ごとにごく短い質問で確かめる（料金は1円未満）。"""
    schema = prompts.obj(answer=prompts.STR)
    for tier in ("important", "standard", "casual"):
        gen = llm.Generator(config.get("ai"))
        try:
            gen("短く答えてください。", "「こんにちは」と返してください。", schema, tier=tier)
            print(f"✅ AI（{tier}）: {gen.label} で動きました")
        except Exception as e:  # noqa: BLE001 - 接続確認なので、全部の結果を表示する
            print(f"❌ AI（{tier}）: {str(e)[:200]}")
        if gen.notice:
            print(f"   ⚠️ {gen.notice}")


# ---------------------------------------------------------------- テーマ

def ensure_theme_bank(config, today, generate, force=False):
    """今月のテーマがまだなければ AI に考えてもらう。失敗しても固定テーマで続ける。"""
    directory = DATA / "themes"
    path = themes_mod.bank_path(directory, today)
    if path.exists() and not force:
        return None
    existing = [t["keyword"] for t in themes_mod.load_bank(directory, today) + themes_mod.fixed_themes(config)]
    system, user = prompts.theme_messages(config["account"], today, config["themes"]["monthly_count"], existing)
    try:
        result = generate(system, user, prompts.THEME_SCHEMA)
    except Exception as e:  # noqa: BLE001
        if force:
            raise
        print(f"⚠️ 今月のテーマを作れませんでした（固定テーマで続けます）: {e}")
        return None
    valid = [t for t in result["themes"] if t["keyword"].strip() and t["source"] in ("ichiba", "books", "travel")]
    print(f"🧭 今月のテーマを{len(valid)}個作りました")
    return themes_mod.save_bank(directory, today, valid)


# ---------------------------------------------------------------- 候補探し

MAX_THEME_TRIES = 15
# どのテーマでも条件に合う商品がなかったとき、最後に使うゆるめの条件
RELAXED_FILTERS = {"min_review_count": 3, "min_review_average": 3.8}


def _score(config, theme, cands, trend_map, ranking, notes):
    ranks = {}
    if theme["source"] == "ichiba":
        for genre in list(dict.fromkeys(c.get("genre_id") for c in cands if c.get("genre_id")))[:2]:
            try:
                ranks.update(ranking(genre))
            except Exception as e:  # noqa: BLE001 - ランキングは補助なので、取れなくても続ける
                notes.append(f"ランキングを取得できませんでした（需要はレビュー件数で判定）: {str(e)[:80]}")
                break
    scored = selector.score_items(cands, config["scoring"], trend_map, ranks)
    return scored[: config["filters"]["max_candidates"]]


def find_candidates(config, ordered_themes, today, history, search, ranking, gem_day):
    """テーマを順に試して、条件に合う商品が見つかったテーマと候補を返す。
    AI が考えたテーマは検索語が細かすぎて商品が見つからないことがあるので、固定テーマも必ず試し、
    それでもだめなら条件をゆるめる。"""
    notes, tried = [], []
    fixed = [t for t in themes_mod.fixed_themes(config) if t["id"] not in {x["id"] for x in ordered_themes[:MAX_THEME_TRIES]}]
    for theme in ordered_themes[:MAX_THEME_TRIES] + fixed:
        try:
            items = search(theme["source"], theme["keyword"])
        except Exception as e:  # noqa: BLE001 - 1つのテーマの検索失敗で止めない
            print(f"⚠️ 「{theme['keyword']}」を検索できませんでした: {str(e)[:100]}")
            continue
        trend_map = selector.trends(DATA / "snapshots", today, items)  # 保存する前に、前回の記録と比べる
        selector.save_snapshot(DATA / "snapshots", today, items)
        gem = config["hidden_gems"] if gem_day else None
        cands = selector.filter_items(items, history, today, config["filters"], gem)
        if gem and not cands:
            cands = selector.filter_items(items, history, today, config["filters"])
            if cands:
                notes.append("今日は発掘枠の日でしたが、条件に合う商品がなかったため通常の候補から選びました")
        print(f"🔎 「{theme['keyword']}」: {len(items)}件取得 → 条件に合う候補 {len(cands)}件")
        if cands:
            return theme, _score(config, theme, cands, trend_map, ranking, notes), notes
        if items:
            tried.append((theme, items, trend_map))
    relaxed = dict(config["filters"], **RELAXED_FILTERS)
    for theme, items, trend_map in tried:
        cands = selector.filter_items(items, history, today, relaxed)
        if cands:
            print(f"🔎 条件をゆるめて「{theme['keyword']}」から候補 {len(cands)}件")
            notes.append("条件に合う商品が少なかったため、レビュー数の条件をゆるめて選びました。商品ページも確認してください")
            return theme, _score(config, theme, cands, trend_map, ranking, notes), notes
    raise RuntimeError("どのテーマでも条件に合う候補が見つかりませんでした（config.yaml の filters を緩めてください）")


# ---------------------------------------------------------------- AI による分析と執筆

def analyze(config, theme, candidates, today, generate, owner_note=None, tier="important"):
    system, user = prompts.analysis_messages(config["account"], theme, candidates, today, owner_note)
    analysis = generate(system, user, prompts.ANALYSIS_SCHEMA, tier=tier)
    ids = [c["id"] for c in candidates]
    warnings = []
    if analysis["chosen_candidate_id"] not in ids:
        warnings.append(f"AI が候補にない商品（{analysis['chosen_candidate_id']}）を選んだため、点数1位の商品にしました")
        analysis["chosen_candidate_id"] = ids[0]
    if analysis["angles"]:
        analysis["best_angle_index"] = min(max(analysis["best_angle_index"], 0), len(analysis["angles"]) - 1)
    chosen = next(c for c in candidates if c["id"] == analysis["chosen_candidate_id"])
    return analysis, chosen, warnings


def write_posts(config, theme, chosen, analysis, pats, today, generate, owner_note=None, tier="important",
                context=None):
    """AI に書かせて自動チェック。引っかかったら理由を伝えて書き直させる。"""
    feedback = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        system, user = prompts.write_messages(config["account"], theme, chosen, analysis, pats,
                                              today, owner_note, feedback, context)
        result = generate(system, user, prompts.WRITE_SCHEMA, tier=tier)
        errors, warnings = checks.check_posts(result["posts"], result["room_comment"], owner_note)
        print(f"✍️ 下書き {attempt}回目: エラー{len(errors)}件・要確認{len(warnings)}件")
        if not errors:
            break
        feedback = errors
    for post in result["posts"]:
        if post["type"] == "pr":
            post["reply_text_with_link"] = post["reply_text"].replace(checks.LINK_PLACEHOLDER, chosen["url"])
    return result, errors, warnings


# ---------------------------------------------------------------- 下書きの書き出し

def _code(text):
    return f"```text\n{text.strip()}\n```"


def _price(item, today):
    note = f"（{item['price_note']}）" if item.get("price_note") else ""
    return f"{item['price']:,}円{note}　※{today.isoformat()} 取得時点"


def _rating_line(analysis, item_id):
    r = next((r for r in analysis["ratings"] if r["id"] == item_id), None)
    if not r:
        return ""
    return " ／ ".join(f"{label}{r[key]}" for key, label in CRITERIA.items()) + (f"　{r['comment']}" if r["comment"] else "")


def render(today, title, theme, analysis, chosen, candidates, result, errors, warnings, notes, llm_label):
    out = [f"# {title}", ""]
    out += [f"> 読者: {analysis['reader_persona']}"]
    if theme.get("keyword"):
        out += [f"> テーマ（{theme['origin']}）: {theme.get('category') or ''} ／ 楽天で「{theme['keyword']}」を検索"]
    if theme.get("scene"):
        out += [f"> 困っている場面: {theme['scene']}"]
    out += [f"> 下書き: {llm_label}", ""]
    if chosen.get("is_hidden_gem"):
        out += ["> 💎 **発掘枠**: まだレビューが少ない高評価アイテムです。商品ページを見て、信頼できそうか確認してから投稿してください。", ""]
    for note in notes:
        out.append(f"> ℹ️ {note}")
    if notes:
        out.append("")

    out.append("## ✅ 自動チェック")
    if errors:
        out.append("❌ **直してから投稿してください:**")
        out += [f"- {e}" for e in errors]
    if warnings:
        out.append("⚠️ **確認してください:**")
        out += [f"- {w}" for w in warnings]
    if not errors and not warnings:
        out.append("PR表記・リンク1本・NGワード・文字数のチェックはすべて合格")
    if not chosen.get("is_affiliate_url"):
        out.append("⚠️ リンクがアフィリエイトURLになっていません（RAKUTEN_AFFILIATE_ID を確認してください）")
    if analysis["questions_for_human"]:
        out += ["", "## 🙋 確認してほしいこと"] + [f"- {q}" for q in analysis["questions_for_human"]]
    out.append("")

    for n, post in enumerate(result["posts"], 1):
        kind = "PR・リンクあり" if post["type"] == "pr" else "リンクなし"
        parts = post.get("thread_parts") or []
        out += [f"## 投稿{n}（{kind}）— {post['angle']}", ""]
        if parts:
            total = len(parts) + 1
            out += [f"**本文（ツリー 1/{total}）**", _code(post["text"]), ""]
            for i, part in enumerate(parts, 2):
                out += [f"**ツリー {i}/{total}**（自分の投稿への返信としてつなげる）", _code(part), ""]
        else:
            out += ["**本文**", _code(post["text"]), ""]
        if post["type"] == "pr":
            out += ["**返信**（投稿したあと、この投稿への返信として貼る）", _code(post["reply_text_with_link"]), ""]

    out += ["## 🛍️ 楽天ROOM 用コメント", "", _code(result["room_comment"]),
            "楽天ROOM アプリでこの商品を開き「ROOMに投稿」→ このコメントを貼り付け", ""]

    out += ["## 紹介する商品", "", f"- **{chosen['name']}**", f"- 価格: {_price(chosen, today)}",
            f"- レビュー: ★{chosen['review_average']}（{chosen['review_count']:,}件）／ {chosen['shop']}"]
    if chosen.get("score") is not None:
        detail = "・".join(f"{k}{v}" for k, v in chosen.get("score_detail", {}).items())
        out.append(f"- 点数: **{chosen['score']}点**（今日の候補どうしの比較: {detail}）／ 1件売れたときの報酬の目安 約{chosen['commission']:,}円（料率{chosen['affiliate_rate']}%）")
    if chosen.get("ranking"):
        out.append(f"- 楽天ランキング: ジャンル内{chosen['ranking']}位")
    if _rating_line(analysis, chosen["id"]):
        out.append(f"- AI の採点（5点満点）: {_rating_line(analysis, chosen['id'])}")
    out += [f"- 選んだ理由: {analysis['why_this_candidate']}", f"- リンク: {chosen['url']}"]
    if chosen.get("image"):
        out += ["", f"<img src=\"{chosen['image']}\" width=\"200\">"]

    out += ["", "## PR投稿の書き出し 別案"] + [f"{i}. {h}" for i, h in enumerate(result["hook_alternatives"], 1)]

    others = [c for c in candidates if c["id"] != chosen["id"]]
    if others:
        out += ["", "## ほかの候補", "", "| 商品 | 価格 | レビュー | 点数 |", "|---|---|---|---|"]
        out += [f"| {'💎' if c.get('is_hidden_gem') else ''}{c['name'][:40]} | {c['price']:,}円 | "
                f"★{c['review_average']}（{c['review_count']:,}件） | {c.get('score', '-')} |" for c in others]

    buyer = analysis["buyer"]
    labels = [("pains_before_buying", "買う直前に困っていること"), ("decision_factors", "購入を決める条件"),
              ("comparison_points", "比較するポイント"), ("hesitations", "購入を迷う理由"),
              ("expected_changes", "買った後に期待する変化")]
    out += ["", "<details><summary>📊 買う人の分析</summary>", ""]
    for key, label in labels:
        out += [f"**{label}**"] + [f"- {x}" for x in buyer[key]] + [""]
    out += ["</details>", "", "<details><summary>💡 切り口20個</summary>", ""]
    out += [f"{i}. **{a['name']}** — {a['hook']}" for i, a in enumerate(analysis["angles"], 1)]
    out += ["", "</details>", "", "<details><summary>✏️ AI の自己添削（60点版の弱点）</summary>", ""]
    out += [f"- {x}" for x in result["first_draft_issues"]] + ["", "</details>"]

    out += [
        "", "## 投稿のしかた",
        "1. 投稿1〜3は時間をあけて投稿（例: 朝・昼・夜）。PR投稿を連続させない",
        "2. ツリーや返信は、自分の投稿への返信としてつなげる（他の人の投稿には貼らない）",
        "3. 実際の状況と違う部分は、自由に書き換えてOK",
        "",
        "この PR を **Merge** すると、紹介した商品が履歴に記録され、しばらく同じ商品は選ばれません。"
        "使わなかった日は **Close** してください。",
    ]
    return "\n".join(out) + "\n"


def render_themes(today, themes):
    out = [f"# 🧭 {today:%Y年%m月}のテーマ案（{len(themes)}個）", "",
           "毎朝の下書きは、この中から緊急度・季節・最近使ったかを見て1つずつ選ばれます。",
           "合わないテーマは、この PR の data/themes のファイルから行ごと消してから Merge してください。", "",
           "| 緊急度 | 誰の悩み | 場面 | 商品カテゴリー | 楽天で検索 |", "|---|---|---|---|---|"]
    for t in sorted(themes, key=lambda t: -t["urgency"]):
        out.append(f"| {'🔥' * min(t['urgency'], 5)} | {t['who']} | {t['scene']} | {t['category']} | {t['keyword']}（{t['source']}） |")
    return "\n".join(out) + "\n"


def save_draft(body, filename):
    out_dir = Path(os.environ.get("KOTORI_DRAFTS_DIR", HERE / "drafts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(body, encoding="utf-8")
    print(f"💾 {path} に保存しました")
    return path


def save_post_data(md_path, title, kind, today, result, errors, warnings, chosen, followup=None):
    """自動投稿用に、投稿文だけを機械が読める形（JSON）でも保存する。"""
    data = {
        "date": today.isoformat(), "title": title, "kind": kind, "followup": followup,
        "errors": errors, "warnings": warnings,
        "chosen": {k: chosen.get(k) for k in ("source", "id", "name", "url", "is_hidden_gem")},
        "posts": [{"type": p["type"], "angle": p["angle"], "text": p["text"],
                   "thread_parts": p.get("thread_parts") or [],
                   "reply_text": p.get("reply_text_with_link", "")} for p in result["posts"]],
        "room_comment": result["room_comment"],
    }
    path = Path(md_path).with_suffix(".json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_manual_stock(today, theme, analysis, chosen, result, errors, warnings):
    """手動投稿用のストックに1セット追加し、一覧（index.json）を作り直す。"""
    MANUAL.mkdir(parents=True, exist_ok=True)
    data = {
        "id": today.isoformat(), "date": today.isoformat(),
        "theme": theme.get("category") or theme.get("keyword", ""), "reader": analysis["reader_persona"],
        "errors": errors, "warnings": warnings, "questions": analysis["questions_for_human"],
        "item": {k: chosen.get(k) for k in ("source", "name", "url", "price", "price_note", "review_count",
                                              "review_average", "shop", "image", "is_hidden_gem")},
        "posts": [{"type": p["type"], "angle": p["angle"], "text": p["text"],
                   "thread_parts": p.get("thread_parts") or [],
                   "reply_text": p.get("reply_text_with_link", "")} for p in result["posts"]],
        "room_comment": result["room_comment"],
        "hook_alternatives": result["hook_alternatives"],
    }
    path = MANUAL / f"{today.isoformat()}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sets = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(MANUAL.glob("2*.json"), reverse=True)]
    index = {"updated": datetime.datetime.now(JST).isoformat(timespec="minutes"), "sets": sets[:MANUAL_INDEX_SIZE]}
    (MANUAL / "index.json").write_text(json.dumps(index, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✋ 手動投稿ストックに追加しました（{theme.get('category') or theme.get('keyword')}）")
    return path


def make_manual_stock(config, today, ordered, used_theme, history, pats, search, ranking, generate):
    """自動投稿とは別のテーマ・別の商品で、手動投稿用の下書きを1セット作る。失敗しても毎朝の下書きは止めない。"""
    rest = [t for t in ordered if t["id"] != used_theme["id"] and t["source"] != used_theme["source"]]
    rest += [t for t in ordered if t["id"] != used_theme["id"] and t not in rest]
    if not rest:
        return None
    try:
        theme, candidates, _ = find_candidates(config, rest, today, history, search, ranking, False)
        analysis, chosen, warn1 = analyze(config, theme, candidates, today, generate, tier="standard")
        result, errors, warnings = write_posts(config, theme, chosen, analysis, pats, today, generate,
                                               tier="standard")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 手動投稿ストックを作れませんでした（自動投稿の下書きはできています）: {e}")
        return None
    save_manual_stock(today, theme, analysis, chosen, result, errors, warn1 + warnings)
    return theme, chosen, candidates, result["room_comment"]


ROOM_SOURCES = ("ichiba", "books")  # 楽天トラベルの宿は ROOM に載せられない
ROOM_KEEP = 120
ROOM_EXTRA_SEARCHES = 3  # ROOM 用に楽天市場を追加で検索する回数の上限


def room_per_day(config, today):
    """ROOM に出す1日の件数。セール（お買い物マラソン・スーパーSALE）の前の週と期間中は多めにする。"""
    room = config.get("room", {})
    for sale in room.get("sales") or []:
        start = datetime.date.fromisoformat(str(sale["start"]))
        end = datetime.date.fromisoformat(str(sale.get("end") or sale["start"]))
        if start - datetime.timedelta(days=7) <= today <= end:
            return room.get("sale_per_day", room.get("per_day", 3)), sale.get("name", "セール")
    return room.get("per_day", 3), None


def room_more_items(config, today, ordered, history, search, used_ids, need):
    """ROOM 用に、楽天市場の商品を追加で探す（本より投稿の手間が少ないため）。"""
    found = []
    for theme in [t for t in ordered if t["source"] == "ichiba"][:ROOM_EXTRA_SEARCHES]:
        if len(found) >= need:
            break
        try:
            items = search("ichiba", theme["keyword"])
        except Exception as e:  # noqa: BLE001 - ROOM の追加分は補助なので、失敗しても続ける
            print(f"⚠️ ROOM 用の追加の検索ができませんでした: {str(e)[:100]}")
            continue
        cands = selector.filter_items(items, history, today, config["filters"])
        cands = [c for c in cands if c["id"] not in used_ids and c["id"] not in {f["id"] for f in found}]
        if cands:
            found += selector.score_items(cands, config["scoring"])[:need - len(found)]
    return found


def build_room_list(config, today, picked, extras, generate):
    """ROOM 用の一覧に今日の分を追加する。picked = すでにコメントがある (商品, コメント)、extras = 追加候補。
    楽天市場の商品を優先し、本（投稿のたびに検索の手間がかかる）は1日 max_books 件までにする。"""
    per_day, _ = room_per_day(config, today)
    max_books = config.get("room", {}).get("max_books", 1)
    entries, seen = [], set()
    books = lambda: sum(1 for i, _ in entries if i["source"] == "books")  # noqa: E731
    for item, comment in picked:
        if item["source"] == "books" and books() >= max_books:
            continue
        if item["source"] in ROOM_SOURCES and item["id"] not in seen and not checks.check_room_comment(comment):
            entries.append((item, comment))
            seen.add(item["id"])
    pool = sorted((i for i in extras if i["source"] in ROOM_SOURCES and i["id"] not in seen),
                  key=lambda i: (i["source"] != "ichiba", -i.get("score", 0)))
    more, book_slots = [], max(max_books - books(), 0)
    for item in pool:
        if len(more) >= max(per_day - len(entries), 0):
            break
        if item["id"] in {m["id"] for m in more}:
            continue
        if item["source"] == "books":
            if book_slots <= 0:
                continue
            book_slots -= 1
        more.append(item)
    if more:
        try:
            system, user = prompts.room_messages(config["account"], today, more)
            comments = {c["id"]: c["comment"] for c in generate(system, user, prompts.ROOM_SCHEMA)["comments"]}
            for item in more:
                comment = comments.get(item["id"], "")
                if comment and not checks.check_room_comment(comment):
                    entries.append((item, comment))
        except Exception as e:  # noqa: BLE001 - ROOM の追加分は補助なので、失敗しても続ける
            print(f"⚠️ ROOM 用コメントを追加で作れませんでした: {e}")
    entries = entries[:per_day]
    if not entries:
        return []
    MANUAL.mkdir(parents=True, exist_ok=True)
    path = MANUAL / "room.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    new = [{"key": f"{today.isoformat()}:{item['id']}", "date": today.isoformat(),
            **{k: item.get(k) for k in ("source", "id", "name", "url", "price", "review_count",
                                          "review_average", "shop", "image", "is_hidden_gem")},
            "comment": comment} for item, comment in entries]
    keys = {e["key"] for e in new}
    path.write_text(json.dumps(new + [e for e in old if e["key"] not in keys][:ROOM_KEEP], ensure_ascii=False,
                               indent=1) + "\n", encoding="utf-8")
    print(f"🛍️ ROOM 用に{len(new)}件追加しました")
    return [item for item, _ in entries]


# ---------------------------------------------------------------- 各モード

def update_insights(today, dry_run=False):
    """直近の投稿の反響を Threads から取ってくる。トークンや権限がなければ (None, 理由)。"""
    if dry_run:
        return None, None
    token = os.environ.get("KOTORI_THREADS_TOKEN")
    if not token:
        return None, "Threads のトークンがないため、投稿の反響は取得していません"
    posted = autopost.load_posted(DATA / "posted")
    try:  # 昨日1日分の成果（アカウント全体の反響・フォロワー）を記録する
        import stats
        stats.record_day(ThreadsClient(token), today - datetime.timedelta(days=1))
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 昨日の成果を記録できませんでした: {str(e)[:150]}")
    try:
        return insights.collect(ThreadsClient(token), posted, today, DATA / "insights" / "latest.json")
    except Exception as e:  # noqa: BLE001 - 反響は補助なので、取れなくても下書きは作る
        return None, f"投稿の反響を取得できませんでした（{str(e)[:120]}）"


def find_followup(config, today, store, drafts_dir):
    """反響が大きかった集客投稿があれば、その話題の商品を探すテーマと、書くときの補足を返す。"""
    conf = config.get("followup", {})
    if not store or not conf.get("enabled", True):
        return None
    hit = insights.pick_followup(store, today, insights.load_done(DATA / "followups.json"), conf.get("min_likes", 10))
    if not hit:
        return None
    name, likes, record = hit
    path = Path(drafts_dir) / name
    if not path.exists():
        return None
    buzz = json.loads(path.read_text(encoding="utf-8"))
    product = buzz.get("product") or {}
    if not product.get("keyword"):
        return None
    theme = themes_mod._make("反響", product.get("source") or "ichiba", product["keyword"],
                             product.get("persona") or "", category=f"反響のあった話題: {buzz.get('topic', '')}")
    theme["id"] = f"followup:{name}"
    theme["scene"] = buzz.get("topic", "")
    context = (f"この PR 投稿は、{record['date']} の集客投稿（下）に いいね{likes}件 の反響があったことを受けて書く。"
               "その話題の続きとして自然につなげる（例:「この前の◯◯の話、思った以上に反応があって」）。"
               f"\n反響のあった投稿: {buzz['posts'][0]['text']}")
    return {"theme": theme, "context": context, "draft": name, "likes": likes, "topic": buzz.get("topic", "")}


def make_extras(config, today, generate, pats, args):
    """集客投稿とつぶやきを作る。失敗しても毎朝の下書きは止めない。返り値: (本文に足す Markdown, お知らせ)"""
    drafts_dir = Path(os.environ.get("KOTORI_DRAFTS_DIR", HERE / "drafts"))
    sections, notes = [], []
    if config.get("buzz", {}).get("enabled", True):
        try:
            collect = (lambda *a: ([("お試し", "運動会の練習で毎日体操服を洗う季節")], [])) if args.dry_run else sources.collect
            buzz = extras.make_buzz(config, today, generate, pats, drafts_dir, collect)
            extras.save_json(drafts_dir, f"{today.isoformat()}-buzz.json", buzz)
            sections.append(extras.render_buzz(buzz))
        except Exception as e:  # noqa: BLE001
            notes.append(f"集客投稿を作れませんでした（朝の枠は役立つ投稿で代わりに出します）: {str(e)[:150]}")
    if config.get("casual", {}).get("enabled", True):
        try:
            repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
            neta = [] if args.dry_run else extras.fetch_neta(repo, token)
            casual = extras.make_casual(config, today, generate, drafts_dir, neta)
            extras.save_json(drafts_dir, f"{today.isoformat()}-casual.json", casual)
            sections.append(extras.render_casual(casual))
            if not args.dry_run:
                for number in casual["neta_used"]:
                    text = next(m for n, m in neta if n == number)
                    extras.close_neta(repo, token, number, text)
        except Exception as e:  # noqa: BLE001
            notes.append(f"つぶやきを作れませんでした: {str(e)[:150]}")
    return "\n".join(sections), notes


def run_daily(config, today, client, generate, args):
    history = selector.load_history(DATA / "history")
    pats = patterns_mod.fetch_patterns(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"))
    bank_created = ensure_theme_bank(config, today, generate)
    drafts_dir = Path(os.environ.get("KOTORI_DRAFTS_DIR", HERE / "drafts"))
    store, insight_note = update_insights(today, args.dry_run)

    if args.keyword:
        pool = [themes_mod._make("手動", args.source or "ichiba", args.keyword, "", category="手動指定")]
        ordered = pool
    else:
        pool = (themes_mod.load_bank(DATA / "themes", today) + themes_mod.reference_themes(pats)
                + themes_mod.fixed_themes(config))
        ordered = (themes_mod.rank(pool, history, today, config["themes"]["reuse_after_days"])
                   or themes_mod.rank(pool, [], today, 0))
        # 今の季節に合わないテーマ（暖かいのに「ダウン」など）は後回しにする
        ordered = ([t for t in ordered if not season.hits(f"{t['keyword']} {t.get('category', '')}", checks.SEASON["avoid"])]
                   + [t for t in ordered if season.hits(f"{t['keyword']} {t.get('category', '')}", checks.SEASON["avoid"])])
    followup = None if args.keyword else find_followup(config, today, store, drafts_dir)
    if followup:
        print(f"🔥 反響のあった集客投稿（いいね{followup['likes']}件）の話題で商品を探します: {followup['topic']}")
        ordered = [followup["theme"]] + ordered
    gem_day = selector.is_hidden_gem_day(today, config["hidden_gems"])
    print(f"📅 {today}: テーマ候補 {len(ordered)}個（{'💎発掘枠の日' if gem_day else '通常の日'}）／ 勝ちパターン {len(pats)}個")

    theme, candidates, notes = find_candidates(config, ordered, today, history, client.search,
                                               client.ranking_codes, gem_day)
    is_followup = bool(followup) and theme["id"] == followup["theme"]["id"]
    if followup and not is_followup:
        notes.append(f"反響のあった話題（{followup['topic']}）に合う商品が見つからなかったため、通常のテーマで書きました")
    if is_followup:
        notes.append(f"🔥 {followup['draft']} の集客投稿に いいね{followup['likes']}件 の反響があったので、その話題の商品を選びました")
    if insight_note:
        notes.append(insight_note)
    elif store:
        lines = insights.summary(store, today)
        if lines:
            notes.append("この1週間の反響: " + " ".join(x.lstrip("- ") for x in lines))
    analysis, chosen, warn1 = analyze(config, theme, candidates, today, generate)
    result, errors, warnings = write_posts(config, theme, chosen, analysis, pats, today, generate,
                                           context=followup["context"] if is_followup else None)
    if bank_created:
        notes.append(f"今月のテーマを{len(json.loads(bank_created.read_text(encoding='utf-8')))}個作りました"
                     "（data/themes）。Merge すると保存されます")
    extra_md, extra_notes = ("", []) if args.keyword else make_extras(config, today, generate, pats, args)
    notes += extra_notes
    label = theme.get("category") or theme["keyword"]
    icon = "🔥" if is_followup else ("💎" if chosen.get("is_hidden_gem") else "📝")
    title = f"{'⚠️要修正 ' if errors else ''}{icon} 投稿下書き {today.isoformat()}（{label}）"
    body = render(today, title, theme, analysis, chosen, candidates, result, errors, warn1 + warnings, notes,
                  generate.label)
    if extra_md:
        body += "\n" + extra_md
    path = save_draft(body, f"{today.isoformat()}.md")
    save_post_data(path, title, "daily", today, result, errors, warn1 + warnings, chosen,
                   followup={"draft": followup["draft"], "likes": followup["likes"]} if is_followup else None)
    if is_followup and not args.dry_run:
        insights.mark_done(DATA / "followups.json", followup["draft"])
    entries = [{"date": today.isoformat(), "source": chosen["source"], "id": chosen["id"], "name": chosen["name"],
                "theme_id": theme["id"], "theme": theme["keyword"], "origin": theme["origin"],
                "hidden_gem": chosen.get("is_hidden_gem", False)}]

    room_picked = [(chosen, result["room_comment"])]
    room_extras = [c for c in candidates if c["id"] != chosen["id"]]
    if config.get("manual_stock", {}).get("enabled") and not args.keyword:
        manual = make_manual_stock(config, today, ordered, theme, history + entries, pats,
                                   client.search, client.ranking_codes, generate)
        if manual:
            m_theme, m_chosen, m_candidates, m_room = manual
            entries.append({"date": today.isoformat(), "source": m_chosen["source"], "id": m_chosen["id"],
                            "name": m_chosen["name"], "theme_id": m_theme["id"], "theme": m_theme["keyword"],
                            "origin": "手動投稿ストック", "hidden_gem": False})
            room_picked.append((m_chosen, m_room))
            room_extras += [c for c in m_candidates if c["id"] != m_chosen["id"]]
    used_ids = {e["id"] for e in entries}
    if not args.keyword:
        per_day, sale = room_per_day(config, today)
        if sale:
            print(f"🛍️ {sale}の時期なので、ROOM の候補を{per_day}件にします")
        have = sum(1 for i, _ in room_picked if i["source"] == "ichiba") + sum(1 for c in room_extras if c["source"] == "ichiba")
        if have < per_day:
            room_extras += room_more_items(config, today, ordered, history + entries, client.search,
                                           used_ids | {c["id"] for c in room_extras}, per_day - have)
    room_items = build_room_list(config, today, room_picked, room_extras, generate)
    try:  # Pinterest のピン: 今日の PR の商品と ROOM の候補から
        pin_items = [c for c in [chosen] + room_items if c.get("url")]
        pin_items = list({c["id"]: c for c in pin_items}.values())
        pins_mod.make_pins(config, today, pin_items, generate,
                           pin_dir=(DATA / "pins") if args.dry_run else pins_mod.PIN_DIR, manual_dir=MANUAL)
    except Exception as e:  # noqa: BLE001 - ピンは補助なので、失敗しても下書きは止めない
        print(f"⚠️ Pinterest のピンを作れませんでした: {str(e)[:150]}")
    for item in room_items:
        if item["id"] not in used_ids:
            entries.append({"date": today.isoformat(), "source": item["source"], "id": item["id"],
                            "name": item["name"], "theme_id": "", "theme": "", "origin": "楽天ROOM",
                            "hidden_gem": item.get("is_hidden_gem", False)})
    if not args.dry_run:
        for entry in entries:
            selector.save_history_entry(DATA / "history", entry)
    return title, path


def run_item(config, today, client, generate, args):
    item = client.lookup(args.item_url, args.isbn)
    item = selector.score_items([dict(item, is_hidden_gem=False)], config["scoring"])[0]
    owner_note = " ".join(x for x in [args.memo, "（投稿者は実際にこの商品を使ったことがある）" if args.used else ""] if x)
    theme = {"id": "", "origin": "推し商品", "source": item["source"], "keyword": "", "category": "推し商品",
             "persona": "この商品が気になっている、子育て中の親", "scene": ""}
    analysis, chosen, warn1 = analyze(config, theme, [item], today, generate, owner_note or None)
    pats = patterns_mod.fetch_patterns(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"))
    result, errors, warnings = write_posts(config, theme, chosen, analysis, pats, today, generate, owner_note or None)
    title = f"{'⚠️要修正 ' if errors else ''}🛒 推し商品の下書き（{item['name'][:30]}）"
    body = render(today, title, theme, analysis, chosen, [item], result, errors, warn1 + warnings, [],
                  generate.label)
    suffix = os.environ.get("ISSUE_NUMBER", "manual")
    path = save_draft(body, f"{today.isoformat()}-item-{suffix}.md")
    save_post_data(path, title, "item", today, result, errors, warn1 + warnings, chosen)
    if not args.dry_run:
        selector.save_history_entry(DATA / "history", {
            "date": today.isoformat(), "source": chosen["source"], "id": chosen["id"], "name": chosen["name"],
            "theme_id": "", "theme": "", "origin": "推し商品", "hidden_gem": False})
    return title, path


def run_reference(config, generate, body_text):
    form = issue_forms.parse(body_text)
    post_text = form.get("投稿の本文", "").strip()
    if not post_text:
        raise RuntimeError("「投稿の本文」が空です。参考にしたい投稿の文章を貼り付けてください")
    system, user = prompts.reference_messages(config["account"], post_text, form.get("いいねの数", ""),
                                              form.get("ひとことメモ", ""))
    analysis = generate(system, user, prompts.REFERENCE_SCHEMA)
    comment = patterns_mod.format_comment(analysis)
    path = Path(os.environ.get("KOTORI_DRAFTS_DIR", HERE / "drafts")) / "reference_comment.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(comment, encoding="utf-8")
    print(comment)
    return path


# ---------------------------------------------------------------- お試し実行（API を使わない）

class FakeClient:
    def __init__(self):
        self.data = json.loads((HERE / "fixtures" / "sample_candidates.json").read_text(encoding="utf-8"))

    def search(self, source, keyword, hits=30):
        return [dict(c) for c in self.data if c["source"] == source]

    def ranking_codes(self, genre_id):
        return {}

    def lookup(self, url, isbn=None):
        return dict(self.data[0])


class FakeGenerator:
    label = "お試し（固定の文章）"
    notice = ""

    def __init__(self):
        self.fixtures = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))

    def research(self, system, user, tier="important"):
        return "お試しの調査メモ: 10月は運動会シーズンで、体操服の洗濯が大変という声が多い。"

    def __call__(self, system, user, schema, tier="standard"):
        name = {id(prompts.THEME_SCHEMA): "themes", id(prompts.ANALYSIS_SCHEMA): "analysis",
                id(prompts.WRITE_SCHEMA): "write", id(prompts.REFERENCE_SCHEMA): "reference",
                id(prompts.ROOM_SCHEMA): "room", id(prompts.BUZZ_SCHEMA): "buzz",
                id(prompts.CASUAL_SCHEMA): "casual", id(prompts.COMMENT_SCHEMA): "comment",
                id(prompts.PIN_SCHEMA): "pins"}[id(schema)]
        result = json.loads(json.dumps(self.fixtures[name]))
        if name == "pins":
            ids = [json.loads(line)["id"] for line in user.splitlines() if line.startswith("{")]
            result = {"pins": [dict(result["pins"][0], id=i) for i in ids]}
        if name == "room":
            ids = [json.loads(line)["id"] for line in user.splitlines() if line.startswith("{")]
            template = result["comments"][0]["comment"]
            result["comments"] = [{"id": i, "comment": template} for i in ids]
        if name == "analysis":
            first = next(json.loads(line) for line in user.splitlines() if line.startswith("{"))
            result["chosen_candidate_id"] = first["id"]
            result["ratings"][0]["id"] = first["id"]
        return result


# ----------------------------------------------------------------

def run_pins_only(config, today, generate, dry_run=False):
    """下書きを作り直さずに、ピンだけ作る（今日の ROOM の候補のうち、まだピンにしていない商品から）。"""
    room = MANUAL / "room.json"
    items = json.loads(room.read_text(encoding="utf-8")) if room.exists() else []
    pins_path = MANUAL / "pins.json"
    done = {p["key"].split(":", 1)[1] for p in json.loads(pins_path.read_text(encoding="utf-8"))} if pins_path.exists() else set()
    latest = max((i["date"] for i in items), default="")
    items = [i for i in items if i["date"] == latest and i.get("url") and i["id"] not in done]
    if not items:
        print("ピンにできる商品がありませんでした（ROOM の候補がまだないか、全部ピンにしました）")
        return 0
    made = pins_mod.make_pins(config, today, items, generate,
                              pin_dir=(DATA / "pins") if dry_run else pins_mod.PIN_DIR, manual_dir=MANUAL)
    write_output(pins=str(len(made)), notice=getattr(generate, "notice", ""))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="ことり｜投稿の下書きを作る")
    parser.add_argument("--date", help="日付を指定（例: 2026-10-10）。省略すると今日（日本時間）")
    parser.add_argument("--keyword", help="テーマを使わず、このキーワードで探す")
    parser.add_argument("--source", choices=["ichiba", "books", "travel"], help="--keyword と一緒に使う")
    parser.add_argument("--item-url", help="推し商品: 楽天の商品ページのURL")
    parser.add_argument("--isbn", help="推し商品: 本のISBN")
    parser.add_argument("--memo", default="", help="推し商品: ひとことメモ")
    parser.add_argument("--used", action="store_true", help="推し商品: 実際に使ったことがある")
    parser.add_argument("--from-issue", action="store_true", help="推し商品フォーム（ISSUE_BODY）から読む")
    parser.add_argument("--analyze-reference", action="store_true", help="参考投稿フォーム（ISSUE_BODY）を分析する")
    parser.add_argument("--generate-themes", action="store_true", help="今月のテーマを作り直す")
    parser.add_argument("--dry-run", action="store_true", help="サンプルデータで動作確認（APIを使わない）")
    parser.add_argument("--check-api", action="store_true", help="楽天APIの接続確認だけ行う")
    parser.add_argument("--pins-only", action="store_true", help="Pinterest のピンだけ、今日の ROOM の商品から作る")
    args = parser.parse_args(argv)

    global DATA, MANUAL
    config = load_config()
    if args.dry_run:
        # お試し実行ではリポジトリの記録（履歴・テーマ・勢いの記録）を書き換えない
        DATA = Path(tempfile.mkdtemp(prefix="kotori-dry-"))
        os.environ.setdefault("KOTORI_DRAFTS_DIR", str(DATA / "drafts"))
        MANUAL = DATA / "manual"
    if args.check_api:
        return check_api(config)

    today = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(JST).date()
    # 今の季節感（実際の気温）を調べて、文章作りと確認に使う
    info = season.get(today, store=DATA / "season", fetcher=(lambda d: None) if args.dry_run else season.fetch)
    prompts.SEASON_NOTE = info["note"]
    checks.SEASON.update(avoid=info["avoid"], avg_max=info["avg_max"])
    generate = FakeGenerator() if args.dry_run else llm.Generator(config.get("ai"))

    if args.analyze_reference:
        path = run_reference(config, generate, os.environ.get("ISSUE_BODY", ""))
        write_output(comment_path=path, notice=generate.notice)
        return 0
    if args.pins_only:
        return run_pins_only(config, today, generate, args.dry_run)
    if args.generate_themes:
        bank = ensure_theme_bank(config, today, generate, force=True)
        path = save_draft(render_themes(today, json.loads(bank.read_text(encoding="utf-8"))),
                          f"{today:%Y-%m}-themes.md")
        write_output(title=f"🧭 {today:%Y年%m月}のテーマ案", draft_path=path, notice=generate.notice)
        return 0

    if args.from_issue:
        form = issue_forms.parse(os.environ.get("ISSUE_BODY", ""))
        args.item_url = issue_forms.first_url(form.get("商品のURL", ""))
        args.isbn = form.get("ISBN（本の場合）", "") or None
        args.memo = form.get("ひとことメモ", "")
        args.used = issue_forms.checked(form.get("実際に使いましたか？", ""))
        if not (args.item_url or args.isbn):
            raise RakutenError("商品のURL（またはISBN）が見つかりませんでした")

    client = FakeClient() if args.dry_run else make_client(config)
    if args.item_url or args.isbn:
        title, path = run_item(config, today, client, generate, args)
    else:
        title, path = run_daily(config, today, client, generate, args)
    write_output(title=title, draft_path=path, notice=generate.notice,
                 auto_post="true" if config.get("auto_post", {}).get("enabled") else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
