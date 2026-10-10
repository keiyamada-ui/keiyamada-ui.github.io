"""Threads の公式 API で投稿する（コンテナを作って → 公開する、の2段階）。"""

import time

import requests

BASE = "https://graph.threads.net/v1.0"


class ThreadsError(RuntimeError):
    pass


class ThreadsClient:
    def __init__(self, token, session=None, wait_seconds=5):
        if not token:
            raise ThreadsError("Threads のアクセストークンが未設定です（GitHub Secrets の KOTORI_THREADS_TOKEN）")
        self.token = token
        self.session = session or requests.Session()
        self.wait = wait_seconds
        self._user_id = None

    def _call(self, method, url, **params):
        params["access_token"] = self.token
        res = self.session.request(method, url, params=params, timeout=60)
        if res.status_code != 200:
            raise ThreadsError(f"Threads API がエラーを返しました: HTTP {res.status_code} {res.text[:300]}")
        return res.json()

    def me(self):
        return self._call("GET", f"{BASE}/me", fields="id,username")

    @property
    def user_id(self):
        if not self._user_id:
            self._user_id = self.me()["id"]
        return self._user_id

    def post_text(self, text, reply_to=None, topic_tag=None):
        """テキストを投稿して、投稿のIDを返す。reply_to を付けると、その投稿への返信（ツリー）になる。"""
        params = {"media_type": "TEXT", "text": text}
        if reply_to:
            params["reply_to_id"] = reply_to
        if topic_tag:
            params["topic_tag"] = topic_tag
        try:
            container = self._call("POST", f"{BASE}/{self.user_id}/threads", **params)["id"]
        except ThreadsError:
            if not topic_tag:
                raise
            # トピックタグが受け付けられなかったときは、タグなしで出す
            params.pop("topic_tag")
            container = self._call("POST", f"{BASE}/{self.user_id}/threads", **params)["id"]
        # 作ったコンテナが公開できる状態になるまで少し待つ（Meta の推奨）
        last_error = None
        for attempt in range(4):
            time.sleep(self.wait * (attempt + 1))
            try:
                return self._call("POST", f"{BASE}/{self.user_id}/threads_publish", creation_id=container)["id"]
            except ThreadsError as e:
                last_error = e
        raise last_error

    def permalink(self, media_id):
        try:
            return self._call("GET", f"{BASE}/{media_id}", fields="permalink").get("permalink", "")
        except ThreadsError:
            return ""

    def insights(self, media_id):
        """投稿の反響（表示・いいね・返信・再投稿・引用）。threads_manage_insights の権限が必要。"""
        data = self._call("GET", f"{BASE}/{media_id}/insights", metric="views,likes,replies,reposts,quotes")
        out = {}
        for item in data.get("data", []):
            values = item.get("values") or []
            value = values[0].get("value") if values else (item.get("total_value") or {}).get("value")
            out[item.get("name")] = int(value or 0)
        return out

    def replies(self, media_id):
        """投稿についた返信（コメント）。threads_read_replies の権限が必要。"""
        data = self._call("GET", f"{BASE}/{media_id}/replies",
                          fields="id,text,username,timestamp,permalink,hide_status")
        return data.get("data", [])

    def recent_ids(self, limit=5):
        return [x["id"] for x in self.recent_posts(limit)]

    def recent_posts(self, limit=20):
        """自分の最近の投稿（手で出したものも含む）。返信（ツリーの続き・リンクの返信）は含まれない。"""
        data = self._call("GET", f"{BASE}/{self.user_id}/threads", fields="id,text,timestamp,permalink", limit=limit)
        return data.get("data", [])

    def conversation(self, media_id):
        """投稿についた返信を、返信への返信も含めてすべて取る。"""
        data = self._call("GET", f"{BASE}/{media_id}/conversation",
                          fields="id,text,username,timestamp,permalink,hide_status", reverse="false")
        return data.get("data", [])
