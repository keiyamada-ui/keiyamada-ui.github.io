"""スマホへの通知（Web Push）と、アプリのアイコンの赤いバッジ。

    python _affiliate/push.py setup                 # 最初に1回: 通知用の鍵を作る
    python _affiliate/push.py subscribe '<JSON>'    # 管理画面で「通知をオン」にした端末を登録する
    python _affiliate/push.py send --title ... --body ... [--url ...] [--add 1]

鍵と登録した端末の情報は、GitHub Secrets の KOTORI_STORE_KEY で暗号化して data/push/ に保存する
（公開リポジトリなので、そのままでは置かない）。KOTORI_STORE_KEY がなければ何もしない。
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "push"
SITE = "https://keiyamada-ui.github.io/kotori/"


def _fernet():
    from cryptography.fernet import Fernet
    secret = os.environ.get("KOTORI_STORE_KEY", "")
    if not secret:
        return None
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _read(name, default):
    f, path = _fernet(), STORE / name
    if not f or not path.exists():
        return default
    return json.loads(f.decrypt(path.read_bytes()))


def _write(name, value):
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / name).write_bytes(_fernet().encrypt(json.dumps(value).encode()))


def setup():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    if not _fernet():
        print("⚠️ GitHub Secrets に KOTORI_STORE_KEY がないため、通知の準備ができません")
        return 1
    if (STORE / "public.json").exists() and (STORE / "vapid.enc").exists():
        print("通知の鍵はもうあります")
        return 0
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    _write("vapid.enc", {"pem": pem})
    (STORE / "public.json").write_text(json.dumps({"key": base64.urlsafe_b64encode(raw).decode().rstrip("=")}) + "\n")
    print("✅ 通知の鍵を作りました")
    return 0


def subscribe(text):
    sub = json.loads(text)
    if not (sub.get("endpoint", "").startswith("https://") and sub.get("keys", {}).get("p256dh")):
        print("⚠️ 端末の情報が正しくありません")
        return 1
    if not _fernet():
        print("⚠️ GitHub Secrets に KOTORI_STORE_KEY がありません")
        return 1
    subs = [s for s in _read("subs.enc", []) if s["endpoint"] != sub["endpoint"]]
    _write("subs.enc", subs + [{"endpoint": sub["endpoint"], "keys": sub["keys"]}])
    print(f"✅ この端末に通知を送れるようにしました（登録 {len(subs) + 1} 台）")
    return 0


def send(title, body, url=SITE, add=1):
    """登録したすべての端末に通知する。準備ができていなければ何もしない（失敗にもしない）。"""
    subs, vapid = _read("subs.enc", []), _read("vapid.enc", None)
    if not subs or not vapid:
        print("通知の準備がまだなので、送りません")
        return 0
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush
    key = Vapid.from_pem(vapid["pem"].encode())
    data = json.dumps({"title": title, "body": body, "url": url, "add": add}, ensure_ascii=False)
    alive = []
    for s in subs:
        try:
            webpush(s, data=data, vapid_private_key=key, vapid_claims={"sub": "mailto:keiyamada-ui@users.noreply.github.com"}, ttl=12 * 3600)
            alive.append(s)
        except WebPushException as e:
            code = getattr(e.response, "status_code", 0)
            if code not in (404, 410):  # 404・410 は通知をやめた端末なので消す
                alive.append(s)
            print(f"⚠️ 1台に送れませんでした（{code}）")
        except Exception as e:  # noqa: BLE001 - 通信の一時的な失敗。登録は残す
            alive.append(s)
            print(f"⚠️ 1台に送れませんでした: {str(e)[:80]}")
    if len(alive) != len(subs):
        _write("subs.enc", alive)
    print(f"🔔 通知しました: {title}（{len(alive)}台）")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["setup", "subscribe", "send"])
    p.add_argument("subscription", nargs="?", default="")
    p.add_argument("--title", default="ことり")
    p.add_argument("--body", default="")
    p.add_argument("--url", default=SITE)
    p.add_argument("--add", type=int, default=1)
    a = p.parse_args(argv)
    if a.cmd == "setup":
        return setup()
    if a.cmd == "subscribe":
        return subscribe(a.subscription or os.environ.get("SUBSCRIPTION", ""))
    try:
        return send(a.title, a.body, a.url, a.add)
    except Exception as e:  # noqa: BLE001 - 通知は補助なので、失敗しても止めない
        print(f"⚠️ 通知を送れませんでした: {str(e)[:150]}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
