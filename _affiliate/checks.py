"""AI が書いた投稿文を、楽天・Threads・法律（景品表示法など）のルールで自動チェックする。

errors   = 直さないと投稿してはいけないもの（AI に書き直させる）
warnings = 人の目で確認してほしいもの（PR の本文に表示する）
"""

import re

THREADS_MAX_CHARS = 500
LINK_PLACEHOLDER = "{{LINK}}"
URL_PATTERN = re.compile(r"https?://|www\.|\.co\.jp|\.com/")

# 使うと違反・BAN のリスクが高い言葉（見つけたら書き直し）
NG_WORDS = {
    "稼げる": "「稼げる」系の言葉はスパム判定されやすい",
    "稼ぐ": "「稼ぐ」系の言葉はスパム判定されやすい",
    "収益": "収益の話はスパム判定されやすい",
    "副業": "副業の話はアカウントの趣旨と合わない",
    "必ず": "効果の断定は景品表示法上のリスク",
    "絶対": "効果の断定は景品表示法上のリスク",
    "確実に": "効果の断定は景品表示法上のリスク",
    "誰でも": "効果の断定は景品表示法上のリスク",
    "100%": "効果の断定は景品表示法上のリスク",
    "最安": "最安の断定は根拠が必要",
    "日本一": "No.1表示は根拠が必要",
    "No.1": "No.1表示は根拠が必要",
    "ナンバーワン": "No.1表示は根拠が必要",
    "頭が良くなる": "知育効果の断定は景品表示法上のリスク",
    "IQ": "知育効果の断定は景品表示法上のリスク",
    "天才": "効果を連想させる誇張表現",
    "治る": "医薬品的な効果の表現（薬機法）",
    "効く": "医薬品的な効果の表現（薬機法）",
    "痩せる": "痩身効果の表現（薬機法・景品表示法）",
    "背が伸びる": "成長効果の表現（薬機法・景品表示法）",
    "身長が伸びる": "成長効果の表現（薬機法・景品表示法）",
    "奇跡": "誇張表現",
    "魔法の": "誇張表現",
    "公式": "公式アカウントと誤解されるおそれ",
}

# AI が書いたと気づかれやすい言い回し（見つけたら書き直し）
AI_SMELL = ["いかがでしたか", "結論から言うと", "解説します", "ご紹介します", "まとめると", "と言えるでしょう",
            "てみてはいかがでしょうか", "徹底解説", "必見", "様々な", "することが大切です", "することが重要です"]

# 実際に使ったかどうかは人にしか分からないので、警告として知らせる
EXPERIENCE_WORDS = ["使ってみた", "使ってみました", "愛用", "うちの子", "我が家で", "買ってみた", "泊まってみた", "泊まりました"]


# 今の季節に合わない言葉（season.py が毎朝決める。例: まだ暖かいのに「ダウン」）
SEASON = {"avoid": [], "avg_max": None}


def _ng_hits(text):
    import season
    hits = [(w, reason) for w, reason in NG_WORDS.items() if w in text]
    for w in season.hits(text, SEASON["avoid"]):
        hits.append((w, f"今の季節（これから1週間の最高気温は平均{SEASON['avg_max']}℃）に合わない言葉です。今の気温に合う話にしてください"))
    return hits


def check_posts(posts, room_comment=None, owner_note=None):
    errors, warnings = [], []
    pr_posts = [p for p in posts if p.get("type") == "pr"]
    value_posts = [p for p in posts if p.get("type") == "value"]

    if len(pr_posts) != 1:
        errors.append(f"PR投稿はちょうど1本必要です（今は{len(pr_posts)}本）")
    if len(value_posts) != 2:
        errors.append(f"リンクなし投稿はちょうど2本必要です（今は{len(value_posts)}本）")

    for n, post in enumerate(posts, 1):
        label = f"投稿{n}（{'PR' if post.get('type') == 'pr' else 'リンクなし'}）"
        text = post.get("text", "")
        reply = post.get("reply_text", "") or ""

        if not text.strip():
            errors.append(f"{label}: 本文が空です")
        if len(text) > THREADS_MAX_CHARS:
            errors.append(f"{label}: 本文が{len(text)}文字です（Threadsの上限は{THREADS_MAX_CHARS}文字）")
        if URL_PATTERN.search(text) or LINK_PLACEHOLDER in text:
            errors.append(f"{label}: 本文にリンクが入っています（リンクは自分の投稿への返信に1つだけ）")

        parts = post.get("thread_parts") or []
        if post.get("type") == "pr" and parts:
            errors.append(f"{label}: PR投稿はツリーにしないでください")
        if len(parts) > 5:
            errors.append(f"{label}: ツリーが長すぎます（{len(parts)}個、5個まで）")
        for i, part in enumerate(parts, 2):
            if len(part) > THREADS_MAX_CHARS:
                errors.append(f"{label}: ツリー{i}つ目が{len(part)}文字です（上限{THREADS_MAX_CHARS}文字）")
            if URL_PATTERN.search(part) or LINK_PLACEHOLDER in part:
                errors.append(f"{label}: ツリー{i}つ目にリンクが入っています")

        whole = "\n".join([text, reply, *parts])
        for word, reason in _ng_hits(whole):
            errors.append(f"{label}: NGワード「{word}」— {reason}")
        errors += [f"{label}: {e}" for e in _ai_smell(whole) + _overused("\n".join([text, *parts]))]
        for word in EXPERIENCE_WORDS:
            if word in whole:
                hint = "メモの内容と合っているか確認してください" if owner_note else "実際に使った・泊まった場合だけ残してください"
                warnings.append(f"{label}: 「{word}」は体験談の表現です。{hint}")

        if post.get("type") == "value" and reply.strip():
            errors.append(f"{label}: リンクなし投稿に返信用の文が入っています")

        if post.get("type") == "pr":
            first_line = text.strip().splitlines()[0] if text.strip() else ""
            if "PR" not in first_line:
                errors.append(f"{label}: 本文の1行目に「PR」の表記がありません")
            if reply.count(LINK_PLACEHOLDER) != 1:
                errors.append(f"{label}: 返信用の文にリンクの置き場所 {LINK_PLACEHOLDER} がちょうど1つ必要です")
            if "#PR" not in reply:
                errors.append(f"{label}: 返信用の文に「#PR」がありません")
            if URL_PATTERN.search(reply.replace(LINK_PLACEHOLDER, "")):
                errors.append(f"{label}: 返信用の文に置き場所以外のリンクが入っています")
            if len(reply.replace(LINK_PLACEHOLDER, "x" * 60)) > THREADS_MAX_CHARS:
                errors.append(f"{label}: 返信用の文が長すぎます")

    if room_comment is not None:
        errors += check_room_comment(room_comment)

    return errors, warnings


def check_room_comment(comment):
    errors = []
    if not comment.strip():
        errors.append("楽天ROOM: コメントが空です")
    if URL_PATTERN.search(comment) or LINK_PLACEHOLDER in comment:
        errors.append("楽天ROOM: コメントにリンクが入っています（ROOMは商品に直接つながるので不要）")
    if "#PR" not in comment:
        errors.append("楽天ROOM: コメントに「#PR」がありません")
    if len(comment) > THREADS_MAX_CHARS:
        errors.append(f"楽天ROOM: コメントが{len(comment)}文字です（{THREADS_MAX_CHARS}文字まで）")
    for word, reason in _ng_hits(comment):
        errors.append(f"楽天ROOM: NGワード「{word}」— {reason}")
    return errors


# 最近の投稿で使いすぎている言い回し（variety.py が毎朝決める）。入っていたら書き直してもらう。
# 書き直しても残ったときは投稿を止めず、要確認にする（soften）
OVERUSED = []
VARIETY_TAG = "【言い回しのくり返し】"


def _overused(text):
    hits = [w for w in OVERUSED if w in text]
    return [f"{VARIETY_TAG}「{'」「'.join(hits)}」は最近の投稿で何度も使っています。別の言い方にしてください"] if hits else []


def soften(errors):
    """言い回しのくり返しだけは、投稿を止めるほどではないので (残すエラー, 要確認) に分ける。"""
    return [e for e in errors if VARIETY_TAG not in e], [e for e in errors if VARIETY_TAG in e]


def _ai_smell(text):
    return [f"「{w}」は AI が書いた感じが出る言い回しです。別の言い方にしてください" for w in AI_SMELL if w in text]


def check_simple_post(text, label, min_chars=1, max_chars=THREADS_MAX_CHARS):
    """集客投稿・つぶやきのチェック（リンク・宣伝なしの短い投稿）。"""
    errors = []
    if len(text.strip()) < min_chars:
        errors.append(f"{label}: 短すぎます（{len(text.strip())}文字、{min_chars}文字以上）")
    if len(text) > max_chars:
        errors.append(f"{label}: 長すぎます（{len(text)}文字、{max_chars}文字まで）")
    if URL_PATTERN.search(text) or LINK_PLACEHOLDER in text:
        errors.append(f"{label}: リンクは入れないでください")
    if "PR" in text:
        errors.append(f"{label}: 宣伝ではない投稿なので「PR」は入れないでください")
    if "#" in text or "＃" in text:
        errors.append(f"{label}: ハッシュタグは入れないでください")
    for word, reason in _ng_hits(text):
        errors.append(f"{label}: NGワード「{word}」— {reason}")
    errors += [f"{label}: {e}" for e in _ai_smell(text) + _overused(text)]
    return errors
