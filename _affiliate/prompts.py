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

ROOM_SCHEMA = obj(comments={"type": "array", "items": obj(id=STR, comment=STR)})

REFERENCE_SCHEMA = obj(
    summary=STR, hook_type=STR, structure=STRS, why_it_worked=STRS,
    reusable_pattern=STR, avoid=STRS,
    theme=obj(who=STR, scene=STR, keyword=STR, source=SOURCE, persona=STR),
    comment_insights=STRS, reader_questions=STRS,
)


# 今の季節感（season.py が毎朝、実際の気温から作る）と、自分の投稿から学んだこと（learn.py が週1回作る）。
# すべての文章作りに添える
SEASON_NOTE = ""
LEARNED_NOTE = ""
TIPS_NOTE = ""  # 参考投稿フォームで登録した「考え方・コツ」（ルール帳が作れないときだけ使う）
RULEBOOK_NOTE = ""  # 考え方・コツと自分の投稿の学びをまとめたルール帳（rulebook.py）
VARIETY_NOTE = ""  # 最近使いすぎの言い回しと、今日の書き出しの形（variety.py）
REWRITE_NOTE = ""  # 投稿者本人の書き直し・お手本・👍👎（rewrites.py）。いちばん優先


def _persona(account):
    base = f"アカウント「{account['name']}」の人物像: {account['persona']}"
    if account.get("persona_rules"):
        base += f"\n人物像の使い方: {account['persona_rules']}"
    return base + "".join(f"\n\n{n}" for n in (SEASON_NOTE, RULEBOOK_NOTE, LEARNED_NOTE, TIPS_NOTE, VARIETY_NOTE, REWRITE_NOTE) if n)


SHARED_RULES = """\
# 絶対に守るルール
- 効果を断定しない（「必ず」「絶対」「頭が良くなる」「上手くなる」など）。「〜しやすい」「〜という声が多い」のように事実と口コミの範囲で書く。
- 「稼げる」「収益」「副業」「最安」「No.1」「公式」は使わない。煽り表現（「ぶっちゃけ」「9割が知らない」「暴露」）も使わない。
- 体験していないことを体験したように書かない。投稿者本人のメモにある事実だけは体験として書いてよい。
- 数字（価格・レビュー件数・評価）は渡された情報のものだけを使う。価格は変わるので「記事作成時点で」と添える。
- ディズニーなど他社の商標を、公式と誤解させる形で使わない。
"""

# AI が書いたと気づかれないための書き方（すべての投稿に使う）
HUMAN_STYLE = """# 人間らしい文章にする（AI が書いたと思われないことが最優先）
- 子育て中の親が、スマホでさっと打ったような文章にする。話し言葉。きれいに整えすぎない。
- 短く書く。言いたいことと数字だけで十分。基本は100字前後（つぶやきはもっと短く）。
  例: 「2枚で3,180円、送料0円。『え、メール便で2点までいけるの？』ってなった。」ではなく「2枚3180円で送料無料！」
- 驚いたふりをしない（「え、〜？」「二度見」「〜ってなった」「〜ってなるやつ」）。大したことでないことを大げさに書かない。
- 読めばわかる理由や、当たり前の説明を書かない（「〜だからなんだよね」「〜っていう上限があって」など）。
  人は、自分が言いたいことだけを書く。わざわざ説明しない。
- 「！」は使ってよい（1投稿に1〜2個まで。「！！」と続けない）。
- 文末を単調にしない。同じ語尾を続けない。投稿ごとにも、語尾や口ぐせが毎回同じにならないようにする。
- 書き出しの形は「同じ形をくり返さない」の指示に合わせる。
- 本音やツッコミは入れてもよいが、毎回入れなくてよい。同じ言葉（「正直」など）をくり返さない。
- 次の AI っぽい言い回しは使わない: 「いかがでしたか」「結論から言うと」「解説します」「ご紹介します」
  「ポイントは〇つ」「まとめると」「〜することが大切です」「〜と言えるでしょう」「〜してみてはいかがでしょうか」
  「様々な」「徹底解説」「必見」「〜に最適」「〜を実現」「〜な方へ」「〜な方必見」。
- 見出し記号（■◆【】）、①②③の番号、文末ごとの絵文字は使わない（絵文字は0〜1個。PR 表記の【PR】だけは例外）。
- 体験していない出来事を事実のように作らない（「うちの子が昨日〜した」は書かない）。
  多くの家庭で起きることとして書く。投稿者本人のメモ（ネタ帳）にある出来事だけは、本人の体験として書いてよい。
- 「投稿者本人の書き方」のお手本があれば、それを一番に参考にする。
- 書いたあとに「AI が書いた感じがしないか」「長すぎないか」を見直し、直してから返す。
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
- keyword: 楽天でそのまま検索して商品がたくさん出る、一般的な2〜3語のキーワード（travel は地名を中心に）。
  固有名詞・型番・細かすぎる条件（「直結」「コンパクト版」「裏起毛」など）は入れない。例: 「なわとび 子供」「図鑑 小学生」「箱根 家族」
- persona: 「誰が＋どんな条件で探しているか」を1文で

JSON だけを返す。"""
    user = (f"今日の日付: {today.isoformat()}\nテーマを{count}個考えてください。季節・行事のテーマは半分以下にして、残りは一年中ある悩み（片付け・勉強・習い事・食事・お金・きょうだいなど）にしてください。\n"
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


def write_messages(account, theme, chosen, analysis, patterns, today, owner_note=None, feedback=None, context=None):
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
{HUMAN_STYLE}
# 投稿の形式（違反すると投稿できません）
- 投稿は3本: リンクなしの役立つ投稿（type: "value"）2本と、商品紹介（type: "pr"）1本。
- value 投稿はテーマに関係する豆知識・選び方・共感の話。商品名もリンクも入れない。reply_text は空文字。
  本文は150文字以内。どうしても必要なときだけ thread_parts にツリーの続き（2〜3個、各150文字以内）を入れてよい。
  ツリーにしない場合 thread_parts は空の配列。
- pr 投稿の text の1行目に必ず「PR」を入れる（例:「【PR】」で始める）。本文にリンクは入れない。thread_parts は空の配列。
- pr 投稿は宣伝っぽさを抑える（宣伝らしい投稿は Threads でほとんど表示されないため）。
  前半は読む人の困りごとや、よくある場面の話。商品の話は後半に短く、決め手を1〜2個だけ。
  色・サイズ・スペックを並べない。価格やレビューの数字は1つか2つまで。売り込む言葉（おすすめ・ぜひ・今すぐ）は使わない。
  文章全体は150字前後に収める。
- pr 投稿の reply_text（自分の投稿にぶら下げる返信）に、リンクの置き場所 {{{{LINK}}}} をちょうど1回書き、「#PR」も入れる。
  URL そのものは絶対に書かない（後でプログラムが正しいリンクを差し込む）。
- 各投稿の本文は150文字前後まで（上限250文字）。ハッシュタグは各投稿1つまで。絵文字は各投稿1つまで。
- room_comment は楽天ROOMに商品を載せるときのコメント。Threads の投稿とは書き方を変え、次の形にする:
{ROOM_STYLE}
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
    if context:
        lines += ["", context]
    if patterns:
        lines += ["", "勝ちパターン（型だけ参考にする）:"]
        lines += [f"- {p['hook_type']}: {p['reusable_pattern']}" + (f"（読者の反応: {p['comment_insights'][0]}）" if p.get("comment_insights") else "")
                  for p in [x for x in patterns if x.get("kind") != "tips"][:5]]
    if feedback:
        lines += ["", "前回の下書きは次のチェックに引っかかりました。すべて直して書き直してください:"]
        lines += [f"- {e}" for e in feedback]
    return system, "\n".join(lines)


def reference_messages(account, post_text, likes, memo, has_images=False):
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
- comment_insights: コメント欄（返信）も渡されたときだけ。読んだ人がどこに反応したか・共感したか・反対したか、
  どんな言葉を使っていたかを2〜5個。コメント欄がなければ空の配列。
- reader_questions: コメントで読者が聞いていたこと・不安に思っていたこと（次の投稿や商品紹介のネタになるもの）を0〜5個。
  なければ空の配列。コメントした人の名前やアイコンなど、個人を特定できることは書かない。

JSON だけを返す。"""
    if has_images:
        system += ("\n\n投稿はスクリーンショット（画像）で渡します。コメント欄のスクリーンショットが含まれることもあります。"
                   "まず画像から本文・いいね数・返信数・コメントの内容などを正確に読み取り、"
                   "そのうえで分析してください。画像の中の名前やアイコンなど、投稿者を特定できる情報は結果に書かない。")
    user = (f"いいね数: {likes or '不明（画像にあれば読み取る）'}\n投稿者のメモ: {memo or 'なし'}\n\n"
            f"投稿:\n{post_text or '（スクリーンショットを見てください）'}")
    return system, user


# 楽天ROOM のコメントの書き方（ROOM のランキング上位の投稿を参考にした形。Threads とは書き方を変える）
ROOM_STYLE = """# 楽天ROOM のコメントの書き方（ランキング上位の投稿の形）
- 1行目がいちばん大事（「さらに表示」を押す前に見えるのは1行目だけ）。全角30〜40字で、お得さと何の商品かを言い切る。
  渡された商品名や価格に「クーポン」「〇%OFF」「半額」「送料無料」「先着」「〇個で〇円」などがあれば、それを1行目に使う。
  数字は渡されたものだけを使い、作らない。個数と値段がわかれば、1個あたりの値段を計算して出してよい（例:「1個あたり約137円」）。
  お得情報がなければ「困りごとが減る一言＋何の商品か」で言い切る（例:「分解して丸洗いできるキッチンバサミ✂️」）。
- 絵文字は1行目に2〜3個まで使ってよい（🔥✨🫶 など、商品に合うもの）。全体で5個まで。
- 2行目からは短い行を3〜5行: 何が良いと言われているか（レビューの評判として）／どんな人・場面に向くか／
  レビューの件数と評価。価格・クーポンは変わるので、どこかに1回「（記事作成時点）」と入れる。
- 最後の行に、ROOM で検索されそうなハッシュタグを3〜6個（例: #キッチン用品 #時短家事 #掃除グッズ）と「#PR」。
- 全体で150〜250文字。URL は書かない。
- 体験していないことを書かない（「使ってみた」「うちでは」などは、本人のメモにあるときだけ）。
- 「最安」「必ず」「絶対」「今すぐ」などの言葉は使わない。
"""


def room_messages(account, today, items):
    system = f"""あなたは楽天ROOMに商品を載せる、子育て家族向けの紹介者です。{_persona(account)}

渡された商品それぞれに、楽天ROOMの投稿コメントを書いてください。
{ROOM_STYLE}
{SHARED_RULES}
JSON だけを返す。comments の id は渡された商品の id をそのまま使う。"""
    user = f"今日の日付: {today.isoformat()}\n\n商品:\n" + "\n".join(_candidate_line(i) for i in items)
    return system, user


# ---------------------------------------------------------------- 集客投稿（バズ狙い）

BUZZ_SCHEMA = obj(
    topic=STR, why_now=STR, parent_emotion=STR,
    drafts={"type": "array", "items": obj(
        pattern=STR, text=STR, empathy=INT, reply=INT, share=INT, human=INT, weak_point=STR,
    )},
    best_index=INT,
    topic_tag=STR,
    product_keyword=STR, product_source=SOURCE, product_persona=STR,
)


def buzz_research_messages(account, today, headlines, recent_topics):
    system = f"""あなたは SNS で話題を生むのが得意な編集者です。{_persona(account)}

今日 Threads に出す「集客投稿」（商品紹介なし。共感・返信・拡散でフォロワーを増やす投稿）のネタを調べます。
ネット検索を使って、次の手順で調べてください。

1. 渡されたニュース・トレンドの見出しと、自分で検索した最近の話題から、
   小学生の子をもつ親が「わかる！」「うちも！」と反応しそうな話題を3つ選ぶ。
   季節・行事・学校・習い事・家事・お金・きょうだい・祖父母など、生活に近いものを優先する。
2. それぞれについて、なぜ今話題なのか、親たちがSNSやコメント欄でどんな本音を言っているかを検索して確かめる。
3. 伸びている投稿の「型」（あるある共感・問いかけ・本音の告白・比較・季節の小ネタ など）のどれが合うか考える。

# 使ってはいけない話題
- 事故・事件・災害・病気・死亡・虐待など、誰かがつらい思いをしている話題（宣伝目的に見えて反感を買う）
- 政治・宗教・特定の人や団体への批判、芸能人のゴシップ、炎上中の話題
- 医療・健康効果・お金もうけの話

最後に、選んだ3つの話題について「話題の要点 / なぜ今か / 親の本音 / 合いそうな投稿の型 / 関連しそうな商品ジャンル」を
日本語のメモでまとめてください。記事の文章をそのまま書き写さないこと。"""
    lines = [f"今日の日付: {today.isoformat()}", ""]
    if headlines:
        lines += ["今日集めたニュース・トレンドの見出し:"] + [f"- {h}" for h in headlines[:60]] + [""]
    if recent_topics:
        lines += ["最近使った話題（同じものは避ける）: " + "、".join(recent_topics[-14:])]
    return system, "\n".join(lines)


def buzz_write_messages(account, today, research, patterns, feedback=None):
    system = f"""あなたは Threads アカウント「{account['name']}」の中の人です。{_persona(account)}

調べたメモをもとに、今日の「集客投稿」を1本書きます。商品名・リンク・宣伝は一切入れません。
目的は、知らない人に「わかる」と思ってもらい、いいね・返信・フォローにつなげること。

# 手順
1. メモの中から一番反応が取れそうな話題を1つ選ぶ（topic / why_now / parent_emotion に書く）。
2. 違う型で下書きを3つ書く（pattern に型の名前）。型の例:
   あるある共感 / 答えたくなる問いかけ / 本音の告白 / 小さな発見 / 二択の比較 / 季節の小ネタ
3. それぞれを10点満点で厳しく採点する:
   empathy=共感される / reply=返信したくなる / share=人に見せたくなる / human=人が書いた感じがする
   weak_point に一番の弱点を書く。
4. 一番良いものの番号（0始まり）を best_index に。その下書きは弱点を直した完成版にしておく。
5. topic_tag に、Threads のトピックタグとして付ける言葉を1つ（例: 子育て、小学生ママ、習い事）。「#」は付けない。
6. この話題に反響があったとき、次に紹介できそうな楽天の商品を考え、
   product_keyword（楽天で検索する2〜3語）・product_source（ichiba/books/travel）・
   product_persona（誰が＋どんな条件で探しそうか）に書く。

# 書き方
- 本文は40〜150文字。長い説明より、短くて「わかる」と思える一言のほうが伸びる。
- 最後は、読んだ人が返信しやすい一言で終えてもよい（「みんなのとこはどう？」など）。毎回同じ締めにしない。
- ハッシュタグは書かない（トピックタグは topic_tag に分けて書く）。
{SHARED_RULES}
{HUMAN_STYLE}
JSON だけを返す。"""
    lines = [f"今日の日付: {today.isoformat()}", "", "調べたメモ:", research]
    if patterns:
        lines += ["", "勝ちパターン（型だけ参考にする）:"]
        lines += [f"- {p['hook_type']}: {p['reusable_pattern']}" for p in [x for x in patterns if x.get("kind") != "tips"][:5]]
    if feedback:
        lines += ["", "前回の下書きは次のチェックに引っかかりました。すべて直して書き直してください:"]
        lines += [f"- {e}" for e in feedback]
    return system, "\n".join(lines)


# ---------------------------------------------------------------- つぶやき（短い日常の投稿）

CASUAL_SCHEMA = obj(posts={"type": "array", "items": obj(text=STR, memo_used=STR)})


def casual_messages(account, today, count, memos, recent_texts, feedback=None):
    system = f"""あなたは Threads アカウント「{account['name']}」の中の人です。{_persona(account)}

宣伝でも役立ち情報でもない、ふつうの親の「つぶやき」を{count}本書きます。
アカウントに人間味を出すための投稿なので、内容は薄くてかまいません。

# 書き方
- 1本 15〜80文字。思いついたまま打ったような短い文。説明しない。オチもいらない。
- 朝の支度・学校の持ち物・習い事の送迎・週末・夕飯の献立・きょうだい・片付けなど、日常の話題（季節や天気の話はたまにだけ）。
- {count}本とも話題と言い回しを変える。問いかけは多くても1本まで。
- 商品名・リンク・ハッシュタグは書かない。絵文字は0〜1個。
- 投稿者のメモ（ネタ帳）が渡されたら、そのうち1つを使って本人の出来事として書き、memo_used にそのメモをそのまま書く。
  メモを使わない投稿の memo_used は空文字。
{SHARED_RULES}
{HUMAN_STYLE}
JSON だけを返す。"""
    lines = [f"今日の日付: {today.isoformat()}（{'月火水木金土日'[today.weekday()]}曜日）"]
    if memos:
        lines += ["", "投稿者のメモ（ネタ帳。本人に実際にあったこと）:"] + [f"- {m}" for m in memos]
    if recent_texts:
        lines += ["", "最近のつぶやき（似た内容・言い回しを避ける）:"] + [f"- {t}" for t in recent_texts[-10:]]
    if feedback:
        lines += ["", "前回の下書きは次のチェックに引っかかりました。すべて直して書き直してください:"]
        lines += [f"- {e}" for e in feedback]
    return system, "\n".join(lines)


# ---------------------------------------------------------------- コメント返しの案

COMMENT_SCHEMA = obj(replies={"type": "array", "items": obj(
    id=STR, action={"type": "string", "enum": ["reply", "like", "ignore"]}, reason=STR, reply_text=STR,
)})


def comment_messages(account, items):
    system = f"""あなたは Threads アカウント「{account['name']}」の中の人です。{_persona(account)}

自分の投稿についたコメントへの対応を決め、返信する場合は返信文の案を書きます。
（実際に返信するのは本人です。案はそのままコピーして使えるように書く）

# 対応の決め方（action）
- reply: 質問・体験談・共感など、会話が続くコメント。基本はこれ。返信がつくと投稿が伸びやすい。
- like: 絵文字だけ・「わかる」だけなど短い反応。いいねだけで十分。reply_text は空文字。
- ignore: 宣伝・勧誘・DM誘導・攻撃的・意味不明なコメント。返さない（必要なら非表示にする）。reply_text は空文字。

# 返信文の書き方
- 10〜60文字。友達に返すような短い文。相手の言葉を少し拾ってから返す。
- 毎回「ありがとうございます！」で始めない。言い回しを毎回変える。
- リンク・商品名・宣伝は絶対に入れない（楽天のルールで、返信にリンクを貼るのは禁止）。DMやLINEに誘わない。
- 商品について聞かれても、使っていない商品を使ったように答えない。「レビューでは〜って声が多かったよ」のように答える。
- 否定的なコメントには言い返さない。受け止める一言にするか、ignore にする。
{HUMAN_STYLE}
JSON だけを返す。replies の id は渡されたコメントの id をそのまま使う。"""
    lines = []
    for item in items:
        lines.append(json.dumps({"id": item["id"], "自分の投稿": item["post_text"][:200],
                                 "コメントした人": item["username"], "コメント": item["text"]}, ensure_ascii=False))
    return system, "\n".join(lines)


# ---------------------------------------------------------------- Pinterest のピン

PIN_SCHEMA = obj(pins={"type": "array", "items": obj(
    id=STR, title=STR, description=STR, headline=STR, points=STRS, board=STR, keywords=STRS,
)})


def pin_messages(account, today, items, boards):
    system = f"""あなたは Pinterest で子育て家族向けの「買ってよかった」ピンを作る担当です。{_persona(account)}

Pinterest は「検索して保存する」場所です。探している人が検索しそうな言葉を、自然に入れてください。
渡された商品それぞれに、ピン1枚分の文章と、画像に入れる短い文字を作ります。

- title: ピンのタイトル（25〜60文字）。「誰の・どんな悩みに・何が良いか」が分かる言葉。検索されそうな言葉を前のほうに。
- description: ピンの説明（120〜300文字）。悩み → この商品の良さ（レビューの評判として）→ どんな人に向くか。
  価格を書くときは「記事作成時点」ではなく「今は○円くらい（変わることがあります）」のように自然に。
  最後に「#PR」と、関係するハッシュタグを2つまで（例: #小学生ママ #知育）。URL は書かない。
- headline: 画像に大きく入れる言葉。2行で、1行は全角9文字以内、行の区切りに必ず「/」を入れる（例: 玄関の上着、/床置きやめたい）。
  1行目は見る人の悩みや場面、2行目は解決や気持ち。言葉の途中で区切らない。思わず保存したくなる一言に。
- points: 画像に入れる短い特徴を3つ（それぞれ全角16文字以内）。レビューや商品情報から分かることだけ。
  レビューの件数・評価・価格は画像の別の場所に自動で入るので、points には書かない。
- keywords: Pinterest で検索されそうな言葉を3〜5個（例: 小学生 なわとび、冬休み 室内遊び）。
- board: 次のボードから1つ選ぶ: {"、".join(boards)}
- 体験していないことを体験したように書かない。価格や件数は渡された数字だけを使う。
{SHARED_RULES}
{HUMAN_STYLE}
JSON だけを返す。pins の id は渡された商品の id をそのまま使う。"""
    user = f"今日の日付: {today.isoformat()}\n\n商品:\n" + "\n".join(_candidate_line(i) for i in items)
    return system, user


LEARN_SCHEMA = obj(summary=STR, lessons={"type": "array", "items": obj(
    title=STR, do=STR, avoid=STR, why=STR, applies_to=STR,
)})


def learn_messages(account, today, top, bottom, averages):
    """自分の投稿の、伸びたもの・伸びなかったものを比べて、次に活かす書き方を見つける。"""
    system = f"""あなたは Threads の運用を分析する担当です。{_persona(account)}

同じアカウントの投稿のうち、反響が大きかったものと小さかったものを渡します。
2つを比べて、「このアカウントで伸びる書き方・伸びない書き方」を見つけてください。
見るところ: 書き出しの1文・長さ・話題（悩み/あるある/商品/季節など）・問いかけの有無・具体性・本音の出し方・投稿した時間帯・投稿の種類。

- lessons: 次の投稿にそのまま使える学びを3〜5個。
  title（短い名前）, do（こう書く。具体的に）, avoid（こうは書かない）, why（比べてわかった根拠。数字があれば添える）,
  applies_to（すべて / 集客投稿 / つぶやき / 役立つ投稿 / PR 投稿 のどれか）
- 投稿数が少なく、はっきりした差が見えないときは、無理に言い切らず「まだ傾向」と書く。偶然の差を法則にしない。
  1〜2件の投稿だけで見えた差は、lessons にしないか、「試してみる」程度の書き方にとどめる。
- do と avoid に、そのまま使える言い回し・例文・決まり文句を書かない（例文を書くと、毎回それを真似して全部の投稿が同じ形になる）。
  書き出しや締めの形を1つに決めつける学びも出さない。「何を伝えると反応が来たか」を書く。
- 返信の数は、自分で付けた返信（ツリーの続き・リンク）を除いた、読んだ人からの返信だけを数えてある。
- 全部の投稿が似た形になっていることが反響の伸びない理由に見えるときは、それも学びとして書く。
- summary: 全体の一言まとめ（例: 「問いかけで終わる短い投稿ほど返信が多い」）
- 体験していないことを体験として書く、効果を断定する、のような学びは出さない（ルール違反になるため）。

JSON だけを返す。"""
    def lines(rows):
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    user = (f"今日の日付: {today.isoformat()}\n種類ごとの平均: {json.dumps(averages, ensure_ascii=False)}\n\n"
            f"## 反響が大きかった投稿\n{lines(top)}\n\n## 反響が小さかった投稿\n{lines(bottom)}")
    return system, user


TIPS_SCHEMA = obj(
    summary=STR,
    principles={"type": "array", "items": obj(title=STR, explain=STR)},
    rules_for_us=STRS, example=STR, avoid=STRS,
)


def tips_messages(account, content, memo, has_images=False):
    """「考え方・コツ」（バズる投稿の作り方の解説など）を、このアカウントで使える具体的なルールに直す。"""
    system = f"""あなたは SNS 運用のコーチです。{_persona(account)}

渡されたのは、投稿の作り方・伸ばし方についての「考え方・コツ」です（解説の投稿や記事、メモなど）。
これを読み、子育て家族向けのこのアカウント（Threads）で実際に使える形に落とし込んでください。
- summary: 何についての考え方か（1文）
- principles: 考え方の要点を3〜6個。title（短い名前）と explain（中身を短く）
- rules_for_us: このアカウントの投稿を書くときの具体的なルールに言い換えたもの3〜6個。
  「〜する」の形で、書き手がそのまま守れるくらい具体的に（例:「1行目は子どもの一言かその場面から始める」）。
- example: そのルールで書いた、このアカウント用の短い例文（2〜4行。体験談は作らず、あるあるとして）
- avoid: このアカウントでは取り入れないほうがいい点（煽り・収入アピール・誇大表現・ルール違反になるもの・
  人間らしさを損なうテクニックなど）
元の文章はそのまま使わない。JSON だけを返す。"""
    if has_images:
        system += "\n\n内容はスクリーンショット（画像）で渡します。まず画像の文字を正確に読み取ってから考えてください。"
    user = f"投稿者のメモ: {memo or 'なし'}\n\n内容:\n{content or '（スクリーンショットを見てください）'}"
    return system, user


def tips_note(patterns, limit=10):
    """登録した「考え方・コツ」から、文章作りに添えるルール集を作る。"""
    rules = []
    for p in patterns:
        if p.get("kind") == "tips":
            rules += p.get("rules_for_us", [])
    if not rules:
        return ""
    return ("登録した「考え方・コツ」から作ったルール（当てはまる投稿では取り入れる。ルールと人間らしさが優先）:\n"
            + "\n".join(f"- {r}" for r in rules[:limit]))


# ---------------------------------------------------------------- まとめサイトの記事

MATOME_SCHEMA = obj(
    title=STR, description=STR, slug=STR, intro=STR,
    items={"type": "array", "items": obj(id=STR, heading=STR, body=STR, good_for=STR)},
    closing=STR,
)


def matome_messages(account, today, topic, persona, event, candidates):
    """まとめサイトの記事（場面ごとの「買ってよかった」まとめ）を書く。"""
    system = f"""あなたは「{account['name']}」のまとめサイトの記事を書く人です。{_persona(account)}

テーマに合う楽天の商品の候補を渡します。この中から、読む人の役に立つものを4〜6個選んで、まとめ記事を書きます。
読む人は、その場面で困っている子育て中の親。検索や Pinterest から来て、何を買えばいいか早く知りたい人です。

- title: 検索されそうな言葉を前に入れた、32文字以内のタイトル（例:「入学準備で買ってよかった物まとめ｜名前付けが楽になる5選」）。「最強」「神」「おすすめ〇選！」のような煽りは使わない。
- description: 検索結果に出る説明。80〜110文字。
- slug: URL に使う英小文字とハイフンだけの短い名前（例: school-prep-name-labels）。
- intro: 書き出し。その場面のよくある困りごとを、話し言葉で2〜3文（150文字以内）。
- items: 選んだ商品。id は渡された id をそのまま使う。
  heading = その商品の一番の良さを一言で（20文字以内。商品名ではなく良さ）
  body = どんなところが良いと言われているか（レビューの評判として。100〜180文字）。体験していないので「使ってみた」とは書かない。
  good_for = こんな人に向いている、を一言（30文字以内）
- closing: しめくくり（100文字以内）。売り込まない。
- 価格やレビューの数字は渡されたものだけを使う。効果を断定しない。
{SHARED_RULES}
{HUMAN_STYLE}
JSON だけを返す。"""
    lines = [f"今日の日付: {today.isoformat()}", f"テーマ: {topic}", f"読む人: {persona}"]
    if event:
        lines.append(f"今の時期の行事: {event}")
    lines += ["", "商品の候補:"] + [_candidate_line(c) for c in candidates]
    return system, "\n".join(lines)
