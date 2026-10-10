"""集客投稿のネタ集め: ニュース・トレンド・人気記事の見出しを RSS で集める（API キー不要）。

記事の本文は取らず、見出しだけを AI に渡して「今なにが話題か」の手がかりにする。
どれかの取得に失敗しても、取れた分だけで続ける。
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; kotori-research/1.0)"}
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"

DEFAULT_FEEDS = [
    ("Googleトレンド（急上昇ワード）", "https://trends.google.co.jp/trending/rss?geo=JP"),
    ("Yahoo!ニュース 国内", "https://news.yahoo.co.jp/rss/topics/domestic.xml"),
    ("Yahoo!ニュース 経済", "https://news.yahoo.co.jp/rss/topics/business.xml"),
    ("はてなブックマーク 暮らしの人気記事", "https://b.hatena.ne.jp/hotentry/life.rss"),
]
DEFAULT_QUERIES = ["子育て", "小学生 親", "習い事", "小学校 保護者", "子連れ おでかけ"]

# 宣伝に結びつけると反感を買う話題は、見出しの段階で外す
SENSITIVE = re.compile(r"死亡|死去|亡くな|殺|事故|事件|逮捕|容疑|虐待|いじめ自殺|自殺|被害|遺体|重体|地震|津波|"
                       r"台風.*被害|火災|不同意|性的|わいせつ|行方不明|訃報|戦争|ミサイル")


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed(xml_text, limit=20):
    """RSS 2.0 / RSS 1.0（RDF）/ Atom のどれでも、見出しの一覧を返す。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    titles = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = next((c.text for c in el if _local(c.tag) == "title" and c.text), "")
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def fetch(url, session=None):
    res = (session or requests).get(url, headers=UA, timeout=20)
    res.raise_for_status()
    return res.text


def collect(feeds=None, queries=None, session=None, per_feed=15):
    """[(出どころ, 見出し)] と、取得できなかった出どころの一覧を返す。"""
    feeds = list(feeds or DEFAULT_FEEDS)
    feeds += [(f"Googleニュース「{q}」", GOOGLE_NEWS.format(q=urllib.parse.quote(q)))
              for q in (queries or DEFAULT_QUERIES)]
    headlines, failed, seen = [], [], set()
    for name, url in feeds:
        try:
            titles = parse_feed(fetch(url, session), per_feed)
        except Exception as e:  # noqa: BLE001 - 一部が取れなくても続ける
            failed.append(f"{name}（{str(e)[:60]}）")
            continue
        for t in titles:
            if t in seen or SENSITIVE.search(t):
                continue
            seen.add(t)
            headlines.append((name, t))
    return headlines, failed
