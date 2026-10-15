"""同じ言い回し・同じ書き出しが続かないようにする（AI っぽさのいちばんの原因が「毎回同じ形」なので）。

毎朝、この1週間に実際に投稿した文章を数えて、何度も使っている言い回しを見つける。
  ・prompts.VARIETY_NOTE … 「今回は使わない言い回し」と「今日の書き出しの形」を AI に渡す
  ・checks.OVERUSED     … 下書きに入っていたら書き直してもらう（書き直しても残るときは、投稿は止めずに要確認にする）
決まった禁止リストではなく、その時々の口ぐせを毎回見つけるので、新しい口ぐせができても防げる。
"""

import datetime
import json
import re
from collections import Counter
from pathlib import Path

DAYS = 7
MIN_POSTS = 4       # 投稿がこれより少ないうちは、口ぐせを判断しない
MIN_SHARE = 0.3     # この割合以上の投稿に出てくる言い回しを「使いすぎ」とする
MAX_PHRASES = 12

# AI が書いた文章に出やすい決まり文句。2回以上使っていたら使いすぎとみなす
WATCH = ["え、", "二度見", "ってなる", "ってなった", "なんだよね", "正直", "やつ", "地味に", "あるある",
         "ツリーに書いておく", "ツリーにメモ", "見ておきたい", "わかりすぎ", "これ私だけ", "しがち", "のが大事"]
WATCH_MIN = 2

# 書き出しの形。種類ごと・日ごとに順番に変える
OPENINGS = [
    "その場の一コマ（時間・場所・モノで、今まさに起きている場面を短く描く）",
    "心の声（頭の中のひとりごとを、そのまま一言）",
    "読む人への問いかけ（質問から入る）",
    "言いたいことを先に一言で（理由はあとから）",
    "子どものひと言（セリフ）から",
    "よくある失敗の場面から（体験談としてではなく、よくあることとして）",
    "ちょっとした発見や豆知識から（驚きのリアクションは付けない）",
]
SLOTS = {"集客投稿": 0, "役立つ投稿の1本目": 2, "役立つ投稿の2本目": 4, "PR 投稿": 5}

_JP = re.compile(r"[ぁ-んァ-ヶ一-龠ー]")
_KANA = re.compile(r"[ぁ-ん]")


def recent_texts(today, posted_dir, drafts_dir, days=DAYS):
    """この1週間に投稿した文章（本文とツリーの続き）。1投稿 = 1つの文字列。"""
    texts = []
    since = today - datetime.timedelta(days=days)
    for path in sorted(Path(posted_dir).glob("*.json")):
        try:
            day = datetime.date.fromisoformat(path.stem)
        except ValueError:
            continue
        if not since <= day < today:
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            draft = Path(drafts_dir) / entry.get("draft", "")
            if not entry.get("draft") or not draft.exists():
                continue
            posts = json.loads(draft.read_text(encoding="utf-8")).get("posts", [])
            i = entry.get("post_index", 0)
            if i < len(posts):
                p = posts[i]
                texts.append("\n".join([p.get("text", ""), *(p.get("thread_parts") or [])]))
    return texts


def _grams(text, low=5, high=10):
    text = re.sub(r"\s+", "", text)
    return {text[i:i + n] for n in range(low, high + 1) for i in range(len(text) - n + 1)}


def overused(texts, limit=MAX_PHRASES):
    """何度も使っている言い回しを、よく使う順に返す。"""
    if len(texts) < MIN_POSTS:
        return []
    found = {}
    for word in WATCH:  # 決まり文句: 合計の回数で見る
        n = sum(t.count(word) for t in texts)
        if n >= WATCH_MIN:
            found[word] = n
    # それ以外の口ぐせ: 何本の投稿に出てくるかで見る
    docs = Counter()
    for t in texts:
        docs.update(_grams(t))
    need = max(3, int(len(texts) * MIN_SHARE + 0.999))
    cands = [g for g, n in docs.items() if n >= need and len(_KANA.findall(g)) >= 2 and len(_JP.findall(g)) == len(g)]
    cands.sort(key=lambda g: (-len(g), -docs[g]))
    for g in cands:  # 長い言い回しを優先し、その一部分だけのものは除く
        if any(g in k for k in found):
            continue
        found[g] = docs[g]
    return [w for w, _ in sorted(found.items(), key=lambda x: -x[1])][:limit]


def openings(today):
    """今日の書き出しの形（種類ごと）。毎日ずらして、同じ形が続かないようにする。"""
    d = today.toordinal()
    return {name: OPENINGS[(d + k) % len(OPENINGS)] for name, k in SLOTS.items()}


def note(today, phrases):
    lines = ["# 同じ形をくり返さない（いちばん大事。毎回同じ形だと AI が書いたとすぐ分かる）"]
    if phrases:
        lines.append("最近の投稿で何度も使っている言い回し。今回は使わない（言い換えて似た形にするのもやめる）: "
                     + "、".join(f"「{p}」" for p in phrases))
    lines.append("今日の書き出しの形（種類ごとに決めてある。これに合わせる）:")
    lines += [f"- {k}: {v}" for k, v in openings(today).items()]
    lines.append("- つぶやき: 何本か書くときは、1本ずつ違う形にする")
    lines.append("見本や例として書かれている言い回しは、そのまま使わない。毎回、自分の言葉で書く。")
    return "\n".join(lines)


def setup(today, posted_dir, drafts_dir):
    """毎朝の文章作りの前に呼ぶ。(AI に渡す注意書き, 使いすぎの言い回し) を返す。"""
    phrases = overused(recent_texts(today, posted_dir, drafts_dir))
    if phrases:
        print("🔁 最近使いすぎの言い回し: " + "、".join(phrases))
    return note(today, phrases), phrases
