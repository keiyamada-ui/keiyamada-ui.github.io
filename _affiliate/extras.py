"""集客投稿（バズ狙い）・つぶやき・ネタ帳。毎朝の下書き作りの中で呼ばれる。

    集客投稿: ニュース・トレンドの見出しを集める → Claude（最上位）がネット検索して深掘り →
              型の違う3案を書いて採点 → 一番良い案を自動チェック → drafts/日付-buzz.json
    つぶやき: 短い日常の投稿。Gemini（無料）で書く。ネタ帳のメモがあれば本人の出来事として使う
              → drafts/日付-casual.json
"""

import json
from pathlib import Path

import requests

import checks
import issue_forms
import prompts
import sources

MAX_ATTEMPTS = 3
NETA_LABEL = "ネタ帳"
NETA_FIELD = "あったこと"
NETA_TITLE = "[ネタ帳]"


def _recent(drafts_dir, suffix, key, days=14):
    out = []
    for path in sorted(Path(drafts_dir).glob(f"*-{suffix}.json"))[-days:]:
        data = json.loads(path.read_text(encoding="utf-8"))
        out += data.get(key) if isinstance(data.get(key), list) else [data.get(key, "")]
    return [x for x in out if x]


# ---------------------------------------------------------------- 集客投稿

def _total(d):
    return d["empathy"] + d["reply"] + d["share"] + d["human"]


def make_buzz(config, today, generate, pats, drafts_dir, collect=sources.collect):
    headlines, failed = collect(config.get("buzz", {}).get("feeds"), config.get("buzz", {}).get("queries"))
    print(f"📰 ニュース・トレンドの見出し {len(headlines)}件（取得できなかった出どころ {len(failed)}件）")
    recent = _recent(drafts_dir, "buzz", "topic")
    system, user = prompts.buzz_research_messages(config["account"], today,
                                                  [f"{t}（{n}）" for n, t in headlines], recent)
    research = generate.research(system, user, tier="important")

    feedback, result, chosen, errors = None, None, None, []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        system, user = prompts.buzz_write_messages(config["account"], today, research, pats, feedback)
        result = generate(system, user, prompts.BUZZ_SCHEMA, tier="important")
        drafts = result["drafts"]
        if not drafts:
            feedback = ["下書きが1つもありません。3つ書いてください"]
            continue
        best = min(max(result["best_index"], 0), len(drafts) - 1)
        # AI が選んだ案を優先し、チェックに通らなければ点数の高い順に次の案を使う
        order = [best] + sorted((i for i in range(len(drafts)) if i != best), key=lambda i: -_total(drafts[i]))
        problems = {i: checks.check_simple_post(drafts[i]["text"], "集客投稿", 20, 250) for i in order}
        if attempt == MAX_ATTEMPTS:  # 言い回しのくり返しが直りきらなくても、投稿は止めない
            problems = {i: checks.soften(p)[0] for i, p in problems.items()}
        chosen = next((i for i in order if not problems[i]), None)
        print(f"📣 集客投稿 {attempt}回目: {len(drafts)}案中 合格{sum(1 for p in problems.values() if not p)}案")
        if chosen is not None:
            errors = []
            break
        chosen, errors = best, problems[best]
        feedback = errors
    pick = result["drafts"][chosen]
    tag = result["topic_tag"].strip().lstrip("#＃")[:50]
    return {
        "date": today.isoformat(), "kind": "buzz", "title": f"📣 集客投稿 {today.isoformat()}（{result['topic']}）",
        "errors": errors, "warnings": [],
        "topic": result["topic"], "why_now": result["why_now"], "parent_emotion": result["parent_emotion"],
        "topic_tag": tag,
        "product": {"keyword": result["product_keyword"], "source": result["product_source"],
                    "persona": result["product_persona"]},
        "posts": [{"type": "buzz", "angle": pick["pattern"], "text": pick["text"], "thread_parts": [],
                   "reply_text": "", "topic_tag": tag}],
        "alternatives": [{"pattern": d["pattern"], "text": d["text"], "score": _total(d), "weak_point": d["weak_point"]}
                         for i, d in enumerate(result["drafts"]) if i != chosen],
        "score": {k: pick[k] for k in ("empathy", "reply", "share", "human")},
        "research": research[:4000], "sources_failed": failed, "headline_count": len(headlines),
    }


def render_buzz(data):
    out = ["## 📣 集客投稿（朝・リンクなし・宣伝なし）", ""]
    if data["errors"]:
        out += ["❌ **自動チェックに通らなかったため、自動投稿しません:**"] + [f"- {e}" for e in data["errors"]] + [""]
    post = data["posts"][0]
    s = data["score"]
    out += [f"- 話題: {data['topic']}", f"- なぜ今: {data['why_now']}", f"- 親の本音: {data['parent_emotion']}",
            f"- 型: {post['angle']} ／ AI の採点: 共感{s['empathy']}・返信{s['reply']}・拡散{s['share']}・人間らしさ{s['human']}（各10点）",
            f"- トピックタグ: {data['topic_tag'] or 'なし'}",
            f"- 反響があったら紹介する商品: 楽天で「{data['product']['keyword']}」（{data['product']['source']}）", "",
            "```text", post["text"].strip(), "```", ""]
    if data["alternatives"]:
        out += ["<details><summary>ほかの案</summary>", ""]
        for a in data["alternatives"]:
            out += [f"**{a['pattern']}**（{a['score']}点・弱点: {a['weak_point']}）", "```text", a["text"].strip(), "```", ""]
        out += ["</details>", ""]
    out += ["<details><summary>🔎 AI が調べたメモ</summary>", "", data["research"], "", "</details>", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- ネタ帳

def _owner(repo):
    return (repo or "").split("/")[0]


def fetch_neta(repo, token, session=None, limit=5):
    """持ち主が書いた、開いている「ネタ帳」の Issue を古い順に返す: [(番号, メモ)]。"""
    if not (repo and token):
        return []
    http = session or requests
    try:
        res = http.get(f"https://api.github.com/repos/{repo}/issues", timeout=30,
                       headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                       params={"state": "open", "per_page": 50, "direction": "asc"})
        res.raise_for_status()
        out = []
        for issue in res.json():
            labels = {lb.get("name") for lb in issue.get("labels", [])}
            if NETA_LABEL not in labels and not (issue.get("title") or "").startswith(NETA_TITLE):
                continue
            if issue["user"]["login"] != _owner(repo) or "pull_request" in issue:
                continue  # 公開リポジトリなので、持ち主以外が書いたものは使わない
            memo = issue_forms.parse(issue.get("body") or "").get(NETA_FIELD, "").strip()
            if memo:
                out.append((issue["number"], memo[:300]))
        return out[:limit]
    except Exception as e:  # noqa: BLE001 - ネタ帳は補助なので、読めなくても続ける
        print(f"⚠️ ネタ帳を読み込めませんでした（なしで続けます）: {e}")
        return []


def close_neta(repo, token, number, text, session=None, moved=False):
    http = session or requests
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    body = (f"📝 体験メモに移しました（管理画面の「入力 → 体験メモ」で見られます）:\n\n> {text}" if moved
            else f"✅ このネタでつぶやきを作りました（今日の投稿枠で自動投稿されます）:\n\n> {text}")
    try:
        http.post(f"https://api.github.com/repos/{repo}/issues/{number}/comments", headers=headers, timeout=30,
                  json={"body": body})
        http.patch(f"https://api.github.com/repos/{repo}/issues/{number}", headers=headers, timeout=30,
                   json={"state": "closed", "state_reason": "completed"})
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ ネタ帳 #{number} を閉じられませんでした: {e}")


# ---------------------------------------------------------------- つぶやき

def make_casual(config, today, generate, drafts_dir, neta):
    count = config.get("casual", {}).get("per_day", 3)
    recent = [p["text"] for path in sorted(Path(drafts_dir).glob("*-casual.json"))[-5:]
              for p in json.loads(path.read_text(encoding="utf-8"))["posts"]]
    memos = [m for _, m in neta]
    feedback, good, errors = None, [], []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        system, user = prompts.casual_messages(config["account"], today, count, memos, recent, feedback)
        result = generate(system, user, prompts.CASUAL_SCHEMA, tier="casual")
        good, errors = [], []
        for n, post in enumerate(result["posts"], 1):
            problems = checks.check_simple_post(post["text"], f"つぶやき{n}", 5, 140)
            if attempt == MAX_ATTEMPTS:
                problems = checks.soften(problems)[0]
            (errors.extend(problems) if problems else good.append(post))
        print(f"💬 つぶやき {attempt}回目: {len(result['posts'])}本中 合格{len(good)}本")
        if len(good) >= count:
            break
        feedback = errors or [f"つぶやきが{len(good)}本しかありません。{count}本書いてください"]
    good = good[:count]
    used = []
    for post in good:
        number = next((num for num, memo in neta if post["memo_used"] and post["memo_used"].strip() in memo), None)
        if number is not None:
            used.append(number)
    return {
        "date": today.isoformat(), "kind": "casual", "title": f"💬 つぶやき {today.isoformat()}",
        "errors": [] if good else errors, "warnings": [],
        "posts": [{"type": "casual", "angle": "ネタ帳" if p["memo_used"] else "日常", "text": p["text"],
                   "thread_parts": [], "reply_text": ""} for p in good],
        "neta_used": used,
    }


def render_casual(data):
    out = ["## 💬 つぶやき（短い日常の投稿・リンクなし）", ""]
    if not data["posts"]:
        out += ["❌ 今日は作れませんでした。"] + [f"- {e}" for e in data["errors"]] + [""]
    for n, post in enumerate(data["posts"], 1):
        mark = "（📝 体験メモから）" if post["angle"] == "ネタ帳" else ""
        out += [f"**つぶやき{n}**{mark}", "```text", post["text"].strip(), "```", ""]
    return "\n".join(out)


def save_json(drafts_dir, filename, data):
    path = Path(drafts_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
