"""Claude の使った金額と、残高の目安を記録する。

Claude には「今の残高」を直接読み取る仕組みがないため、
  ・管理画面で入力した残高（Claude Console に出ている金額）やチャージ額から
  ・AI を呼ぶたびに、返ってきた使用量（文字数＝トークン数）× 料金表 で計算した金額を引いて
目安の残高を出す。ぴったりの金額は Claude Console の「Billing」で確認できる。

    data/stats/claude.json
      usage:   日付 → {"usd": その日に使った金額（ドル）, "calls": 呼んだ回数}
      balance: {"usd": 残高の目安, "at": 最後に入力した日時, "set_usd": そのとき入力した金額}
      charges: [{"at": 日時, "usd": 金額, "kind": "set" | "add"}]  入力の履歴

    python _affiliate/claude_cost.py set 18.40   … Console に出ている残高に合わせる
    python _affiliate/claude_cost.py add 10      … チャージした金額を足す
"""

import argparse
import datetime
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATH = HERE / "data" / "stats" / "claude.json"
JST = datetime.timezone(datetime.timedelta(hours=9))

# 100万トークンあたりの料金（ドル）: (入力, 出力)。新しいモデルほど先に書く
PRICES = [
    ("claude-opus-5-5", 4.0, 20.0),
    ("claude-sonnet-5-5", 2.0, 10.0),
    ("claude-haiku-5-5", 0.10, 0.50),
    ("claude-fable-5", 10.0, 50.0),
    ("claude-opus-5", 5.0, 25.0),
    ("claude-opus-4", 5.0, 25.0),
    ("claude-sonnet-5", 2.0, 10.0),
    ("claude-sonnet-4", 3.0, 15.0),
]
DEFAULT_PRICE = (4.0, 20.0)  # 知らないモデルは Opus 5.5 と同じ料金で数える
WEB_SEARCH_USD = 0.01  # ネット検索 1回あたり


def _get(obj, key, default=0):
    value = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return default if value is None else value


def cost_usd(model, usage):
    """1回の返答の金額（ドル）。usage は Claude の返答の response.usage。"""
    price_in, price_out = next(((i, o) for name, i, o in PRICES if (model or "").startswith(name)), DEFAULT_PRICE)
    tokens_in = _get(usage, "input_tokens")
    cache_write = _get(usage, "cache_creation_input_tokens")
    cache_read = _get(usage, "cache_read_input_tokens")
    tokens_out = _get(usage, "output_tokens")
    searches = _get(_get(usage, "server_tool_use", None) or {}, "web_search_requests")
    return ((tokens_in + cache_write * 1.25 + cache_read * 0.1) * price_in + tokens_out * price_out) / 1_000_000 \
        + searches * WEB_SEARCH_USD


def _load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _now():
    return datetime.datetime.now(JST)


def log(model, usage, path=None):
    """AI を1回呼ぶたびに、使った金額を今日の分に足し、残高の目安から引く。"""
    path = Path(path or os.environ.get("KOTORI_CLAUDE_COST") or PATH)
    usd = cost_usd(model, usage)
    data = _load(path)
    day = _now().date().isoformat()
    row = data.setdefault("usage", {}).setdefault(day, {"usd": 0.0, "calls": 0})
    row["usd"] = round(row["usd"] + usd, 6)
    row["calls"] += 1
    if data.get("balance"):
        data["balance"]["usd"] = round(data["balance"]["usd"] - usd, 6)
    _save(path, data)
    return usd


def record(kind, usd, path=PATH):
    """kind="set": 残高を入力した金額に合わせる / kind="add": チャージした金額を足す。"""
    usd = round(float(usd), 2)
    if usd < 0 or (kind == "add" and usd == 0):
        raise ValueError("金額は 0 より大きい数で入力してください")
    path = Path(path)
    data = _load(path)
    at = _now().isoformat(timespec="minutes")
    if kind == "set" or not data.get("balance"):
        data["balance"] = {"usd": usd, "at": at, "set_usd": usd}
    else:
        data["balance"]["usd"] = round(data["balance"]["usd"] + usd, 6)
    data.setdefault("charges", []).append({"at": at, "usd": usd, "kind": kind})
    data["charges"] = data["charges"][-50:]
    _save(path, data)
    return data["balance"]["usd"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=["set", "add"])
    parser.add_argument("usd")
    args = parser.parse_args()
    left = record(args.kind, str(args.usd).replace("$", "").replace(",", "").strip())
    word = "残高を合わせました" if args.kind == "set" else "チャージを足しました"
    print(f"✅ {word}（残高の目安: ${left:,.2f}）")


if __name__ == "__main__":
    main()
