# ことり｜Threads・楽天ROOM 投稿下書きの自動作成

## 毎朝 5:15（日本時間）に自動で行うこと

1. **テーマを選ぶ** — AI が月に1回「季節・行事・生活の悩み」から考えたテーマ（誰の悩みか・場面・カテゴリー・緊急度）、
   参考投稿から生まれたテーマ、固定テーマを混ぜて、緊急度・季節・最近使ったかで1つ選ぶ
2. **商品を選ぶ** — 楽天市場・ブックス・トラベルから候補を取り、需要（レビュー件数・ランキング）・評価・
   報酬の目安（価格×料率）・勢い（レビュー数の伸び）で点数を付ける。水曜と土曜は 💎 **発掘枠**（高評価なのにまだレビューが少ない商品）
3. **分析する** — AI が候補を5つの基準（季節需要・買い替え・比較しやすさ・写真映え・悩み直結）で採点して1つ選び、
   買う人を分析（買う直前の悩み・決め手・比較ポイント・迷う理由・期待する変化）し、切り口を20個出す
4. **書く** — 60点の下書き → 弱点の洗い出し → 100点版。リンクなし2本（ツリー可）＋PR1本＋楽天ROOM用コメント。
   勝ちパターン（参考投稿の型）も参考にする
5. **自動チェック** — PR表記・リンク1本・NGワード・文字数（引っかかったら AI に書き直させる）
6. **確認用の PR** を作る → スマホに通知。失敗したら Issue で通知

AI は `ANTHROPIC_API_KEY` があれば Claude を使い、残高切れなどで使えなければ自動で Gemini に切り替えて、Issue で知らせます。

あなたは PR を読んで Threads・楽天ROOM にコピーして投稿し、**Merge**（使った）か **Close**（使わない）を押すだけです。

## 自動投稿（Threads）

`config.yaml` の `auto_post.enabled: true` のとき、下書きは PR を通さずにそのまま保存され、1日3回 Threads に投稿されます。

| 時間帯（日本時間） | 投稿するもの |
|---|---|
| 7:40ごろ | リンクなし投稿1 |
| 12:20ごろ | リンクなし投稿2（ツリーなら続けてつなげる。朝が出ていなければ朝の分） |
| 20:10ごろ | PR 投稿（本文 → 自分への返信にリンク）。推し商品フォームの下書きを優先 |

- 毎回 0〜15 分ずらして投稿します
- 自動チェックでエラーが残った下書きは投稿しません
- `pr_posts_from` の日付までは PR 投稿をしません（アカウントを育てる期間）。`pr_min_interval_days` で PR 投稿の間隔を決めます
- 結果は「📣 ことり 今日の投稿」という Issue にまとまります。良くない投稿は Threads アプリで削除してください
- すぐ止めたいとき: Actions →「ことり 自動投稿」→「…」→「Disable workflow」
- `auto_post.enabled: false` にすると、以前の「確認用の PR が届く」形に戻ります
- Threads のトークンは60日で切れます。登録した日を `auto_post.token_updated` に書いておくと、50日たったときに Issue で知らせます（毎週月曜に確認）

## 手動投稿ストック（BAN 対策）

毎朝、自動投稿とは**別のテーマ・別の商品**で、手動投稿用の下書きを1セット（リンクなし2本＋PR1本＋楽天ROOM用コメント）作って `manual/` にためます。

管理画面の「✋ 手動投稿ストック」（`kotori/stock.html`）に一覧で並び、ボタンでコピー、または「Threads で開く」で投稿画面を開けます。
投稿したら「使った」を押すと、その端末では一覧から外れます。自動投稿を止めて、手動だけで運用することもできます。
`config.yaml` の `manual_stock.enabled: false` で作らないようにできます。

## スマホから使う

管理画面 https://keiyamada-ui.github.io/kotori/ をホーム画面に追加すると、アプリのように使えます。

- 🛒 **推し商品を紹介** — 楽天のURLを貼るだけで、その商品の下書き PR が届く（使った感想を書けば体験談として使われる）
- ⭐ **参考投稿を登録** — 伸びている投稿を貼ると、AI が「型」を分析して勝ちパターンに追加（外したいときは Issue を Close）

## 最初に 1 回だけやる設定

### 1. GitHub Secrets（鍵の金庫）に登録する

Settings → Secrets and variables → Actions → New repository secret

| Name | 中身 | 必須 |
|---|---|---|
| `RAKUTEN_APP_ID` | 楽天ウェブサービスの applicationId | ✅ |
| `RAKUTEN_ACCESS_KEY` | 楽天ウェブサービスの accessKey | ✅ |
| `RAKUTEN_AFFILIATE_ID` | 楽天のアフィリエイト ID | ✅ |
| `GEMINI_API_KEY` | Google AI Studio の API キー | ✅（Claude が使えないときの予備にもなる） |
| `ANTHROPIC_API_KEY` | Claude Console の API キー | Claude を使うとき |
| `KOTORI_THREADS_TOKEN` | kotori.family の Threads アクセストークン（長期） | 自動投稿するとき |

### 2. GitHub Actions が PR を作れるようにする

Settings → Actions → General → 一番下の「Workflow permissions」で

- 「Read and write permissions」を選ぶ
- 「**Allow GitHub Actions to create and approve pull requests**」にチェック
- Save

### 3. 接続テスト

Actions → 「ことり 投稿下書き」→「Run workflow」→ mode で **check-api** を選んで実行。
市場・ブックス・トラベルの3つが ✅ になれば準備完了です（ランキングだけ ⚠️ でも下書きは作れます）。
続けて mode **drafts** で実行すると、下書きの PR が 1 本届きます。月の最初の実行では、今月のテーマも一緒に作られます。

## よく変える設定

すべて [config.yaml](config.yaml) にまとまっています。

- **固定テーマ・検索キーワードを増やす・変える** → `pillars`
- **候補の条件**（レビュー件数・評価・同じ商品を再紹介するまでの日数）→ `filters`
- **発掘枠の曜日・条件** → `hidden_gems`
- **点数の重み・料率の目安** → `scoring`
- **楽天 API の URL が変わった** → `rakuten.endpoints`

AI が考えたテーマは `data/themes/年-月.json` にあります。合わないテーマは行ごと消してください。
Actions の mode **themes** で、今月のテーマを作り直せます。

## 手元で動作確認（開発者向け）

```bash
pip install -r _affiliate/requirements.txt
python -m pytest -q _affiliate/tests                    # 自動テスト
python _affiliate/generate_drafts.py --dry-run          # サンプルデータで下書きを作る（API 不要・記録は書き換えない）
python _affiliate/generate_drafts.py --check-api        # 楽天 API の接続確認（鍵が必要）
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `generate_drafts.py` | 本体（毎朝の下書き・推し商品・参考投稿の分析・テーマ作り） |
| `prompts.py` | AI への指示文（テーマ・分析・執筆・参考投稿） |
| `llm.py` | AI の呼び出し（Claude → Gemini の自動切り替え） |
| `themes.py` | 悩み起点のテーマ選び |
| `selector.py` | 候補の絞り込み・点数付け・発掘枠・履歴 |
| `rakuten.py` | 楽天 API（検索・ランキング・URL からの商品取得） |
| `checks.py` | 投稿ルールの自動チェック |
| `patterns.py` / `issue_forms.py` | 勝ちパターンの読み込み・フォームの読み取り |
| `autopost.py` / `threads.py` | Threads への自動投稿 |
| `drafts/` | 下書き（Merge した PR の分が残る） |
| `data/history/` `data/themes/` `data/snapshots/` `data/posted/` | 紹介履歴・月ごとのテーマ・勢いを測る記録・投稿の記録 |
| `manual/` | 手動投稿ストック（`index.json` が一覧ページの元データ） |
| `../kotori/` | スマホ用の管理画面・手動投稿ストックの一覧ページ |
| `../.github/workflows/affiliate_*.yml` | 毎朝の自動実行・フォームの処理 |
| `../.github/ISSUE_TEMPLATE/` | 推し商品・参考投稿のフォーム |
