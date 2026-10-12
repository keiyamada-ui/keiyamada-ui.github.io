"""勝ちパターン集: 「参考投稿」フォームから AI が分析した結果を、GitHub の Issue から読み込む。

分析結果は github-actions が Issue にコメントとして残す。「勝ちパターン」ラベルの付いた
開いている Issue だけを使うので、使いたくなくなったパターンは Issue を Close すれば外れる。
"""

import json
import re

import requests

MARK = "<!-- kotori-pattern -->"
LABEL = "勝ちパターン"
BOT = "github-actions[bot]"
_JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)


def format_comment(analysis):
    if analysis.get("kind") == "tips":
        lines = [MARK, "## 💡 考え方・コツの分析", "", f"**概要**: {analysis['summary']}", "", "**要点**"]
        lines += [f"- {s}" for s in analysis["structure"]]
        lines += ["", "**ことり で使うルール**"] + [f"{n}. {s}" for n, s in enumerate(analysis["rules_for_us"], 1)]
        lines += ["", "**例文**", "", analysis.get("example", ""), "", "**取り入れないこと**"] + [f"- {s}" for s in analysis["avoid"]]
        lines += ["", "この Issue を開いている間は、毎朝の文章作りでこのルールが使われます。外したいときは Close してください。",
                  "", "<details><summary>データ</summary>", "", "```json", json.dumps(analysis, ensure_ascii=False, indent=1),
                  "```", "", "</details>"]
        return "\n".join(lines)
    lines = [MARK, "## 🔍 この投稿の分析", "", f"**概要**: {analysis['summary']}",
             f"**書き出しの型**: {analysis['hook_type']}", "", "**構成**"]
    lines += [f"{n}. {s}" for n, s in enumerate(analysis["structure"], 1)]
    lines += ["", "**伸びた理由**"] + [f"- {s}" for s in analysis["why_it_worked"]]
    lines += ["", f"**ことり用に言い換えた型**: {analysis['reusable_pattern']}", "", "**真似しないこと**"]
    lines += [f"- {s}" for s in analysis["avoid"]]
    theme = analysis.get("theme") or {}
    if theme.get("keyword"):
        lines += ["", f"**テーマ候補**: {theme.get('persona', '')}（楽天で「{theme['keyword']}」を検索）"]
    lines += ["", "この Issue を開いている間は、毎朝の下書きでこの型が参考にされます。外したいときは Close してください。",
              "", "<details><summary>データ</summary>", "", "```json", json.dumps(analysis, ensure_ascii=False, indent=1),
              "```", "", "</details>"]
    return "\n".join(lines)


def parse_comment(body):
    if MARK not in body:
        return None
    m = _JSON_BLOCK.search(body)
    return json.loads(m.group(1)) if m else None


def fetch_patterns(repo, token, limit=10, session=None):
    """失敗しても下書き作りは止めない（勝ちパターンなしで書く）。"""
    if not (repo and token):
        return []
    http = session or requests
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        res = http.get(f"https://api.github.com/repos/{repo}/issues", headers=headers, timeout=30,
                       params={"labels": LABEL, "state": "open", "per_page": limit})
        res.raise_for_status()
        out = []
        for issue in res.json():
            comments = http.get(issue["comments_url"], headers=headers, timeout=30)
            comments.raise_for_status()
            for c in comments.json():
                if c["user"]["login"] == BOT:
                    data = parse_comment(c["body"])
                    if data:
                        out.append(data)
        return out
    except Exception as e:  # noqa: BLE001 - 勝ちパターンは補助なので、取れなくても続ける
        print(f"⚠️ 勝ちパターンを読み込めませんでした（なしで続けます）: {e}")
        return []
