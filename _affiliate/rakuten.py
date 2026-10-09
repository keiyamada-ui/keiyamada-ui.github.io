"""楽天ウェブサービス（市場・ブックス・トラベル）から商品や宿の候補を取ってくる。

2026年の仕様変更に対応:
- 新ドメイン openapi.rakuten.co.jp
- applicationId と accessKey の両方が必須（accessKey はヘッダーとクエリの両方で送る）
- 「Webアプリケーション」タイプのため、登録したサイトを Referer / Origin で名乗る
"""

import time

import requests


class RakutenError(RuntimeError):
    pass


class RakutenClient:
    def __init__(self, app_id, access_key, affiliate_id, endpoints, referer,
                 min_interval_seconds=1.2, session=None):
        if not app_id or not access_key:
            raise RakutenError(
                "楽天の applicationId / accessKey が未設定です"
                "（GitHub Secrets の RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY を確認してください）"
            )
        self.app_id = app_id
        self.access_key = access_key
        self.affiliate_id = affiliate_id
        self.endpoints = endpoints
        self.referer = referer
        self.min_interval = min_interval_seconds
        self.session = session or requests.Session()
        self._last_call = 0.0

    def _get(self, source, params):
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

        query = {
            "applicationId": self.app_id,
            "accessKey": self.access_key,
            "format": "json",
            "formatVersion": 2,
            **params,
        }
        if self.affiliate_id:
            query["affiliateId"] = self.affiliate_id
        headers = {
            "accessKey": self.access_key,
            "Referer": self.referer,
            "Origin": self.referer.rstrip("/"),
        }
        res = self.session.get(self.endpoints[source], params=query,
                               headers=headers, timeout=30)
        if res.status_code == 404 and "not_found" in res.text:
            # 検索結果が0件のとき楽天は404を返す
            return {}
        if res.status_code != 200:
            raise RakutenError(
                f"楽天API（{source}）がエラーを返しました: "
                f"HTTP {res.status_code} {res.text[:300]}"
            )
        return res.json()

    def search(self, source, keyword, hits=30):
        if source == "ichiba":
            data = self._get(source, {
                "keyword": keyword, "hits": hits,
                "sort": "-reviewCount", "availability": 1,
                "imageFlag": 1,
            })
            return [normalize_ichiba(i) for i in _items(data, "Items", "Item")]
        if source == "books":
            data = self._get(source, {
                "keyword": keyword, "hits": hits,
                "sort": "reviewCount", "availability": 1,
            })
            return [normalize_books(i) for i in _items(data, "Items", "Item")]
        if source == "travel":
            data = self._get(source, {
                "keyword": keyword, "hits": hits,
                "sort": "standard", "responseType": "middle",
            })
            return [normalize_travel(h) for h in _hotels(data)]
        raise RakutenError(f"未対応の source です: {source}")


def _items(data, list_key, wrap_key):
    """formatVersion 1（{"Item": {...}} で包まれる）と 2 の両方に対応する。"""
    out = []
    for entry in (data or {}).get(list_key, []):
        if isinstance(entry, dict) and wrap_key in entry:
            entry = entry[wrap_key]
        out.append(entry)
    return out


def _hotels(data):
    """トラベルの hotels は [[{hotelBasicInfo}, {hotelRatingInfo}], ...] の入れ子。
    formatVersion 1 では {"hotel": [...]} で包まれるので両方に対応する。"""
    out = []
    for entry in (data or {}).get("hotels", []):
        if isinstance(entry, dict) and "hotel" in entry:
            entry = entry["hotel"]
        merged = {}
        for part in entry if isinstance(entry, list) else [entry]:
            if isinstance(part, dict):
                for value in part.values():
                    if isinstance(value, dict):
                        merged.update(value)
                    elif isinstance(value, list) and value and isinstance(value[0], dict):
                        merged.update(value[0])
        out.append(merged)
    return out


def _first_image(value):
    if isinstance(value, list) and value:
        first = value[0]
        return first.get("imageUrl", "") if isinstance(first, dict) else first
    return value or ""


def _clip(text, limit=400):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _num(value, cast=float):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return cast(0)


def normalize_ichiba(item):
    return {
        "source": "ichiba",
        "id": item.get("itemCode", ""),
        "name": item.get("itemName", ""),
        "price": _num(item.get("itemPrice"), int),
        "url": item.get("affiliateUrl") or item.get("itemUrl", ""),
        "is_affiliate_url": bool(item.get("affiliateUrl")),
        "review_count": _num(item.get("reviewCount"), int),
        "review_average": _num(item.get("reviewAverage")),
        "shop": item.get("shopName", ""),
        "caption": _clip(item.get("itemCaption")),
        "image": _first_image(item.get("mediumImageUrls")),
    }


def normalize_books(item):
    return {
        "source": "books",
        "id": item.get("isbn") or item.get("jan") or item.get("itemUrl", ""),
        "name": item.get("title", ""),
        "author": item.get("author") or item.get("artistName", ""),
        "price": _num(item.get("itemPrice"), int),
        "url": item.get("affiliateUrl") or item.get("itemUrl", ""),
        "is_affiliate_url": bool(item.get("affiliateUrl")),
        "review_count": _num(item.get("reviewCount"), int),
        "review_average": _num(item.get("reviewAverage")),
        "shop": "楽天ブックス",
        "caption": _clip(item.get("itemCaption")),
        "image": item.get("largeImageUrl") or item.get("mediumImageUrl", ""),
    }


def normalize_travel(hotel):
    access = hotel.get("access", "")
    return {
        "source": "travel",
        "id": str(hotel.get("hotelNo", "")),
        "name": hotel.get("hotelName", ""),
        "price": _num(hotel.get("hotelMinCharge"), int),
        "price_note": "1人あたりの最安料金の目安",
        # affiliateId を付けて呼ぶと、ここがアフィリエイトURLで返ってくる
        "url": hotel.get("hotelInformationUrl", ""),
        "is_affiliate_url": "hb.afl.rakuten.co.jp" in hotel.get("hotelInformationUrl", ""),
        "review_count": _num(hotel.get("reviewCount"), int),
        "review_average": _num(hotel.get("reviewAverage")),
        "shop": "楽天トラベル",
        "caption": _clip(f"{hotel.get('hotelSpecial', '')} アクセス: {access}"),
        "address": f"{hotel.get('address1', '')}{hotel.get('address2', '')}",
        "image": hotel.get("hotelImageUrl", ""),
    }
