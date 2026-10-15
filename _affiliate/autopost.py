"""作った下書きを Threads に自動で投稿する。

    python _affiliate/autopost.py              # 今の時間帯の投稿をする
    python _affiliate/autopost.py --slot 5     # 夕方の枠（PR 投稿）を今すぐ投稿する
    python _affiliate/autopost.py --dry-run    # 何を投稿するかだけ表示する（投稿しない）
    python _affiliate/autopost.py --check      # Threads につながるか・権限・トークンの期限を確認する

1日5回: 朝=集客投稿 / 午前=つぶやき / 昼=役立つ投稿 / 午後=つぶやき / 夜=PR 投稿（本文 → 返信にリンク）。
夜は PR 投稿のない日、役立つ投稿の2本目かつぶやきを出す。
同じ投稿を二度出さないよう、出した投稿は data/posted/ に記録する。
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from threads import ThreadsClient  # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9))
SLOT_NAMES = {1: "朝（集客投稿）", 2: "午前（つぶやき）", 3: "昼（役立つ投稿）", 4: "午後（つぶやき）", 5: "夕方（PR 投稿）"}
# 枠ごとに、出すものの優先順（前のものがなければ次を出す）
SLOT_KINDS = {1: ["buzz", "value"], 2: ["casual"], 3: ["value"], 4: ["casual"], 5: ["pr", "value", "casual"]}
# 各枠の開始時刻と締め切り（日本時間・0時からの分）。
# GitHub の定期実行は数時間遅れることがあるため、20分おきに起動して「開始時刻を過ぎて、まだ出していない枠」を出す。
# 締め切りを過ぎた枠は出さない（集客投稿は大事なので、昼の役立つ投稿の後まで待つ）
SLOT_START = {1: 7 * 60 + 40, 2: 10 * 60 + 10, 3: 12 * 60 + 20, 4: 15 * 60 + 40, 5: 17 * 60 + 40}
SLOT_DEADLINE = {1: 14 * 60, 2: 12 * 60 + 20, 3: 15 * 60 + 40, 4: 17 * 60 + 40, 5: 24 * 60}
MIN_GAP_MINUTES = 60  # 遅れを取り戻すときも、投稿どうしは60分以上あける
FOLLOWUP_DAYS = 3


def _minutes(now):
    return now.hour * 60 + now.minute


def slot_for(now):
    """今の時刻にいちばん近い枠（手動で --slot を指定しないときの目安）。"""
    minutes = _minutes(now)
    started = [s for s, start in SLOT_START.items() if start <= minutes]
    return started[-1] if started else 1


def due_slot(now, posted):
    """今出すべき枠を返す: (枠, None) / 出さないとき (None, 理由)。"""
    today = now.date().isoformat()
    mine = [p for p in posted if p["date"] == today and not p.get("manual")]
    done = {p["slot"] for p in mine}
    minutes = _minutes(now)
    pending = [s for s in SLOT_START if SLOT_START[s] <= minutes < SLOT_DEADLINE[s] and s not in done]
    if not pending:
        return None, "今出す枠はありません"
    times = [datetime.datetime.fromisoformat(p["at"]) for p in mine if p.get("at")]
    if times and (now - max(times)).total_seconds() < MIN_GAP_MINUTES * 60:
        return None, f"前回の投稿から{MIN_GAP_MINUTES}分たっていないため、次の起動で出します"
    return pending[0], None


def load_posted(directory):
    directory = Path(directory)
    out = []
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        out.extend(json.loads(path.read_text(encoding="utf-8")))
    return out


def record_posted(directory, today, entry):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{today.isoformat()}.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_draft(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None


def _first_unposted(name, draft, kind, done):
    return next((i for i, p in enumerate(draft["posts"]) if p["type"] == kind and (name, i) not in done), None)


def _pick_simple(kind, today, drafts_dir, done):
    """集客投稿（buzz）・つぶやき（casual）・役立つ投稿（value）"""
    suffix = {"buzz": "-buzz", "casual": "-casual", "value": ""}[kind]
    label = {"buzz": "集客投稿", "casual": "つぶやき", "value": "役立つ投稿"}[kind]
    name = f"{today.isoformat()}{suffix}.json"
    draft = load_draft(Path(drafts_dir) / name)
    if not draft:
        return None, None, f"今日の{label}の下書きがありません"
    if draft["errors"]:
        return None, None, f"{label}の下書きに自動チェックのエラーが残っているため投稿しませんでした"
    index = _first_unposted(name, draft, kind, done)
    if index is None:
        return None, None, f"今日の{label}はすべて出しました"
    return name, index, None


def _pick_pr(today, config, drafts_dir, posted, done):
    auto = config["auto_post"]
    start = auto["pr_posts_from"]
    start = start if isinstance(start, datetime.date) else datetime.date.fromisoformat(str(start))
    if today < start:
        return None, None, f"アカウントを育てる期間のため、PR 投稿は {start.isoformat()} から始めます"
    last_pr = max((datetime.date.fromisoformat(p["date"]) for p in posted if p["kind"] == "pr"), default=None)
    if last_pr and (today - last_pr).days < auto["pr_min_interval_days"]:
        return None, None, f"前回の PR 投稿（{last_pr.isoformat()}）から {auto['pr_min_interval_days']} 日たっていないため、今日はお休みです"

    # 優先順: 推し商品フォーム → 反響のあった話題の PR（3日以内）→ 今日の下書き
    candidates = sorted(Path(drafts_dir).glob("*-item-*.json"))
    for days in range(FOLLOWUP_DAYS, 0, -1):
        path = Path(drafts_dir) / f"{(today - datetime.timedelta(days=days)).isoformat()}.json"
        draft = load_draft(path)
        if draft and draft.get("followup"):
            candidates.append(path)
    candidates.append(Path(drafts_dir) / f"{today.isoformat()}.json")
    for path in candidates:
        draft = load_draft(path)
        if not draft or draft["date"] > today.isoformat() or draft["errors"]:
            continue
        index = _first_unposted(path.name, draft, "pr", done)
        if index is not None:
            return path.name, index, None
    return None, None, "投稿できる PR の下書きがありません（エラーが残っているか、すでに投稿済みです）"


def pick(slot, today, config, drafts_dir, posted):
    """この枠で出す（下書き, 投稿の番号）を決める。出さないときは (None, None, 理由)。"""
    done = {(p["draft"], p["post_index"]) for p in posted}
    reasons = []
    for kind in SLOT_KINDS[slot]:
        if kind == "pr":
            name, index, reason = _pick_pr(today, config, drafts_dir, posted, done)
        else:
            name, index, reason = _pick_simple(kind, today, drafts_dir, done)
        if name:
            return name, index, None
        reasons.append(reason)
    return None, None, " ／ ".join(reasons)


def publish(client, post, ids):
    """本文を投稿し、ツリーや返信（リンク）を自分の投稿への返信としてつなげる。
    途中で失敗しても、出せた分は ids に残る（二重投稿を防ぐ記録に使う）。"""
    first = None
    if post.get("image_url") and post["type"] != "pr":
        try:  # イラストつき。うまくいかなければ文章だけで出す
            first = client.post_text(post["text"], topic_tag=post.get("topic_tag") or None, image_url=post["image_url"])
            post["_with_image"] = True
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ イラストつきで投稿できなかったので、文章だけで出します: {str(e)[:150]}")
    if first is None:
        first = client.post_text(post["text"], topic_tag=post.get("topic_tag") or None)
    ids.append(first)
    parent = first
    for part in post.get("thread_parts") or []:
        parent = client.post_text(part, reply_to=parent)
        ids.append(parent)
    if post["type"] == "pr" and post.get("reply_text"):
        ids.append(client.post_text(post["reply_text"], reply_to=first))
    return client.permalink(first)


KIND_NAMES = {"buzz": "集客投稿", "casual": "つぶやき", "value": "役立つ投稿", "pr": "PR 投稿"}


def slot_kind_changed(slot, kind):
    """枠の本来の投稿ではなく、代わりのものを出したとき True。"""
    return SLOT_KINDS[slot][0] != kind


def run(slot, today, config, drafts_dir, posted_dir, client=None, dry_run=False):
    posted = load_posted(posted_dir)
    name, index, reason = pick(slot, today, config, drafts_dir, posted)
    lines = [f"### {SLOT_NAMES[slot]}"]
    if not name:
        lines.append(f"⏸ 投稿なし — {reason}")
        return "\n".join(lines) + "\n", False
    draft = load_draft(Path(drafts_dir) / name)
    post = draft["posts"][index]
    preview = post["text"].strip().splitlines()[0][:60]
    if dry_run:
        lines.append(f"🧪 お試し: 「{preview}…」を投稿する予定（{name}）")
        return "\n".join(lines) + "\n", False
    ids = []
    entry = {"date": today.isoformat(), "slot": slot, "draft": name, "post_index": index, "kind": post["type"],
             "ids": ids, "permalink": "", "at": datetime.datetime.now(JST).isoformat(timespec="minutes")}
    try:
        link = publish(client, post, ids)
    except Exception:
        if ids:  # 本文だけ出て、ツリーや返信で失敗した。再実行で本文が二重に出ないよう記録しておく
            entry["partial"] = True
            record_posted(posted_dir, today, entry)
        raise
    entry["permalink"] = link
    if post.pop("_with_image", False):
        entry["image"] = True
    record_posted(posted_dir, today, entry)
    extra = f"（ツリー {len(post['thread_parts']) + 1} 件）" if post.get("thread_parts") else ""
    extra += "（返信にリンク）" if post["type"] == "pr" else ""
    extra += f"（{KIND_NAMES.get(post['type'], '')}）" if slot_kind_changed(slot, post["type"]) else ""
    lines += [f"✅ 投稿しました{extra}: {link or '（リンク取得できず）'}", "", "```text", post["text"].strip(), "```"]
    if post["type"] == "pr" and draft.get("followup"):
        lines.append(f"🔥 反響のあった集客投稿（いいね{draft['followup']['likes']}件）の話題から選んだ商品です")
    if post["type"] == "pr" and draft["chosen"].get("is_hidden_gem"):
        lines.append("💎 発掘枠の商品です。レビューが少ないので、商品ページも確認しておいてください")
    lines.append("")
    lines.append("良くないと思ったら、Threads アプリでこの投稿の「…」→「削除」で消してください。")
    return "\n".join(lines) + "\n", True


TOKEN_LIFETIME_DAYS = 60
TOKEN_WARN_DAYS = 50


TOKEN_REMIND_DAYS_LEFT = 10


def token_days_left(config, today):
    updated = config.get("auto_post", {}).get("token_updated")
    if not updated:
        return None
    updated = updated if isinstance(updated, datetime.date) else datetime.date.fromisoformat(str(updated))
    return TOKEN_LIFETIME_DAYS - (today - updated).days


def token_age_warning(config, today):
    """トークンは60日で切れる。登録した日（config の token_updated）から50日たったら知らせる。"""
    updated = config.get("auto_post", {}).get("token_updated")
    if not updated:
        return "config.yaml の auto_post.token_updated に、トークンを登録した日を書いてください（期限切れを知らせるため）"
    updated = updated if isinstance(updated, datetime.date) else datetime.date.fromisoformat(str(updated))
    age = (today - updated).days
    if age >= TOKEN_WARN_DAYS:
        left = TOKEN_LIFETIME_DAYS - age
        return (f"Threads のトークンを登録してから {age} 日たちました（あと約 {max(left, 0)} 日で期限切れ）。"
                "トークンを作り直して Secrets の KOTORI_THREADS_TOKEN を更新し、config.yaml の token_updated を今日の日付にしてください")
    return None


def check_permissions(client):
    """反響の取得・コメントの取得に必要な権限があるか、最近の投稿で試す。"""
    ids = client.recent_ids(1)
    if not ids:
        return ["ℹ️ まだ投稿がないため、反響・コメントの権限は確認できませんでした（最初の投稿のあとにもう一度確認してください）"]
    lines = []
    for name, call, perm in (("投稿の反響（いいね数など）", client.insights, "threads_manage_insights"),
                             ("コメントの取得", client.replies, "threads_read_replies")):
        try:
            call(ids[0])
            lines.append(f"✅ {name}: 取得できます")
        except Exception as e:  # noqa: BLE001
            lines.append(f"⚠️ {name}: 取得できません。Meta のアプリで権限「{perm}」を追加し、"
                         f"トークンを作り直して Secrets を更新してください（{str(e)[:100]}）")
    return lines


def check(token, config, today):
    client = ThreadsClient(token)
    me = client.me()
    print(f"✅ Threads につながりました: @{me.get('username')}（ID {me.get('id')}）")
    if me.get("username") != "kotori.family":
        print("⚠️ kotori.family 以外のアカウントです。トークンを作ったアカウントを確認してください")
        return 1
    for line in check_permissions(client):
        print(line)
    warning = token_age_warning(config, today)
    if warning:
        print(f"⚠️ {warning}")
        write_output(token_warning=warning)
    return 0


def mark_manual(drafts_dir, posted_dir, draft_name, index, now, undo=False):
    """管理画面の「手で投稿した」ボタンから呼ばれる。自動投稿で二重に出さないよう記録する。"""
    if not draft_name.endswith(".json") or "/" in draft_name or ".." in draft_name:
        print(f"❌ 下書きの名前が正しくありません: {draft_name}")
        return 1
    draft = load_draft(Path(drafts_dir) / draft_name)
    if not draft or not 0 <= index < len(draft["posts"]):
        print(f"❌ 下書きが見つかりません: {draft_name} の {index} 番")
        return 1
    posted_dir = Path(posted_dir)
    if undo:
        for path in sorted(posted_dir.glob("*.json")) if posted_dir.exists() else []:
            entries = json.loads(path.read_text(encoding="utf-8"))
            kept = [e for e in entries if not (e.get("manual") and e["draft"] == draft_name and e["post_index"] == index)]
            if len(kept) != len(entries):
                path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"↩️ 「投稿済み」を取り消しました: {draft_name} の {index} 番")
        return 0
    if any(p["draft"] == draft_name and p["post_index"] == index for p in load_posted(posted_dir)):
        print("✅ すでに投稿済みになっています")
        return 0
    record_posted(posted_dir, now.date(), {
        "date": now.date().isoformat(), "slot": 0, "draft": draft_name, "post_index": index,
        "kind": draft["posts"][index]["type"], "ids": [], "permalink": "", "manual": True,
        "at": now.isoformat(timespec="minutes")})
    print(f"✋ 手で投稿した記録を付けました: {draft_name} の {index} 番")
    return 0


def write_output(**values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}<<__END__\n{value}\n__END__\n")


def remove_image(drafts_dir, draft_name, index):
    """管理画面の「画像を外す」から呼ばれる。イラストを付けずに文章だけで投稿するようにする。"""
    if not draft_name.endswith(".json") or "/" in draft_name or ".." in draft_name:
        print(f"❌ 下書きの名前が正しくありません: {draft_name}")
        return 1
    path = Path(drafts_dir) / draft_name
    draft = load_draft(path)
    if not draft or index >= len(draft["posts"]):
        print("❌ 下書きが見つかりません")
        return 1
    post = draft["posts"][index]
    post.pop("image", None)
    post.pop("image_url", None)
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"🖼️ イラストを外しました: {draft_name} の {index + 1} 本目")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="ことり｜下書きを Threads に自動投稿する")
    parser.add_argument("--slot", choices=["auto", "1", "2", "3", "4", "5"], default="auto")
    parser.add_argument("--date", help="日付（例: 2026-10-10）。省略すると今日（日本時間）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="Threads につながるか・トークンの期限を確認する")
    parser.add_argument("--mark", nargs=2, metavar=("DRAFT", "INDEX"), help="手で投稿した投稿を「投稿済み」にする")
    parser.add_argument("--undo", action="store_true", help="--mark と一緒に使う: 「投稿済み」を取り消す")
    parser.add_argument("--noimage", nargs=2, metavar=("DRAFT", "INDEX"), help="投稿からイラストを外す")
    args = parser.parse_args(argv)

    if args.noimage:
        return remove_image(HERE / "drafts", args.noimage[0], int(args.noimage[1]))
    token = os.environ.get("KOTORI_THREADS_TOKEN")
    config = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    now = datetime.datetime.now(JST)
    today = datetime.date.fromisoformat(args.date) if args.date else now.date()
    if args.check:
        return check(token, config, today)
    if args.mark:
        return mark_manual(HERE / "drafts", HERE / "data" / "posted", args.mark[0], int(args.mark[1]), now, args.undo)
    if args.slot == "auto":
        slot, reason = due_slot(now, load_posted(HERE / "data" / "posted"))
        if slot is None:
            # 20分おきに起動するので、出さないときはレポートを書かない
            print(f"⏸ {reason}")
            write_output(posted="false", report="", date=today.isoformat())
            return 0
    else:
        slot = int(args.slot)
    if not config.get("auto_post", {}).get("enabled"):
        print("⏸ config.yaml の auto_post.enabled が false のため、自動投稿しません")
        write_output(posted="false", report="")
        return 0
    if not token and not args.dry_run:
        report = f"### {SLOT_NAMES[slot]}\n⏸ 投稿なし — Threads のトークン（Secrets の KOTORI_THREADS_TOKEN）がまだ登録されていません\n"
        print(report)
        write_output(posted="false", report=report, date=today.isoformat())
        return 0
    client = None if args.dry_run else ThreadsClient(token)
    report, posted = run(slot, today, config, HERE / "drafts", HERE / "data" / "posted", client, args.dry_run)
    left = token_days_left(config, today)
    if left is not None and left <= TOKEN_REMIND_DAYS_LEFT:
        report += (f"\n🔑 **Threads のトークンの期限まで、あと {max(left, 0)} 日です。** "
                   "作り直して Secrets の KOTORI_THREADS_TOKEN を更新してください\n")
    print(report)
    write_output(posted="true" if posted else "false", report=report, date=today.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
