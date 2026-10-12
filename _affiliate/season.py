"""今の季節感（実際の気温と、この時期の行事）を調べて、文章作りと確認に使う。

毎朝1回、東京の天気予報（Open-Meteo・無料・鍵いらず）から、ここ数日と1週間先の最高・最低気温を取り、
「今はどんな服装・どんな季節か」と「まだ早い（もう遅い）言葉」を決める。取れなければ平年の気温で決める。
結果は data/season/YYYY-MM-DD.json に保存し、同じ日は使い回す。
"""

import datetime
import json
import re
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "season"
URL = ("https://api.open-meteo.com/v1/forecast?latitude=35.69&longitude=139.69"
       "&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FTokyo&past_days=3&forecast_days=8")
# 東京の平年の最高気温（月ごと）。予報が取れないときに使う
NORMAL_MAX = {1: 10, 2: 11, 3: 14, 4: 19, 5: 23, 6: 26, 7: 30, 8: 31, 9: 27, 10: 22, 11: 17, 12: 12}
EVENTS = {
    1: "お正月・冬休み明け・寒さ本番・インフルエンザ", 2: "節分・バレンタイン・寒さのピーク・花粉の始まり",
    3: "ひな祭り・卒業・春休み・新学期の準備", 4: "入学・進級・新生活・お弁当・遠足",
    5: "GW・こどもの日・母の日・運動会（春）・暑い日も出てくる", 6: "梅雨・父の日・プール開き・雨の日の過ごし方",
    7: "夏休み・七夕・熱中症・自由研究", 8: "夏休み・お盆・帰省・旅行・宿題の追い込み",
    9: "新学期・残暑・防災の日・敬老の日・シルバーウィーク", 10: "運動会・ハロウィン・衣替え・秋の遠足・朝晩の気温差",
    11: "七五三・紅葉・秋の行楽・朝晩の冷え込み・年末準備のはじまり", 12: "クリスマス・冬休み・大掃除・年末年始・本格的な寒さ",
}
# 暖かいうちは使わない冬の言葉・涼しくなったら使わない夏の言葉（先取りしすぎ・季節外れ）
WINTER_WORDS = ["ダウンジャケット", "ダウンコート", "ダウン", "こたつ", "手袋", "マフラー", "ネックウォーマー", "カイロ",
                "雪遊び", "雪", "真冬", "極寒", "スキー", "スノーボード", "霜焼け", "しもやけ", "暖房", "電気毛布"]
SUMMER_WORDS = ["猛暑", "熱中症", "かき氷", "プール", "扇風機", "冷房", "真夏", "汗だく", "日焼け", "水遊び"]
NOT_SEASON = {"ダウン": r"ダウン(?!ロード)"}  # 「ダウンロード」などは季節の言葉ではない


def _phase(avg_max):
    if avg_max >= 29:
        return "真夏（半袖・熱中症対策の時期）"
    if avg_max >= 25:
        return "まだ暑い（半袖が中心）"
    if avg_max >= 20:
        return "過ごしやすい（長袖1枚や薄い羽織りで十分。冬物はまだ早い）"
    if avg_max >= 15:
        return "少し肌寒い（カーディガン・薄手の上着。朝晩は冷える）"
    if avg_max >= 9:
        return "寒い（コート・暖房の時期）"
    return "真冬（厚手のコート・防寒が必須）"


def avoid_words(avg_max):
    """最高気温が18℃以上なら冬の言葉、22℃未満なら夏の言葉を避ける（18〜21℃はどちらも避ける）。"""
    out = []
    if avg_max >= 18:
        out += WINTER_WORDS
    if avg_max < 22:
        out += SUMMER_WORDS
    return out


def fetch(today, timeout=15):
    """東京の予報から、ここ数日と1週間先の気温。取れなければ None。"""
    try:
        r = requests.get(URL, timeout=timeout)
        r.raise_for_status()
        d = r.json()["daily"]
        days = list(zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"]))
        return [{"date": t, "max": round(mx), "min": round(mn)} for t, mx, mn in days if mx is not None and mn is not None]
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 天気予報を取れませんでした（平年の気温で考えます）: {str(e)[:100]}")
        return None


def build(today, days=None):
    if days:
        ahead = [x for x in days if x["date"] >= today.isoformat()][:7] or days
        avg_max = round(sum(x["max"] for x in ahead) / len(ahead))
        avg_min = round(sum(x["min"] for x in ahead) / len(ahead))
        source = "東京の天気予報"
    else:
        avg_max, avg_min, source = NORMAL_MAX[today.month], NORMAL_MAX[today.month] - 8, "東京の平年の気温"
    avoid = avoid_words(avg_max)
    note = (f"今の季節感（{source}・{today.month}月{today.day}日）: これから1週間の最高気温は平均{avg_max}℃、最低気温は平均{avg_min}℃。"
            f"{_phase(avg_max)}。この時期の行事・話題: {EVENTS[today.month]}。\n"
            "これは「季節外れの言葉を使わない」ための情報で、季節の話題を書けという意味ではない。"
            "季節や天気の話は毎回入れず、たまに（数回に1回くらい）でよい。ほとんどの投稿は季節と関係ない日常・悩み・商品の話でよい。"
            "季節に触れるときだけ今の気温に合わせ、先取りするなら「朝晩が冷えてきたら」「そろそろ」のように今の体感から自然につなげる。")
    if avoid:
        note += f"\nまだ（もう）季節に合わない言葉は使わない: {'・'.join(avoid)}。"
    return {"date": today.isoformat(), "avg_max": avg_max, "avg_min": avg_min, "source": source,
            "days": days or [], "avoid": avoid, "note": note}


def get(today, store=STORE, fetcher=fetch):
    path = Path(store) / f"{today.isoformat()}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    info = build(today, fetcher(today))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for old in sorted(Path(store).glob("*.json"))[:-30]:  # 古い記録は30日分だけ残す
        old.unlink()
    print(f"🌤️ {info['note'].splitlines()[0]}")
    return info


def hits(text, avoid):
    """季節に合わない言葉のうち、文章に入っているもの。"""
    found = []
    for w in avoid:
        pattern = NOT_SEASON.get(w, re.escape(w))
        if re.search(pattern, text) and not any(w in f for f in found):
            found.append(w)
    return found
