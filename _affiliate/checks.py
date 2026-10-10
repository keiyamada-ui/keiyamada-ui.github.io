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

# 実際に使ったかどうかは人にしか分からないので、警告として知らせる
EXPERIENCE_WORDS = ["使ってみた", "使ってみました", "愛用", "うちの子", "我が家で", "買ってみた", "泊まってみた", "泊まりました"]


def _ng_hits(text):
    return [(w, reason) for w, reason in NG_WORDS.items() if w in text]


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
        if not room_comment.strip():
            errors.append("楽天ROOM: コメントが空です")
        if URL_PATTERN.search(room_comment) or LINK_PLACEHOLDER in room_comment:
            errors.append("楽天ROOM: コメントにリンクが入っています（ROOMは商品に直接つながるので不要）")
        if "#PR" not in room_comment:
            errors.append("楽天ROOM: コメントに「#PR」がありません")
        if len(room_comment) > THREADS_MAX_CHARS:
            errors.append(f"楽天ROOM: コメントが{len(room_comment)}文字です（{THREADS_MAX_CHARS}文字まで）")
        for word, reason in _ng_hits(room_comment):
            errors.append(f"楽天ROOM: NGワード「{word}」— {reason}")

    return errors, warnings
