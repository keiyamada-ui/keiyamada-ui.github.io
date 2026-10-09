"""AI（Gemini または Claude）に投稿の下書きを書いてもらう。

どちらを使うかは環境変数で切り替える:
- ANTHROPIC_API_KEY があれば Claude、なければ Gemini（LLM_PROVIDER で明示もできる）
"""

import json
import os

import requests

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
# Gemini の具体的なモデル名は頻繁に入れ替わるため、常に最新の Flash を指す別名を使う
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(RuntimeError):
    pass


POST_SCHEMA = {
    "type": "object",
    "properties": {
        "chosen_candidate_id": {"type": "string"},
        "why_this_candidate": {"type": "string"},
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["value", "pr"]},
                    "angle": {"type": "string"},
                    "text": {"type": "string"},
                    "reply_text": {"type": "string"},
                },
                "required": ["type", "angle", "text", "reply_text"],
                "additionalProperties": False,
            },
        },
        "hook_alternatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["chosen_candidate_id", "why_this_candidate", "posts", "hook_alternatives"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
あなたは Threads アカウント「{name}」の投稿を下書きするライターです。
アカウントの人物像: {persona}

# このアカウントの書き方
- 読者は子育て中の親。友達に話すような、やわらかい日本語で書く。
- 「誰が＋どんな条件で探しているか」を書き出しで具体的に示し、その人の悩みに寄り添う。
- 商品は「レビューを読み比べて分かったこと」として紹介する。
  {name}がその商品を実際に使った・泊まったとは書かない（体験していない事実を作らない）。
- 数字（価格・レビュー件数・評価）は渡された情報のものだけを使い、作らない。価格は変わるので「記事作成時点で」と添える。
- 1投稿は Threads の上限を考えて 350 文字以内を目安にする。

# 必ず守るルール（違反すると投稿できません）
- 投稿は3本: リンクなしの役立つ投稿（type: "value"）を2本と、商品紹介（type: "pr"）を1本。
- value 投稿はテーマに関係する豆知識・選び方・共感の話にする。商品名もリンクも入れない。reply_text は空文字。
- pr 投稿の本文（text）の1行目に必ず「PR」を入れる（例:「【PR】」で始める）。本文にはリンクを入れない。
- pr 投稿の reply_text（自分の投稿にぶら下げる返信）に、リンクの置き場所として {{{{LINK}}}} をちょうど1回だけ書き、「#PR」も入れる。
  URL そのものは絶対に書かない（後でプログラムが正しいアフィリエイトURLを差し込む）。
- 効果を断定しない（「必ず」「絶対」「頭が良くなる」「上手くなる」など）。「〜しやすい」「〜という声が多い」のように事実と口コミの範囲で書く。
- 「稼げる」「収益」「副業」「最安」「No.1」「公式」は使わない。
- ディズニーなど他社の商標を、公式と誤解させる形で使わない（「ディズニー周辺」「パーク近く」のような説明はOK）。
- ハッシュタグは各投稿1つまで。絵文字は控えめに（各投稿2つまで）。

# 出力
JSON だけを返す。形式:
{{"chosen_candidate_id": "pr投稿で紹介する候補のid",
 "why_this_candidate": "その候補を選んだ理由（人間の確認用、1〜2文）",
 "posts": [{{"type": "value", "angle": "切り口の名前", "text": "...", "reply_text": ""}},
           {{"type": "value", "angle": "...", "text": "...", "reply_text": ""}},
           {{"type": "pr", "angle": "レビュー型・比較型・悩み訴求型など", "text": "...", "reply_text": "...{{{{LINK}}}}...#PR"}}],
 "hook_alternatives": ["pr投稿の別の書き出し案を3つ"]}}
"""


def build_messages(account, pillar, query, candidates, today, feedback=None):
    system = SYSTEM_PROMPT.format(name=account["name"], persona=account["persona"])
    lines = [
        f"今日の日付: {today.isoformat()}",
        f"今日のテーマ: {pillar['label']}",
        f"想定する読者: {query['persona']}",
        "",
        "紹介候補（この中から pr 投稿で紹介する1つを選ぶ）:",
    ]
    for c in candidates:
        lines.append(json.dumps({
            k: c.get(k) for k in
            ("id", "name", "author", "price", "price_note", "review_count",
             "review_average", "shop", "address", "caption")
            if c.get(k) not in (None, "")
        }, ensure_ascii=False))
    if feedback:
        lines += ["", "前回の下書きは次のチェックに引っかかりました。すべて直して書き直してください:"]
        lines += [f"- {e}" for e in feedback]
    return system, "\n".join(lines)


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"AI の返答が JSON として読めませんでした: {e}: {text[:300]}") from e
    for key in POST_SCHEMA["required"]:
        if key not in data:
            raise LLMError(f"AI の返答に {key} がありません")
    return data


def _call_gemini(system, user):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY が未設定です（GitHub Secrets を確認してください）")
    res = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=180,
    )
    if res.status_code != 200:
        raise LLMError(f"Gemini API がエラーを返しました: HTTP {res.status_code} {res.text[:300]}")
    body = res.json()
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Gemini の返答に本文がありません: {json.dumps(body, ensure_ascii=False)[:300]}") from e
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _call_claude(system, user):
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": POST_SCHEMA},
        },
        # 安全判定で断られたときは、Anthropic 推奨の別モデルで自動的にやり直す
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise LLMError(f"Claude が生成を断りました: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude の返答が長すぎて途中で切れました")
    return next(b.text for b in response.content if b.type == "text")


def provider():
    chosen = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if chosen in ("claude", "gemini"):
        return chosen
    return "claude" if os.environ.get("ANTHROPIC_API_KEY") else "gemini"


def generate(system, user):
    name = provider()
    raw = _call_claude(system, user) if name == "claude" else _call_gemini(system, user)
    return _parse_json(raw)
