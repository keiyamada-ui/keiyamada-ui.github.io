"""Pinterest の自動投稿（Pinterest API の審査に通ったら使う）。

    python _affiliate/pinterest_api.py connect CODE   # 管理画面の「Pinterest とつなぐ」から（最初に1回）
    python _affiliate/pinterest_api.py post-due       # 自動投稿の見回りのたびに: 時刻を過ぎた枠があれば1枚出す
    python _affiliate/pinterest_api.py check          # つながっているか確認

必要な GitHub Secrets: PINTEREST_APP_ID・PINTEREST_APP_SECRET・KOTORI_STORE_KEY。
鍵（トークン）は KOTORI_STORE_KEY で暗号化して data/pinterest/ に保存し、使うたびに新しくする。
つながっていなければ何もしない（それまでは管理画面の「週1回のまとめて予約」を使う）。
"""

import argparse
import base64
import datetime
import json
import os
import sys
from pathlib import Path

import requests
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pins as pins_mod  # noqa: E402
import push  # noqa: E402

TOKEN_FILE = "pinterest.enc"
REDIRECT_URI = "https://keiyamada-ui.github.io/kotori/pinterest.html"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
JST = pins_mod.JST


class PinterestError(Exception):
    pass


def _conf():
    config = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    return config.get("pinterest", {})


def _base():
    # 審査の最初の段階（Trial）では、お試し用の窓口（api-sandbox）しか使えない
    return _conf().get("api_base", "https://api.pinterest.com/v5").rstrip("/")


def _app_auth():
    app_id, secret = os.environ.get("PINTEREST_APP_ID", ""), os.environ.get("PINTEREST_APP_SECRET", "")
    if not (app_id and secret):
        raise PinterestError("GitHub Secrets に PINTEREST_APP_ID と PINTEREST_APP_SECRET を登録してください")
    return "Basic " + base64.b64encode(f"{app_id}:{secret}".encode()).decode()


def _token_request(data):
    r = requests.post("https://api.pinterest.com/v5/oauth/token", data=data,
                      headers={"Authorization": _app_auth()}, timeout=30)
    if r.status_code != 200:
        raise PinterestError(f"Pinterest の鍵を取れませんでした（{r.status_code} {r.text[:200]}）")
    tok = r.json()
    now = datetime.datetime.now(datetime.timezone.utc)
    return {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", data.get("refresh_token", "")),
            "expires_at": (now + datetime.timedelta(seconds=int(tok.get("expires_in", 2592000)) - 3600)).isoformat()}


def connect(code):
    if not push._fernet():
        raise PinterestError("GitHub Secrets に KOTORI_STORE_KEY を登録してください")
    tok = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
    push._write(TOKEN_FILE, tok)
    me = _api("GET", "/user_account", tok)
    print(f"✅ Pinterest とつながりました（@{me.get('username', '')}）")
    return tok


def _token():
    tok = push._read(TOKEN_FILE, None)
    if not tok:
        return None
    if datetime.datetime.fromisoformat(tok["expires_at"]) < datetime.datetime.now(datetime.timezone.utc):
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        push._write(TOKEN_FILE, tok)
    return tok


def _api(method, path, tok, **kw):
    r = requests.request(method, _base() + path, headers={"Authorization": "Bearer " + tok["access_token"]},
                         timeout=60, **kw)
    if r.status_code >= 300:
        raise PinterestError(f"Pinterest API {method} {path}: {r.status_code} {r.text[:200]}")
    return r.json() if r.text else {}


def boards(tok):
    out, bookmark = {}, None
    while True:
        res = _api("GET", "/boards", tok, params={"page_size": 100, **({"bookmark": bookmark} if bookmark else {})})
        out.update({b["name"]: b["id"] for b in res.get("items", [])})
        bookmark = res.get("bookmark")
        if not bookmark:
            return out


def board_id(tok, name, cache):
    if not cache:
        cache.update(boards(tok))
    if name not in cache:  # ボードがなければ作る
        cache[name] = _api("POST", "/boards", tok, json={"name": name, "privacy": "PUBLIC"})["id"]
    return cache[name]


def create_pin(tok, pin, bid):
    res = _api("POST", "/pins", tok, json={
        "board_id": bid, "title": pin["title"][:100], "description": pin["description"][:500], "link": pin["link"],
        "alt_text": pin.get("product", "")[:500],
        "media_source": {"source_type": "image_url", "url": pin["image_url"]},
    })
    return res["id"]


def due_slots(now):
    """今日の枠のうち、時刻を過ぎたもの（日本時間 8:00・20:30）。"""
    out = []
    for h, m in pins_mod.SLOTS:
        t = datetime.datetime.combine(now.date(), datetime.time(h, m), JST)
        if now >= t:
            out.append(t.isoformat(timespec="minutes"))
    return out


def post_due(now=None, manual_dir=None, tok=None, create=None):
    """時刻を過ぎて、まだ出していない枠があれば、予約待ちのピンを1枚出す。返り値: 出したピン（なければ None）。"""
    now = now or datetime.datetime.now(JST)
    tok = tok or _token()
    if not tok:
        return None
    path = Path(manual_dir or HERE / "manual") / "pins.json"
    pins = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    done = {p.get("slot") for p in pins if p.get("slot")}
    slot = next((s for s in due_slots(now) if s not in done), None)
    todo = [p for p in sorted(pins, key=lambda p: p["date"])
            if not p.get("pin_id") and not p.get("scheduled_at") and not p.get("posted_by_hand") and p.get("tries", 0) < 3]
    if not slot or not todo:
        return None
    pin = todo[0]
    try:
        cache = {}
        create = create or (lambda p: create_pin(tok, p, board_id(tok, p["board"], cache)))
        pid = create(pin)
        pin.update(pin_id=pid, pin_url=f"https://www.pinterest.com/pin/{pid}/", slot=slot,
                   posted_at=now.isoformat(timespec="minutes"))
        pin.pop("error", None)
        print(f"📌 Pinterest に投稿しました: {pin['title'][:30]} → {pin['pin_url']}")
    except Exception as e:  # noqa: BLE001
        pin["tries"] = pin.get("tries", 0) + 1
        pin["error"] = str(e)[:200]
        print(f"⚠️ Pinterest に投稿できませんでした: {pin['error']}")
        if pin["tries"] >= 3:
            push.main(["send", "--title", "⚠️ Pinterest に投稿できませんでした", "--body", "管理画面の「📌 Pinterest」を確認してください",
                       "--url", "https://keiyamada-ui.github.io/kotori/pins.html"])
    path.write_text(json.dumps(pins, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return pin


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["connect", "post-due", "check"])
    ap.add_argument("code", nargs="?", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "connect":
            connect(a.code or os.environ.get("PINTEREST_CODE", ""))
        elif a.cmd == "check":
            tok = _token()
            if not tok:
                print("Pinterest とはまだつながっていません")
                return 1
            print("✅ つながっています: @" + _api("GET", "/user_account", tok).get("username", ""))
        else:
            if not push._fernet() or not (push.STORE / TOKEN_FILE).exists():
                return 0  # まだつながっていない
            post_due()
    except PinterestError as e:
        print(f"⚠️ {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
