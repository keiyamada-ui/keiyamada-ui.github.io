"""GitHub の Issue フォームの本文（### 見出し ごとの回答）を読み取る。"""

import re

NO_RESPONSE = "_No response_"


def parse(body):
    fields, current = {}, None
    for line in (body or "").splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            fields[current] = []
        elif current is not None:
            fields[current].append(line)
    out = {}
    for key, lines in fields.items():
        value = "\n".join(lines).strip()
        out[key] = "" if value == NO_RESPONSE else value
    return out


def checked(value):
    return "- [x]" in value.lower()


def first_url(value):
    m = re.search(r"https?://\S+", value or "")
    return m.group(0).rstrip(").,、。") if m else ""
