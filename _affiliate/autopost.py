"""作った下書きを Threads に自動で投稿する。

    python _affiliate/autopost.py              # 今の時間帯（朝・昼・夜）の投稿をする
    python _affiliate/autopost.py --slot 3     # 夜の枠（PR 投稿）を今すぐ投稿する
    python _affiliate/autopost.py --dry-run    # 何を投稿するかだけ表示する（投稿しない）
    python _affiliate/autopost.py --check      # Threads につながるか・トークンの期限が近くないか確認する

朝 = リンクなし投稿1 / 昼 = リンクなし投稿2（ツリー可）/ 夜 = PR 投稿（本文 → 返信にリンク）。
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
SLOT_NAMES = {1: "朝（リンクなし投稿1）", 2: "昼（リンクなし投稿2）", 3: "夜（PR 投稿）"}


def slot_for(now):
    """GitHub の定期実行は遅れることがあるので、時刻ではなく時間帯で判断する。"""
    if now.hour < 11:
        return 1
    if now.hour < 17:
        return 2
    return 3


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


def pick(slot, today, config, drafts_dir, posted):
    """この枠で出す（下書き, 投稿）を決める。出さないときは (None, None, 理由)。"""
    auto = config["auto_post"]
    done = {(p["draft"], p["post_index"]) for p in posted}

    if slot in (1, 2):
        name = f"{today.isoformat()}.json"
        draft = load_draft(Path(drafts_dir) / name)
        if not draft:
            return None, None, "今日の下書きがまだありません（朝の下書き作りが失敗した可能性があります）"
        values = [i for i, p in enumerate(draft["posts"]) if p["type"] == "value"]
        if len(values) < slot:
            return None, None, "リンクなし投稿が見つかりません"
        if draft["errors"]:
            return None, None, "自動チェックでエラーが残っているため投稿しませんでした"
        # 朝はリンクなし投稿1。昼は、朝の分が出ていなければそれを、出ていれば投稿2を出す
        wanted = values[:1] if slot == 1 else values[:2]
        index = next((i for i in wanted if (name, i) not in done), None)
        if index is None:
            return None, None, "この投稿はすでに出しています"
        return name, index, None

    # 夜の枠: PR 投稿
    start = auto["pr_posts_from"]
    start = start if isinstance(start, datetime.date) else datetime.date.fromisoformat(str(start))
    if today < start:
        return None, None, f"アカウントを育てる期間のため、PR 投稿は {start.isoformat()} から始めます"
    last_pr = max((datetime.date.fromisoformat(p["date"]) for p in posted if p["kind"] == "pr"), default=None)
    if last_pr and (today - last_pr).days < auto["pr_min_interval_days"]:
        return None, None, f"前回の PR 投稿（{last_pr.isoformat()}）から {auto['pr_min_interval_days']} 日たっていないため、今日はお休みです"

    candidates = sorted(Path(drafts_dir).glob("*-item-*.json"))  # 推し商品フォームの下書きを優先
    candidates.append(Path(drafts_dir) / f"{today.isoformat()}.json")
    for path in candidates:
        draft = load_draft(path)
        if not draft or draft["date"] > today.isoformat() or draft["errors"]:
            continue
        index = next((i for i, p in enumerate(draft["posts"]) if p["type"] == "pr"), None)
        if index is not None and (path.name, index) not in done:
            return path.name, index, None
    return None, None, "投稿できる PR の下書きがありません（エラーが残っているか、すでに投稿済みです）"


def publish(client, post, ids):
    """本文を投稿し、ツリーや返信（リンク）を自分の投稿への返信としてつなげる。
    途中で失敗しても、出せた分は ids に残る（二重投稿を防ぐ記録に使う）。"""
    first = client.post_text(post["text"])
    ids.append(first)
    parent = first
    for part in post.get("thread_parts") or []:
        parent = client.post_text(part, reply_to=parent)
        ids.append(parent)
    if post["type"] == "pr" and post.get("reply_text"):
        ids.append(client.post_text(post["reply_text"], reply_to=first))
    return client.permalink(first)


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
    record_posted(posted_dir, today, entry)
    extra = f"（ツリー {len(post['thread_parts']) + 1} 件）" if post.get("thread_parts") else ""
    extra += "（返信にリンク）" if post["type"] == "pr" else ""
    lines += [f"✅ 投稿しました{extra}: {link or '（リンク取得できず）'}", "", "```text", post["text"].strip(), "```"]
    if post["type"] == "pr" and draft["chosen"].get("is_hidden_gem"):
        lines.append("💎 発掘枠の商品です。レビューが少ないので、商品ページも確認しておいてください")
    lines.append("")
    lines.append("良くないと思ったら、Threads アプリでこの投稿の「…」→「削除」で消してください。")
    return "\n".join(lines) + "\n", True


TOKEN_LIFETIME_DAYS = 60
TOKEN_WARN_DAYS = 50


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


def check(token, config, today):
    me = ThreadsClient(token).me()
    print(f"✅ Threads につながりました: @{me.get('username')}（ID {me.get('id')}）")
    if me.get("username") != "kotori.family":
        print("⚠️ kotori.family 以外のアカウントです。トークンを作ったアカウントを確認してください")
        return 1
    warning = token_age_warning(config, today)
    if warning:
        print(f"⚠️ {warning}")
        write_output(token_warning=warning)
    return 0


def write_output(**values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}<<__END__\n{value}\n__END__\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="ことり｜下書きを Threads に自動投稿する")
    parser.add_argument("--slot", choices=["auto", "1", "2", "3"], default="auto")
    parser.add_argument("--date", help="日付（例: 2026-10-10）。省略すると今日（日本時間）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="Threads につながるか・トークンの期限を確認する")
    args = parser.parse_args(argv)

    token = os.environ.get("KOTORI_THREADS_TOKEN")
    config = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    now = datetime.datetime.now(JST)
    today = datetime.date.fromisoformat(args.date) if args.date else now.date()
    if args.check:
        return check(token, config, today)
    slot = slot_for(now) if args.slot == "auto" else int(args.slot)
    if not config.get("auto_post", {}).get("enabled"):
        print("⏸ config.yaml の auto_post.enabled が false のため、自動投稿しません")
        write_output(posted="false", report="")
        return 0
    client = None if args.dry_run else ThreadsClient(token)
    report, posted = run(slot, today, config, HERE / "drafts", HERE / "data" / "posted", client, args.dry_run)
    print(report)
    write_output(posted="true" if posted else "false", report=report, date=today.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
