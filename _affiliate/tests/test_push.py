import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import push  # noqa: E402

SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "x", "auth": "y"}}


def test_without_store_key_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTORI_STORE_KEY", raising=False)
    monkeypatch.setattr(push, "STORE", tmp_path)
    assert push.setup() == 1
    assert push.main(["send", "--title", "t"]) == 0  # 準備がなくても失敗にしない


def test_setup_and_subscribe_are_encrypted(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTORI_STORE_KEY", "secret")
    monkeypatch.setattr(push, "STORE", tmp_path)
    assert push.setup() == 0
    assert "key" in json.loads((tmp_path / "public.json").read_text())
    assert push.subscribe(json.dumps(SUB)) == 0
    assert push.subscribe(json.dumps(SUB)) == 0  # 同じ端末は1台として数える
    raw = (tmp_path / "subs.enc").read_bytes()
    assert b"apple" not in raw and b"PRIVATE" not in (tmp_path / "vapid.enc").read_bytes()
    assert push._read("subs.enc", []) == [SUB]


def test_subscribe_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.setenv("KOTORI_STORE_KEY", "secret")
    monkeypatch.setattr(push, "STORE", tmp_path)
    assert push.subscribe(json.dumps({"endpoint": "http://evil"})) == 1
