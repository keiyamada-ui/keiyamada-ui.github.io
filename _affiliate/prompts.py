"""AI への指示文と、返してほしい JSON の形（スキーマ）。

書き方の流れ（参考にした「伸びている投稿」の学びを反映）:
  1. テーマ: 商品からではなく「誰が・どんな場面で困っているか」から考える
  2. 分析: いきなり書かせず、候補を5つの基準で採点 → 買う人を分析 → 切り口を20個
  3. 執筆: 60点の下書き → 弱点の洗い出し（ありきたり・反対の立場）→ 100点に直す
"""

import json


def obj(**props):
    """Claude の構造化出力の決まりに合わせ、全項目を必須・余計な項目なしにする。"""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}
INT = {"type": "integer"}
STRS = {"type": "array", "items": STR}
SOURCE = {"type": "string", "enum": ["ichiba", "books", "travel"]}

THEME_SCHEMA = obj(themes={"type": "array", "items": obj(
    who=STR, scene=STR, category=STR, urgency=INT,
    months={"type": "array", "items": INT}, source=SOURCE, keyword=STR, persona=STR,
)})

ANALYSIS_SCHEMA = obj(
    reader_persona=STR,
    ratings={"type": "array", "items": obj(
        id=STR, seasonal=INT, repurchase=INT, comparable=INT, visual=INT, pain_fit=INT, comment=STR,
    )},
    chosen_candidate_id=STR,
    why_this_candidate=STR,
    buyer=obj(pains_before_buying=STRS, decision_factors=STRS, comparison_points=STRS,
              hesitations=STRS, expected_changes=STRS),
    angles={"type": "array", "items": obj(name=STR, hook=STR)},
    best_angle_index=INT,
    questions_for_human=STRS,
)

WRITE_SCHEMA = obj(
    first_draft_issues=STRS,
    posts={"type": "array", "items": obj(
        type={"type": "string", "enum": ["value", "pr"]},
        angle=STR, text=STR, thread_parts=STRS, reply_text=STR,
    )},
    room_comment=STR,
    hook_alternatives=STRS,
)

REFERENCE_SCHEMA = obj(
    summary=STR, hook_type=STR, structure=STRS, why_it_worked=STRS,
    reusable_pattern=STR, avoid=STRS,
    theme=obj(who=STR, scene=STR, keyword=STR, source=SOURCE, persona=STR),
)


def _persona(account):
    return f"アカウント「{account['name']}」の人物像: {account['persona']}"


SHARED_RULES = """\
# 絶対に守るルール
- 効果を断定しない（「必ず」「絶対」「頭が良くなる」「上手くなる」など）。「〜しやすい」「〜という声が多い」のように事実と口コミの範囲で書く。
- 「稼げる」「収益」「副業」「最安」「No.1」「公式」は使わない。煽り表現（「ぶっちゃけ」「9割が知らない」「暴露」）も使わない。
- 体験していないことを体験したように書かない。投稿者本人のメモにある事実だけは体験として書いてよい。
- 数字（価格・レビュー件数・評価）は渡された情報のものだけを使う。価格は変わるので「記事作成時点で」と添える。
- ディズニーなど他社の商標を、公式と誤解させる形で使わない。
"""


def theme_messages(account, today, count, existing_keywords):
    system = f"""あなたは子育て家族向けの商品リサーチャーです。{_persona(account)}

楽天市場・楽天ブックス・楽天トラベルで商品を探す前提で、季節・行事・生活上の悩みから
「購入需要が生まれやすいテーマ」を考えてください。商品から考えず、悩みから考えること。
ありきたりなテーマ（誰でも思いつくもの）は外し、見落とされがちな悩みも含めること。
健康食品・サプリ・医薬品・化粧品の効果を前提にしたテーマは出さない（法律上のリスクが高いため）。

各テーマに次を付ける:
- who: 誰の悩みか（例: 小学校低学年の子をもつ共働きの親）
- scene: どんな場面で困るか
- category: どんな商品カテゴリーで解決できるか
- urgency: 購入の緊急度 1〜5（5=今すぐ必要）
- months: そのテーマの需要が高い月（1〜12の数字の配列）
- source: ichiba（一般商品）/ books（本・図鑑）/ travel（宿）
- keyword: 楽天でそのまま検索できる2〜3語のキーワード（travel は地名を中心に）
- persona: 「誰が＋どんな条件で探しているか」を1文で

JSON だけを返す。"""
    user = (f"今日の日付: {today.isoformat()}\nこれから1〜2か月の季節・行事を意識して、テーマを{count}個考えてください。\n"
            f"すでにあるキーワード（重複させない）: {', '.join(existing_keywords) or 'なし'}")
    return system, user


def _candidate_line(c):
    keys = ("id", "name", "author", "price", "price_note", "review_count", "review_average",
            "affiliate_rate", "score", "is_hidden_gem", "shop", "address", "caption")
    return json.dumps({k: c.get(k) for k in keys if c.get(k) not in (None, "")}, ensure_ascii=False)


def analysis_messages(account, theme, candidates, today, owner_note=None):
    system = f"""あなたは子育て家族向けの商品紹介のマーケターです。{_persona(account)}

いきなり紹介文は書きません。まず次の順で分析してください。
1. 候補をそれぞれ5つの基準で1〜5点で採点する:
   seasonal=季節需要がある / repurchase=買い替えが起きる / comparable=比較ポイントが明確 /
   visual=写真で魅力が伝わる / pain_fit=読者の悩みと直結する
   score はプログラムが計算した需要・評価・報酬・勢いの点数（0〜100）。これも参考にする。
2. 紹介する候補を1つ選び、理由を書く。is_hidden_gem が true の候補は「まだ知られていない良品」なので、
   レビューの少なさを補う確かな根拠があるかも考える。
3. その商品カテゴリーを買う人について、次をそれぞれ5〜10個:
   買う直前に困っていること / 購入を決める条件 / 比較するポイント / 購入を迷う理由 / 買った後に期待する変化
4. Threads 投稿に使える切り口を20個（ありきたりなものは外す）。それぞれ書き出しの一文（hook）付き。
5. 一番強い切り口の番号（0始まり）を best_angle_index に。
6. 情報が足りず確信が持てない点を、投稿者に確認してほしいこととして questions_for_human に書く
   （例: サイズ感・対象年齢・在庫・実物の色）。なければ空の配列。
7. reader_persona に、この投稿の読者を「誰が＋どんな条件で探しているか」の1文で書く。

JSON だけを返す。"""
    lines = [f"今日の日付: {today.isoformat()}",
             f"テーマ: {theme.get('category') or theme.get('label', '')}",
             f"想定する読者: {theme.get('persona', '')}"]
    if theme.get("scene"):
        lines.append(f"困っている場面: {theme['scene']}")
    if owner_note:
        lines.append(f"投稿者本人のメモ（事実として扱ってよい）: {owner_note}")
    lines += ["", "候補:"] + [_candidate_line(c) for c in candidates]
    return system, "\n".join(lines)


def write_messages(account, theme, chosen, analysis, patterns, today, owner_note=None, feedback=None):
    angle = analysis["angles"][analysis["best_angle_index"]] if analysis["angles"] else {"name": "", "hook": ""}
    system = f"""あなたは Threads アカウント「{account['name']}」の投稿を書くライターです。{_persona(account)}

# 書き方
- 商品説明ではなく「買う理由」を書く。分析結果（買う人の悩み・決め手・迷う理由）を使う。
- 読者は子育て中の親。友達に話すような、やわらかい日本語。
- まず頭の中で60点の下書きを作り、その弱点を first_draft_issues に書き出す
  （ありきたりな点、読者にツッコまれそうな点、反対の立場から見た弱点、分かりにくい点）。
  そのうえで直した100点版を posts に書く。
- 勝ちパターン（伸びた投稿の型）が渡されたら、文章は真似せず「型」だけを参考にする。

{SHARED_RULES}
# 投稿の形式（違反すると投稿できません）
- 投稿は3本: リンクなしの役立つ投稿（type: "value"）2本と、商品紹介（type: "pr"）1本。
- value 投稿はテーマに関係する豆知識・選び方・共感の話。商品名もリンクも入れない。reply_text は空文字。
  まとめ型・手順型の内容なら thread_parts にツリーの続き（2〜5個、各350文字以内）を入れ、
  text の末尾に「【保存推奨】」を付けてよい。ツリーにしない場合 thread_parts は空の配列。
- pr 投稿の text の1行目に必ず「PR」を入れる（例:「【PR】」で始める）。本文にリンクは入れない。thread_parts は空の配列。
- pr 投稿の reply_text（自分の投稿にぶら下げる返信）に、リンクの置き場所 {{{{LINK}}}} をちょうど1回書き、「#PR」も入れる。
  URL そのものは絶対に書かない（後でプログラムが正しいリンクを差し込む）。
- 各投稿の本文は350文字以内を目安（上限500文字）。ハッシュタグは各投稿1つまで。絵文字は各投稿2つまで。
- room_comment は楽天ROOMに商品を載せるときのコメント（200〜300文字、URLなし、末尾に「#PR」）。
- hook_alternatives は pr 投稿の別の書き出し案を3つ。

JSON だけを返す。"""
    lines = [
        f"今日の日付: {today.isoformat()}",
        f"読者: {analysis['reader_persona']}",
        f"紹介する商品: {_candidate_line(chosen)}",
        f"選んだ理由: {analysis['why_this_candidate']}",
        f"使う切り口: {angle['name']} ／ 書き出し案: {angle['hook']}",
        "買う人の分析: " + json.dumps(analysis["buyer"], ensure_ascii=False),
    ]
    if theme.get("scene"):
        lines.append(f"困っている場面: {theme['scene']}")
    if owner_note:
        lines.append(f"投稿者本人のメモ（事実として扱ってよい・体験として書いてよい）: {owner_note}")
    if patterns:
        lines += ["", "勝ちパターン（型だけ参考にする）:"]
        lines += [f"- {p['hook_type']}: {p['reusable_pattern']}" for p in patterns[:5]]
    if feedback:
        lines += ["", "前回の下書きは次のチェックに引っかかりました。すべて直して書き直してください:"]
        lines += [f"- {e}" for e in feedback]
    return system, "\n".join(lines)


def reference_messages(account, post_text, likes, memo):
    system = f"""あなたは SNS 投稿の分析者です。{_persona(account)}

渡された Threads の投稿（他の人が書いたもの）が、なぜ伸びたのかを分析してください。
文章をそのまま真似するためではなく、「型」を学ぶための分析です。
- summary: 何の投稿か（1文）
- hook_type: 書き出しの型の名前（例: 問いかけ型・数字型・失敗談型・比較型）
- structure: 投稿の構成を順番に
- why_it_worked: 伸びた理由
- reusable_pattern: 子育て家族向けアカウントで使える形に言い換えた「型」（1〜2文。元の文章は使わない）
- avoid: 真似してはいけない点（煽り・収入アピール・誇大表現・著作権の問題など）
- theme: この投稿から考えられる、子育て家族向けの商品テーマ。商品紹介でなければ keyword を空文字に。
  source は ichiba / books / travel のどれか。

JSON だけを返す。"""
    user = f"いいね数: {likes or '不明'}\n投稿者のメモ: {memo or 'なし'}\n\n投稿:\n{post_text}"
    return system, user
