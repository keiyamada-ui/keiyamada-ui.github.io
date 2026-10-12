"""AI（Claude または Gemini）を呼び出す。

投稿の重要度ごとに使う AI を変える（config.yaml の ai）:
  important = 集客投稿・PR 投稿など大事なもの → Claude Opus 5.5（調べものはネット検索つき）
  standard  = テーマ作り・ROOM のコメントなど   → Claude Sonnet 5.5
  casual    = つぶやき・コメント返しの案        → Gemini（無料）

Claude が使えない（キー未登録・残高切れなど）ときは自動で Gemini に、
Gemini が使えないときは Claude Sonnet 5.5 に切り替える。
LLM_PROVIDER=gemini / claude で全部を固定することもできる。
"""

import json
import os
import time

import requests

DEFAULT_TIERS = {
    "important": {"provider": "claude", "model": "claude-opus-5-5", "effort": "high"},
    "standard": {"provider": "claude", "model": "claude-sonnet-5-5", "effort": "medium"},
    "casual": {"provider": "gemini", "model": "claude-sonnet-5-5", "effort": "low"},
}
# Gemini の具体的なモデル名は頻繁に入れ替わるため、常に最新の Flash を指す別名を使う
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Gemini が使えないとき、つぶやき用に使う Claude
CLAUDE_BACKUP_MODEL = "claude-sonnet-5-5"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6,
                   "user_location": {"type": "approximate", "country": "JP", "timezone": "Asia/Tokyo"}}
MAX_CONTINUATIONS = 4
GEMINI_RETRY_WAITS = [10, 30, 60]


class LLMError(RuntimeError):
    pass


def _parse_json(text, schema):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"AI の返答が JSON として読めませんでした: {e}: {text[:300]}") from e
    missing = [k for k in schema["required"] if k not in data]
    if missing:
        raise LLMError(f"AI の返答に {', '.join(missing)} がありません")
    return data


def _call_gemini(system, user, schema=None, search=False, images=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY が未設定です（GitHub Secrets を確認してください）")
    body = {"systemInstruction": {"parts": [{"text": system}]}}
    if schema:
        user = f"{user}\n\n# 返す JSON の形（JSON Schema）\n{json.dumps(schema, ensure_ascii=False)}"
        body["generationConfig"] = {"responseMimeType": "application/json"}
    if search:
        body["tools"] = [{"google_search": {}}]
    pics = [{"inline_data": {"mime_type": m, "data": d}} for m, d in (images or [])]
    body["contents"] = [{"role": "user", "parts": pics + [{"text": user}]}]
    for wait in GEMINI_RETRY_WAITS + [None]:
        res = requests.post(GEMINI_URL.format(model=GEMINI_MODEL),
                            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                            json=body, timeout=300)
        # 混雑（429/503）や一時的な不具合（500）は、少し待ってやり直す
        if res.status_code not in (429, 500, 502, 503, 504) or wait is None:
            break
        print(f"⏳ Gemini が混雑しています（HTTP {res.status_code}）。{wait}秒待ってやり直します")
        time.sleep(wait)
    if res.status_code != 200:
        raise LLMError(f"Gemini API がエラーを返しました: HTTP {res.status_code} {res.text[:300]}")
    data = res.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Gemini の返答に本文がありません: {json.dumps(data, ensure_ascii=False)[:300]}") from e
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _call_claude(system, user, model, effort, schema=None, search=False, images=None):
    import anthropic

    client = anthropic.Anthropic()
    params = {
        "model": model, "max_tokens": 32000, "system": system,
        # 安全判定で断られたときは、Anthropic 推奨の別モデルで自動的にやり直す
        "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default",
    }
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params["output_config"] = output_config
    if search:
        params["tools"] = [WEB_SEARCH_TOOL]
    content = user
    if images:  # スクショなどの画像（base64）を一緒に見てもらう
        content = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": d}} for m, d in images]
        content.append({"type": "text", "text": user})
    messages = [{"role": "user", "content": content}]
    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(messages=messages, **params) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        # ネット検索が長引いて一度止まった。続きから再開してもらう
        messages = [messages[0], {"role": "assistant", "content": response.content}]
    if response.stop_reason == "refusal":
        raise LLMError(f"Claude が生成を断りました: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude の返答が長すぎて途中で切れました")
    text = "".join(b.text for b in response.content if b.type == "text")
    if not text.strip():
        raise LLMError("Claude の返答に本文がありませんでした")
    return text


def _describe_claude_error(e):
    text = str(e)
    if "credit balance" in text.lower():
        return "Claude の残高（クレジット）がなくなりました。Claude Console でチャージしてください"
    if "authentication" in text.lower() or "x-api-key" in text.lower():
        return "Claude の API キーが無効です。GitHub Secrets の ANTHROPIC_API_KEY を確認してください"
    return f"Claude が使えませんでした（{text[:150]}）"


class Generator:
    """1回の実行の中で何度も呼ばれる。Claude が一度失敗したら、その回は Gemini に切り替えたままにする。

    generate(system, user, schema)                 → standard（従来どおりの呼び方）
    generate(system, user, schema, tier="casual")  → 重要度を指定
    generate.research(system, user)                → ネット検索して調べた結果（文章）を返す
    """

    def __init__(self, tiers=None):
        self.tiers = {k: dict(DEFAULT_TIERS[k], **(tiers or {}).get(k, {})) for k in DEFAULT_TIERS}
        forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
        self.forced = forced if forced in ("claude", "gemini") else ""
        self.claude_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
        self.gemini_ok = bool(os.environ.get("GEMINI_API_KEY"))
        self.notice = ""
        self.used = []  # 実際に使った AI（下書きに書く）

    def _plan(self, tier):
        conf = self.tiers[tier]
        first = self.forced or conf["provider"]
        steps = []
        claude_model = conf["model"] if conf["provider"] == "claude" else CLAUDE_BACKUP_MODEL
        if first == "claude":
            steps = [("claude", claude_model), ("gemini", GEMINI_MODEL)]
        else:
            steps = [("gemini", GEMINI_MODEL), ("claude", claude_model)]
        return [(p, m) for p, m in steps if (p == "claude" and self.claude_ok) or (p == "gemini" and self.gemini_ok)]

    def _run(self, tier, call):
        plan = self._plan(tier)
        if not plan:
            raise LLMError("AI の API キー（GEMINI_API_KEY / ANTHROPIC_API_KEY）が登録されていません")
        last = None
        for provider, model in plan:
            try:
                result = call(provider, model)
                label = f"Claude（{model}）" if provider == "claude" else f"Gemini（{model}）"
                if label not in self.used:
                    self.used.append(label)
                return result
            except Exception as e:  # 残高切れ・キー無効・混雑など、理由を問わず次の AI でやり直す
                last = e
                if provider == "claude":
                    self.notice = _describe_claude_error(e)
                    self.claude_ok = False
                    print(f"⚠️ {self.notice} → Gemini に切り替えます")
                else:
                    print(f"⚠️ Gemini が使えませんでした（{str(e)[:150]}）→ 次の AI を試します")
        raise last

    @property
    def label(self):
        return "・".join(self.used) or "（AI 未使用）"

    def __call__(self, system, user, schema, tier="standard", images=None):
        """images: [(mime_type, base64文字列), ...] を渡すと、画像も見て答える。"""
        effort = self.tiers[tier]["effort"]

        extra = {"images": images} if images else {}

        def call(provider, model):
            if provider == "claude":
                return _parse_json(_call_claude(system, user, model, effort, schema, **extra), schema)
            return _parse_json(_call_gemini(system, user, schema, **extra), schema)
        return self._run(tier, call)

    def research(self, system, user, tier="important"):
        """ネット検索しながら調べて、メモ（文章）を返す。検索できないときは検索なしで考える。"""
        effort = self.tiers[tier]["effort"]

        def call(provider, model):
            if provider == "claude":
                return _call_claude(system, user, model, effort, search=True)
            try:
                return _call_gemini(system, user, search=True)
            except LLMError:
                return _call_gemini(system, user)
        return self._run(tier, call)
