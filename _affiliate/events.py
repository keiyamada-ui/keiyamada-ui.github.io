"""行事の先取りカレンダー: 買い物が動く行事を、2〜5週間前から話題・商品に取り入れる。

アフィリエイトの売上は「買う理由がある時期」に集中する（クリスマス・入学準備・ふるさと納税など）。
毎朝、今の時期に動いている行事を調べて、
  ・テーマ: 2日に1回、行事のテーマを優先する（generate_drafts.run_daily）
  ・文章: 「これからの行事」として AI に伝える（話題の1〜2割くらい）
日付は毎年だいたい同じなので、ここに書いておく。変えたいときはこの一覧を直す。
"""

import datetime

import themes as themes_mod

# 名前, 始まり(月,日), 終わり(月,日), 何日前から先取りするか, [(検索先, 楽天で探す言葉, 誰が探すか)]
EVENTS = [
    ("お正月・お年玉", (1, 1), (1, 7), 14, [("ichiba", "福袋 子供服", "年末年始に子ども服をまとめて買いたい親")]),
    ("バレンタイン", (2, 14), (2, 14), 21, [("ichiba", "手作りチョコ キット 子供", "子どもと一緒に手作りしたい親")]),
    ("ひな祭り", (3, 3), (3, 3), 30, [("ichiba", "ひな祭り 飾り コンパクト", "マンションでも飾りたい親")]),
    ("卒園・卒業式", (3, 10), (3, 25), 40, [("ichiba", "卒業式 服 小学生", "卒業式の服を探している親"),
                                        ("ichiba", "卒園式 ママ スーツ", "卒園式に着る服を探している親")]),
    ("中学入学・進級準備", (1, 15), (4, 5), 0, [("ichiba", "通学リュック 中学生 大容量", "中学入学に向けて通学カバンを探す親"),
                                          ("ichiba", "制服 収納 ハンガーラック", "制服や部活の道具の置き場所を整えたい親"),
                                          ("ichiba", "デスクライト 勉強 目に優しい", "進級に合わせて勉強の環境を整えたい親")]),
    ("受験シーズン", (11, 1), (2, 28), 0, [("ichiba", "加湿器 静音 寝室", "受験生の体調管理が心配な親"),
                                       ("ichiba", "ネックウォーマー 中学生", "冬の塾通いや部活の寒さ対策をしたい親")]),
    ("年末の大掃除", (12, 28), (12, 31), 30, [("ichiba", "掃除グッズ 便利", "年末の大掃除をラクにしたい親"),
                                          ("ichiba", "収納ボックス 子供部屋", "子ども部屋を片付けて新年を迎えたい親")]),
    ("新学期・進級", (4, 1), (4, 15), 20, [("ichiba", "体操服袋 キッズ", "新学期の持ち物をそろえる親")]),
    ("こどもの日", (5, 5), (5, 5), 30, [("ichiba", "こいのぼり ベランダ", "こどもの日の飾りを探す親")]),
    ("母の日", (5, 10), (5, 10), 21, [("ichiba", "母の日 プレゼント 実用的", "自分の母に贈り物を探す親")]),
    ("運動会（春）", (5, 15), (6, 10), 21, [("ichiba", "レジャーシート 運動会 大きめ", "運動会の場所取りを考える親"),
                                         ("ichiba", "水筒 子供 2way", "運動会や遠足の水筒を探す親")]),
    ("梅雨", (6, 1), (7, 15), 14, [("ichiba", "レインコート 子供 ランドセル", "雨の日の通学を心配する親"),
                                 ("ichiba", "長靴 キッズ 軽い", "雨の日の通学を心配する親")]),
    ("父の日", (6, 20), (6, 20), 21, [("ichiba", "父の日 プレゼント 子供から", "子どもからの贈り物を考える親")]),
    ("夏休み", (7, 20), (8, 31), 21, [("ichiba", "自由研究 キット 小学生", "夏休みの自由研究に悩む親"),
                                    ("books", "夏休み ドリル 小学生", "夏休みの勉強を考える親")]),
    ("敬老の日", (9, 15), (9, 15), 21, [("ichiba", "敬老の日 孫から プレゼント", "祖父母への贈り物を考える親")]),
    ("運動会（秋）", (9, 20), (10, 20), 21, [("ichiba", "レジャーシート 運動会 大きめ", "運動会の場所取りを考える親")]),
    ("ハロウィン", (10, 31), (10, 31), 21, [("ichiba", "ハロウィン 仮装 子供 簡単", "子どもの仮装を手軽に用意したい親")]),
    ("クリスマス", (12, 25), (12, 25), 35, [("ichiba", "クリスマスプレゼント 小学生 知育", "子どものプレゼントに悩む親"),
                                          ("books", "クリスマス 絵本", "クリスマスに絵本を贈りたい親")]),
    ("ふるさと納税（年末の締め切り）", (11, 1), (12, 31), 0, [("ichiba", "ふるさと納税 お米 訳あり", "年末までにふるさと納税を済ませたい親"),
                                                    ("ichiba", "ふるさと納税 子供 喜ぶ", "家族で楽しめる返礼品を探す親")]),
]


def _span(today, start, end, lead):
    """今日にいちばん近い (先取りの始まり, 行事の終わり)。年をまたぐ行事にも対応する。"""
    for year in (today.year - 1, today.year, today.year + 1):
        s = datetime.date(year, *start)
        e = datetime.date(year if end >= start else year + 1, *end)
        span = (s - datetime.timedelta(days=lead), e)
        if span[0] <= today <= span[1]:
            return span, s
    return (None, None), None


def active(today):
    """今の時期に動いている行事: [{"name", "until", "days_left", "keywords"}]。近い順。"""
    out = []
    for name, start, end, lead, keywords in EVENTS:
        (begin, until), day = _span(today, start, end, lead)
        if begin is None:
            continue
        out.append({"name": name, "day": day, "until": until, "days_left": (day - today).days, "keywords": keywords})
    return sorted(out, key=lambda e: (max(e["days_left"], 0), e["until"]))


def upcoming(today, days=14):
    """これから days 日のうちに始まる・動き出す行事の名前（週のふり返り用）。"""
    later = {e["name"] for e in active(today + datetime.timedelta(days=days))}
    return [e["name"] for e in active(today)] + sorted(later - {e["name"] for e in active(today)})


def themes(today):
    """今の時期の行事のテーマ（テーマ選びに混ぜる）。"""
    out = []
    for e in active(today):
        for source, keyword, persona in e["keywords"]:
            t = themes_mod._make("行事", source, keyword, persona, category=e["name"], urgency=5)
            t["months"] = [today.month]
            out.append(t)
    return out


def note(today):
    """文章作りに添える一文。行事がなければ空。"""
    events = active(today)[:3]
    if not events:
        return ""
    parts = []
    for e in events:
        if e["days_left"] > 0:
            parts.append(f"{e['name']}（あと{e['days_left']}日）")
        else:
            parts.append(f"{e['name']}（{e['until'].month}/{e['until'].day}ごろまで）")
    return ("これから買い物が動く行事: " + "、".join(parts) + "。"
            "話題や商品選びのときは、この準備に役立つものを少し意識する（毎回ではなく、ときどき）。")
