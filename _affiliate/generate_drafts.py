"""毎朝の Threads 投稿下書きを作る本体。

    python _affiliate/generate_drafts.py              # 本番（楽天API と AI を使う）
    python _affiliate/generate_drafts.py --dry-run    # お試し（サンプルデータと固定の文章で動作確認）
    python _affiliate/generate_drafts.py --check-api  # 楽天API の接続確認だけ

失敗したときは終了コード1で止まる（GitHub Actions が「失敗」になり、通知が届く）。
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import llm  # noqa: E402
import selector  # noqa: E402
from rakuten import RakutenClient  # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9))
MAX_ATTEMPTS = 3


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


def check_api(config):
    """各APIに1回ずつ問い合わせて、つながるか確かめる。"""
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
    if not os.environ.get("RAKUTEN_AFFILIATE_ID"):
        print("⚠️ RAKUTEN_AFFILIATE_ID が未設定です。リンクから購入されても報酬になりません")
    return 1 if failed else 0


def fetch_candidates(config, pillar, first_query, today, history, search):
    """今日のキーワードで候補が見つからなければ、同じ柱の別キーワードを順に試す。"""
    queries = pillar["queries"]
    start = queries.index(first_query)
    for offset in range(len(queries)):
        query = queries[(start + offset) % len(queries)]
        items = search(pillar["source"], query["keyword"])
        candidates = selector.select_candidates(items, history, today, config["filters"])
        print(f"🔎 「{query['keyword']}」: {len(items)}件取得 → 条件に合う候補 {len(candidates)}件")
        if candidates:
            return query, candidates
    raise RuntimeError(f"柱「{pillar['label']}」のどのキーワードでも条件に合う候補が見つかりませんでした")


def write_posts(config, pillar, query, candidates, today, generate):
    """AI に書かせて自動チェック。引っかかったら理由を伝えて書き直させる。"""
    feedback = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        system, user = llm.build_messages(config["account"], pillar, query, candidates, today, feedback)
        result = generate(system, user)
        errors, warnings = checks.check_posts(result["posts"])
        ids = {c["id"] for c in candidates}
        if result["chosen_candidate_id"] not in ids:
            errors.append(f"chosen_candidate_id「{result['chosen_candidate_id']}」が候補のidにありません")
        print(f"✍️ 下書き {attempt}回目: エラー{len(errors)}件・要確認{len(warnings)}件")
        if not errors:
            return result, errors, warnings
        feedback = errors
    return result, errors, warnings


def attach_link(result, candidates):
    chosen = next((c for c in candidates if c["id"] == result["chosen_candidate_id"]), candidates[0])
    for post in result["posts"]:
        if post["type"] == "pr":
            post["reply_text_with_link"] = post["reply_text"].replace(checks.LINK_PLACEHOLDER, chosen["url"])
    return chosen


def _code(text):
    return f"```text\n{text.strip()}\n```"


def render(today, pillar, query, result, chosen, candidates, errors, warnings, provider_label):
    out = [f"# 📝 {today.isoformat()} の投稿下書き（{pillar['label']}）", ""]
    out += [f"> 想定読者: {query['persona']}", f"> 検索キーワード: {query['keyword']} ／ 下書き: {provider_label}", ""]

    out.append("## 自動チェック")
    if errors:
        out.append("❌ **直してから投稿してください:**")
        out += [f"- {e}" for e in errors]
    if warnings:
        out.append("⚠️ **確認してください:**")
        out += [f"- {w}" for w in warnings]
    if not errors and not warnings:
        out.append("✅ PR表記・リンク1本・NGワード・文字数のチェックはすべて合格")
    if not chosen.get("is_affiliate_url"):
        out.append("⚠️ リンクがアフィリエイトURLになっていません（RAKUTEN_AFFILIATE_ID を確認してください）")
    out.append("")

    for n, post in enumerate(result["posts"], 1):
        kind = "PR・リンクあり" if post["type"] == "pr" else "リンクなし"
        out += [f"## 投稿{n}（{kind}）— {post['angle']}", "", "**本文**", _code(post["text"]), ""]
        if post["type"] == "pr":
            out += ["**返信**（投稿したあと、この投稿への返信として貼る）",
                    _code(post.get("reply_text_with_link", post["reply_text"])), ""]

    price = f"{chosen['price']:,}円" + (f"（{chosen['price_note']}）" if chosen.get("price_note") else "")
    out += [
        "## 紹介する商品", "",
        f"- **{chosen['name']}**",
        f"- 価格: {price}　※{today.isoformat()} 取得時点",
        f"- レビュー: ★{chosen['review_average']}（{chosen['review_count']:,}件）／ {chosen['shop']}",
        f"- リンク: {chosen['url']}",
        f"- 選んだ理由: {result['why_this_candidate']}",
    ]
    if chosen.get("image"):
        out += ["", f"<img src=\"{chosen['image']}\" width=\"200\">"]
    out += ["", "## PR投稿の書き出し 別案"]
    out += [f"{i}. {h}" for i, h in enumerate(result["hook_alternatives"], 1)]

    others = [c for c in candidates if c["id"] != chosen["id"]]
    if others:
        out += ["", "## ほかの候補", "", "| 商品 | 価格 | レビュー |", "|---|---|---|"]
        out += [f"| {c['name'][:40]} | {c['price']:,}円 | ★{c['review_average']}（{c['review_count']:,}件） |"
                for c in others]

    out += [
        "", "## 投稿のしかた",
        "1. 投稿1〜3は時間をあけて投稿（例: 朝・昼・夜）。PR投稿を連続させない",
        "2. 投稿3を投稿したら、その投稿の「返信」に返信文を貼る（他の人の投稿には貼らない）",
        "3. 実際の状況と違う部分は、自由に書き換えてOK",
        "",
        "この PR を **Merge** すると、紹介した商品が履歴に記録され、しばらく同じ商品は選ばれません。"
        "使わなかった日は **Close** してください。",
    ]
    return "\n".join(out) + "\n"


def dry_run_fixtures():
    data = json.loads((HERE / "fixtures" / "sample_candidates.json").read_text(encoding="utf-8"))
    sample_posts = json.loads((HERE / "fixtures" / "sample_llm_output.json").read_text(encoding="utf-8"))

    def search(source, keyword):
        return [c for c in data if c["source"] == source]

    def generate(system, user):
        result = json.loads(json.dumps(sample_posts))
        first = next(json.loads(line) for line in user.splitlines() if line.startswith("{"))
        result["chosen_candidate_id"] = first["id"]
        return result

    return search, generate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Threads 投稿の下書きを作る")
    parser.add_argument("--date", help="日付を指定（例: 2026-10-10）。省略すると今日（日本時間）")
    parser.add_argument("--pillar", help="テーマの柱を指定（config.yaml の id）")
    parser.add_argument("--dry-run", action="store_true", help="サンプルデータで動作確認（APIを使わない）")
    parser.add_argument("--check-api", action="store_true", help="楽天APIの接続確認だけ行う")
    parser.add_argument("--out-dir", default=str(HERE / "drafts"), help="下書きの保存先")
    parser.add_argument("--no-history", action="store_true", help="紹介履歴を更新しない")
    args = parser.parse_args(argv)

    config = load_config()
    if args.check_api:
        return check_api(config)

    today = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(JST).date()
    history_dir = HERE / "data" / "history"
    history = selector.load_history(history_dir)
    pillar, query = selector.pick_theme(config["pillars"], today, args.pillar)
    print(f"📅 {today}: 今日のテーマは「{pillar['label']}」")

    if args.dry_run:
        search, generate = dry_run_fixtures()
        provider_label = "お試し（固定の文章）"
    else:
        search, generate = make_client(config).search, llm.generate
        provider_label = "Claude" if llm.provider() == "claude" else "Gemini"

    query, candidates = fetch_candidates(config, pillar, query, today, history, search)
    result, errors, warnings = write_posts(config, pillar, query, candidates, today, generate)
    chosen = attach_link(result, candidates)
    body = render(today, pillar, query, result, chosen, candidates, errors, warnings, provider_label)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_path = out_dir / f"{today.isoformat()}.md"
    draft_path.write_text(body, encoding="utf-8")
    title = f"{'⚠️要修正 ' if errors else ''}📝 投稿下書き {today.isoformat()}（{pillar['label']}）"
    print(f"💾 {draft_path} に保存しました")

    if not (args.no_history or args.dry_run):
        selector.save_history_entry(history_dir, {
            "date": today.isoformat(), "source": chosen["source"], "id": chosen["id"],
            "name": chosen["name"], "pillar": pillar["id"]})

    # GitHub Actions が PR を作るときに使う
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"title={title}\n")
            f.write(f"draft_path={draft_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
