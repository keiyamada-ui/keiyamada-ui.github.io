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

import checks  # noqa: E402
import issue_forms  # noqa: E402
import llm  # noqa: E402
import patterns as patterns_mod  # noqa: E402
import prompts  # noqa: E402
import selector  # noqa: E402
import themes as themes_mod  # noqa: E402
from rakuten import RakutenClient, RakutenError  # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9))
MAX_ATTEMPTS = 3
DATA = HERE / "data"
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
    if not os.environ.get("RAKUTEN_AFFILIATE_ID"):
        print("⚠️ RAKUTEN_AFFILIATE_ID が未設定です。リンクから購入されても報酬になりません")
    return 1 if failed else 0


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

def find_candidates(config, ordered_themes, today, history, search, ranking, gem_day):
    notes = []
    for theme in ordered_themes[:8]:
        items = search(theme["source"], theme["keyword"])
        trend_map = selector.trends(DATA / "snapshots", today, items)
        selector.save_snapshot(DATA / "snapshots", today, items)
        gem = config["hidden_gems"] if gem_day else None
        cands = selector.filter_items(items, history, today, config["filters"], gem)
        if gem and not cands:
            cands = selector.filter_items(items, history, today, config["filters"])
            notes.append("今日は発掘枠の日でしたが、条件に合う商品がなかったため通常の候補から選びました")
        print(f"🔎 「{theme['keyword']}」: {len(items)}件取得 → 条件に合う候補 {len(cands)}件")
        if not cands:
            continue
        ranks = {}
        if theme["source"] == "ichiba":
            for genre in list(dict.fromkeys(c.get("genre_id") for c in cands if c.get("genre_id")))[:2]:
                try:
                    ranks.update(ranking(genre))
                except Exception as e:  # noqa: BLE001 - ランキングは補助なので、取れなくても続ける
                    notes.append(f"ランキングを取得できませんでした（需要はレビュー件数で判定）: {str(e)[:80]}")
                    break
        scored = selector.score_items(cands, config["scoring"], trend_map, ranks)
        return theme, scored[: config["filters"]["max_candidates"]], notes
    raise RuntimeError("どのテーマでも条件に合う候補が見つかりませんでした（config.yaml の filters を緩めてください）")


# ---------------------------------------------------------------- AI による分析と執筆

def analyze(config, theme, candidates, today, generate, owner_note=None):
    system, user = prompts.analysis_messages(config["account"], theme, candidates, today, owner_note)
    analysis = generate(system, user, prompts.ANALYSIS_SCHEMA)
    ids = [c["id"] for c in candidates]
    warnings = []
    if analysis["chosen_candidate_id"] not in ids:
        warnings.append(f"AI が候補にない商品（{analysis['chosen_candidate_id']}）を選んだため、点数1位の商品にしました")
        analysis["chosen_candidate_id"] = ids[0]
    if analysis["angles"]:
        analysis["best_angle_index"] = min(max(analysis["best_angle_index"], 0), len(analysis["angles"]) - 1)
    chosen = next(c for c in candidates if c["id"] == analysis["chosen_candidate_id"])
    return analysis, chosen, warnings


def write_posts(config, theme, chosen, analysis, pats, today, generate, owner_note=None):
    """AI に書かせて自動チェック。引っかかったら理由を伝えて書き直させる。"""
    feedback = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        system, user = prompts.write_messages(config["account"], theme, chosen, analysis, pats,
                                              today, owner_note, feedback)
        result = generate(system, user, prompts.WRITE_SCHEMA)
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


# ---------------------------------------------------------------- 各モード

def run_daily(config, today, client, generate, args):
    history = selector.load_history(DATA / "history")
    pats = patterns_mod.fetch_patterns(os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"))
    bank_created = ensure_theme_bank(config, today, generate)

    if args.keyword:
        pool = [themes_mod._make("手動", args.source or "ichiba", args.keyword, "", category="手動指定")]
        ordered = pool
    else:
        pool = (themes_mod.load_bank(DATA / "themes", today) + themes_mod.reference_themes(pats)
                + themes_mod.fixed_themes(config))
        ordered = (themes_mod.rank(pool, history, today, config["themes"]["reuse_after_days"])
                   or themes_mod.rank(pool, [], today, 0))
    gem_day = selector.is_hidden_gem_day(today, config["hidden_gems"])
    print(f"📅 {today}: テーマ候補 {len(ordered)}個（{'💎発掘枠の日' if gem_day else '通常の日'}）／ 勝ちパターン {len(pats)}個")

    theme, candidates, notes = find_candidates(config, ordered, today, history, client.search,
                                               client.ranking_codes, gem_day)
    analysis, chosen, warn1 = analyze(config, theme, candidates, today, generate)
    result, errors, warnings = write_posts(config, theme, chosen, analysis, pats, today, generate)
    if bank_created:
        notes.append(f"今月のテーマを{len(json.loads(bank_created.read_text(encoding='utf-8')))}個作りました"
                     "（data/themes）。Merge すると保存されます")
    label = theme.get("category") or theme["keyword"]
    title = f"{'⚠️要修正 ' if errors else ''}{'💎' if chosen.get('is_hidden_gem') else '📝'} 投稿下書き {today.isoformat()}（{label}）"
    body = render(today, title, theme, analysis, chosen, candidates, result, errors, warn1 + warnings, notes,
                  generate.label)
    path = save_draft(body, f"{today.isoformat()}.md")
    if not args.dry_run:
        selector.save_history_entry(DATA / "history", {
            "date": today.isoformat(), "source": chosen["source"], "id": chosen["id"], "name": chosen["name"],
            "theme_id": theme["id"], "theme": theme["keyword"], "origin": theme["origin"],
            "hidden_gem": chosen.get("is_hidden_gem", False)})
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

    def __call__(self, system, user, schema):
        name = {id(prompts.THEME_SCHEMA): "themes", id(prompts.ANALYSIS_SCHEMA): "analysis",
                id(prompts.WRITE_SCHEMA): "write", id(prompts.REFERENCE_SCHEMA): "reference"}[id(schema)]
        result = json.loads(json.dumps(self.fixtures[name]))
        if name == "analysis":
            first = next(json.loads(line) for line in user.splitlines() if line.startswith("{"))
            result["chosen_candidate_id"] = first["id"]
            result["ratings"][0]["id"] = first["id"]
        return result


# ----------------------------------------------------------------

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
    args = parser.parse_args(argv)

    global DATA
    config = load_config()
    if args.dry_run:
        # お試し実行ではリポジトリの記録（履歴・テーマ・勢いの記録）を書き換えない
        DATA = Path(tempfile.mkdtemp(prefix="kotori-dry-"))
        os.environ.setdefault("KOTORI_DRAFTS_DIR", str(DATA / "drafts"))
    if args.check_api:
        return check_api(config)

    today = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(JST).date()
    generate = FakeGenerator() if args.dry_run else llm.Generator()

    if args.analyze_reference:
        path = run_reference(config, generate, os.environ.get("ISSUE_BODY", ""))
        write_output(comment_path=path, notice=generate.notice)
        return 0
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
    write_output(title=title, draft_path=path, notice=generate.notice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
