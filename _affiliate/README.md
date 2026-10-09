# ことり｜Threads 投稿下書きの自動作成

毎朝 6:15（日本時間）に、次の流れを自動で行います。

1. 今日のテーマを決める（習い事 → 本・図鑑 → 家族旅行 → セール前、の順に毎日交代）
2. 楽天市場・楽天ブックス・楽天トラベルから、レビュー数と評価で候補を絞り込む（最近紹介したものは除外）
3. AI が「リンクなし投稿 2 本＋PR 投稿 1 本」の下書きを書く
4. PR 表記・リンク 1 本・NG ワード・文字数を自動チェック（引っかかったら AI に書き直させる）
5. 確認用の PR（Pull Request）を作る → スマホに通知が届く

あなたは PR を読んで Threads にコピーして投稿し、**Merge**（使った）か **Close**（使わない）を押すだけです。
途中で失敗したときは、「⚠️ 投稿下書きの作成に失敗しました」という Issue が作られて通知が届きます。

## 最初に 1 回だけやる設定

### 1. GitHub Secrets（鍵の金庫）に登録する

Settings → Secrets and variables → Actions → New repository secret

| Name | 中身 | 必須 |
|---|---|---|
| `RAKUTEN_APP_ID` | 楽天ウェブサービスの applicationId | ✅ |
| `RAKUTEN_ACCESS_KEY` | 楽天ウェブサービスの accessKey | ✅ |
| `RAKUTEN_AFFILIATE_ID` | 楽天のアフィリエイト ID | ✅ |
| `GEMINI_API_KEY` | Google AI Studio の API キー | Gemini を使うとき |
| `ANTHROPIC_API_KEY` | Claude Console の API キー | Claude を使うとき |

`ANTHROPIC_API_KEY` を登録すると、自動的に Claude（Opus 5.5）に切り替わります。消すと Gemini に戻ります。

### 2. GitHub Actions が PR を作れるようにする

Settings → Actions → General → 一番下の「Workflow permissions」で

- 「Read and write permissions」を選ぶ
- 「**Allow GitHub Actions to create and approve pull requests**」にチェック
- Save

### 3. 接続テスト

Actions → 「ことり 投稿下書き」→「Run workflow」→ mode で **check-api** を選んで実行。
3 つとも ✅ になれば楽天 API の準備は完了です。続けて mode **drafts** で実行すると、下書きの PR が 1 本届きます。

## よく変える設定

すべて [config.yaml](config.yaml) にまとまっています。

- **テーマや検索キーワードを増やす・変える** → `pillars` の `queries`
- **候補の条件を変える**（レビュー件数・評価・同じ商品を再紹介するまでの日数）→ `filters`
- **楽天 API の URL が変わった** → `rakuten.endpoints`

## 手元で動作確認（開発者向け）

```bash
pip install -r _affiliate/requirements.txt
python -m pytest -q _affiliate/tests                    # 自動テスト
python _affiliate/generate_drafts.py --dry-run          # サンプルデータで下書きを作る（API 不要）
python _affiliate/generate_drafts.py --check-api        # 楽天 API の接続確認（鍵が必要）
```

## ファイル構成

| ファイル | 役割 |
|---|---|
| `generate_drafts.py` | 本体（全体の流れ・下書きの書き出し） |
| `rakuten.py` | 楽天 API から商品・本・宿を取得 |
| `selector.py` | テーマ選び・候補の絞り込み・紹介履歴 |
| `llm.py` | AI（Gemini / Claude）への指示と呼び出し |
| `checks.py` | 投稿ルールの自動チェック |
| `drafts/` | 毎日の下書き（Merge した PR の分が残る） |
| `data/history/` | 紹介した商品の履歴（1 日 1 ファイル） |
| `../.github/workflows/affiliate_drafts.yml` | 毎朝の自動実行の設定 |
