"""AI（Claude または Gemini）を呼び出す。

- ANTHROPIC_API_KEY があれば Claude を先に使い、残高切れなどで失敗したら自動的に Gemini でやり直す。
- ANTHROPIC_API_KEY がなければ最初から Gemini を使う。
- LLM_PROVIDER=gemini / claude で固定もできる。
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


def _call_gemini(system, user, schema):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY が未設定です（GitHub Secrets を確認してください）")
    user = f"{user}\n\n# 返す JSON の形（JSON Schema）\n{json.dumps(schema, ensure_ascii=False)}"
    res = requests.post(
        GEMINI_URL.format(model=GEMINI_MODEL),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=300,
    )
    if res.status_code != 200:
        raise LLMError(f"Gemini API がエラーを返しました: HTTP {res.status_code} {res.text[:300]}")
    body = res.json()
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Gemini の返答に本文がありません: {json.dumps(body, ensure_ascii=False)[:300]}") from e
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _call_claude(system, user, schema):
    import anthropic

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        # 安全判定で断られたときは、Anthropic 推奨の別モデルで自動的にやり直す
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise LLMError(f"Claude が生成を断りました: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude の返答が長すぎて途中で切れました")
    return next(b.text for b in response.content if b.type == "text")


def _describe_claude_error(e):
    text = str(e)
    if "credit balance" in text.lower():
        return "Claude の残高（クレジット）がなくなりました。Claude Console でチャージしてください"
    if "authentication" in text.lower() or "x-api-key" in text.lower():
        return "Claude の API キーが無効です。GitHub Secrets の ANTHROPIC_API_KEY を確認してください"
    return f"Claude が使えませんでした（{text[:150]}）"


class Generator:
    """1回の実行の中で何度も呼ばれる。Claude が一度失敗したら、その回は Gemini に切り替えたままにする。"""

    def __init__(self):
        chosen = os.environ.get("LLM_PROVIDER", "").strip().lower()
        if chosen in ("claude", "gemini"):
            self.provider = chosen
        else:
            self.provider = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "gemini"
        self.notice = ""

    @property
    def label(self):
        return f"Claude（{CLAUDE_MODEL}）" if self.provider == "claude" else f"Gemini（{GEMINI_MODEL}）"

    def __call__(self, system, user, schema):
        if self.provider == "claude":
            try:
                return _parse_json(_call_claude(system, user, schema), schema)
            except Exception as e:  # 残高切れ・キー無効・混雑など、理由を問わず Gemini でやり直す
                if not os.environ.get("GEMINI_API_KEY"):
                    raise
                self.notice = _describe_claude_error(e)
                print(f"⚠️ {self.notice} → Gemini に切り替えます")
                self.provider = "gemini"
        return _parse_json(_call_gemini(system, user, schema), schema)
