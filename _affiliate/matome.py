"""まとめサイトの記事を作る（週1回）: 「〇〇で買ってよかった物まとめ」を、楽天の評判のよい商品から書く。

Threads の投稿は流れていくが、まとめ記事は検索や Pinterest から人が来続ける「資産」になる。
  ・テーマ: 今の時期の行事（入学準備・クリスマスなど）を優先。なければ、いつものテーマから。60日以内に書いたテーマは避ける
  ・商品: 楽天で探して、レビューの数と評価で絞り、似た商品を外して最大10個 → AI が4〜6個選んで記事にする
  ・記事は _posts/ に保存され、サイト（https://keiyamada-ui.github.io/）に自動で載る

    python _affiliate/matome.py                         # テーマを自動で選ぶ
    python _affiliate/matome.py --keyword "お名前シール 入学準備"
    python _affiliate/matome.py --dry-run               # AI と楽天を使わず、形だけ確かめる
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import checks  # noqa: E402
import events  # noqa: E402
import generate_drafts as gd  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
import rewrites  # noqa: E402
import selector  # noqa: E402
import themes as themes_mod  # noqa: E402

POSTS = HERE.parent / "_posts"
HISTORY = HERE / "data" / "matome.json"
JST = datetime.timezone(datetime.timedelta(hours=9))
REUSE_DAYS = 60
MAX_CANDIDATES = 10


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def pick_topics(config, today, history):
    """書くテーマの候補を、優先順に返す: [(検索先, 検索語, 読む人, 行事名)]"""
    since = (today - datetime.timedelta(days=REUSE_DAYS)).isoformat()
    used = {h["keyword"] for h in history if h.get("date", "") >= since}
    out = []
    for e in events.active(today):
        out += [(s, k, p, e["name"]) for s, k, p in e["keywords"]]
    bank = themes_mod.load_bank(HERE / "data" / "themes", today) + themes_mod.fixed_themes(config)
    out += [(t["source"], t["keyword"], t.get("persona", ""), "") for t in bank]
    seen, topics = set(), []
    for t in out:
        if t[1] in used or t[1] in seen or t[0] not in ("ichiba", "books"):
            continue
        seen.add(t[1])
        topics.append(t)
    return topics


def candidates(config, items, today):
    """評判のよい商品を、似たものを外して最大10個。"""
    cands = selector.filter_items(items, [], today, config["filters"])
    if len(cands) < 4:
        cands = selector.filter_items(items, [], today, dict(config["filters"], **gd.RELAXED_FILTERS))
    out = []
    for c in selector.score_items(cands, config["scoring"]):
        if c.get("url") and c.get("image") and not any(gd.similar(c["name"], x["name"]) for x in out):
            out.append(c)
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def _slug(text, today):
    s = re.sub(r"[^a-z0-9-]+", "-", (text or "").lower()).strip("-")[:50].strip("-")
    return s or f"matome-{today:%m%d}"


def _q(text):
    """front matter に安全に入れる（JSON の文字列は YAML としても読める）。"""
    return json.dumps(str(text), ensure_ascii=False)


def render(result, picked, today, event, now=None):
    """記事（Markdown）を作る。商品はカードで見せ、リンクは楽天アフィリエイトのリンク。"""
    now = now or datetime.datetime.now(JST)
    lines = ["---", f"title: {_q(result['title'])}", f"description: {_q(result['description'])}",
             f"date: {now:%Y-%m-%d %H:%M:%S} +0900"]
    if event:
        lines.append(f"event: {_q(event)}")
    lines += [f"image: {_q(picked[0][0]['image'])}", "---", "", result["intro"].strip(), ""]
    for n, (item, text) in enumerate(picked, 1):
        price = f"{item['price']:,}円（{today.month}/{today.day}時点）" if item.get("price") else ""
        rating = f"★{item['review_average']}（{item['review_count']:,}件）" if item.get("review_count") else ""
        spec = "・".join(x for x in (price, rating) if x)
        name = html.escape(item["name"][:80])
        lines += [f"## {n}. {text['heading'].strip()}", "",
                  f'<div class="item"><img src="{html.escape(item["image"])}" alt="{name}" loading="lazy">'
                  f'<div><p class="name">{name}</p><p class="spec">{html.escape(spec)}</p>'
                  f'<a class="buy" href="{html.escape(item["url"])}" target="_blank" rel="sponsored noopener">楽天で見る</a></div></div>',
                  "", text["body"].strip(), ""]
        if text.get("good_for"):
            lines += [f'<p class="good">こんな人に: {html.escape(text["good_for"].strip())}</p>', ""]
    lines += ["## まとめ", "", result["closing"].strip(), ""]
    return "\n".join(lines)


def _check(result):
    whole = "\n".join([result["title"], result["description"], result["intro"], result["closing"]]
                      + [i["heading"] + i["body"] + i["good_for"] for i in result["items"]])
    return [f"NGワード「{w}」— {r}" for w, r in checks._ng_hits(whole)] + checks._ai_smell(whole)


def write(config, today, generate, search, keyword=None, source="ichiba", history_path=HISTORY, posts_dir=POSTS):
    history = _load(history_path, [])
    topics = [(source, keyword, "", "")] if keyword else pick_topics(config, today, history)
    for src, kw, persona, event in topics[:6]:
        try:
            items = search(src, kw)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ 「{kw}」を検索できませんでした: {str(e)[:100]}")
            continue
        cands = candidates(config, items, today)
        print(f"🔎 「{kw}」: {len(items)}件 → 記事の候補 {len(cands)}件")
        if len(cands) >= 4:
            break
    else:
        print("⚠️ 記事にできる商品が見つかりませんでした")
        return None
    by_id = {c["id"]: c for c in cands}
    feedback, result, picked = None, None, []
    for _ in range(2):
        system, user = prompts.matome_messages(config["account"], today, kw, persona or "子育て中の親", event, cands)
        if feedback:
            user += "\n\n前回の記事は次のチェックに引っかかりました。直して書き直してください:\n" + "\n".join(f"- {f}" for f in feedback)
        result = generate(system, user, prompts.MATOME_SCHEMA, tier="important")
        picked = [(by_id[i["id"]], i) for i in result["items"] if i["id"] in by_id][:6]
        feedback = _check(result) + ([] if len(picked) >= 3 else ["商品は渡された id から3つ以上選んでください"])
        if not feedback:
            break
    if len(picked) < 3:
        print("⚠️ 記事にできませんでした: " + " / ".join(feedback))
        return None
    slug = _slug(result["slug"], today)
    posts_dir = Path(posts_dir)
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{today.isoformat()}-{slug}.md"
    n = 2
    while path.exists():
        path = posts_dir / f"{today.isoformat()}-{slug}-{n}.md"
        n += 1
    path.write_text(render(result, picked, today, event), encoding="utf-8")
    history.append({"date": today.isoformat(), "keyword": kw, "title": result["title"], "file": path.name,
                    "warnings": feedback})
    Path(history_path).parent.mkdir(parents=True, exist_ok=True)
    Path(history_path).write_text(json.dumps(history[-200:], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"✅ まとめ記事を書きました: {result['title']}（{path.name}）")
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keyword", default="")
    p.add_argument("--source", default="ichiba", choices=["ichiba", "books"])
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    config = gd.load_config()
    today = datetime.datetime.now(JST).date()
    prompts.REWRITE_NOTE = rewrites.note(HERE / "data" / "rewrites.json")
    if a.dry_run:
        print("🧪 お試し: テーマの候補 → " + " / ".join(t[1] for t in pick_topics(config, today, _load(HISTORY, []))[:5]))
        return 0
    generate = llm.Generator(config.get("ai"))
    client = gd.make_client(config)
    path = write(config, today, generate, client.search, a.keyword.strip() or None, a.source)
    gd.write_output(path=str(path or ""), notice=generate.notice)
    return 0 if path else 1


if __name__ == "__main__":
    sys.exit(main())
