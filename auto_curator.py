import feedparser
import os
import asyncio
import requests
import datetime
import base64
import random
import re
from google import genai
from google.genai import types

# ==========================================
# 🗝️ GitHubの金庫（Secrets）から鍵を自動で呼び出します
# ==========================================
GITHUB_TOKEN = os.environ.get("MY_GITHUB_TOKEN")
GITHUB_REPO = "keiyamada-ui/keiyamada-ui.github.io"

# ==========================================
# 📰 情報源（RSS）リスト：URLをコピペでいつでも追加・削除できます！
# ==========================================
RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://venturebeat.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.technologyreview.com/feed/",
    "https://www.zdnet.com/news/rss.xml",
    "https://www.engadget.com/rss.xml",
    "https://artificialintelligence-news.com/feed/"
]
# ==========================================

def get_diverse_news(limit=2):
    print("🌍 世界中のメディアから最新ニュースを探索しています...")
    # リストからランダムに情報源をピックアップ（毎回違うジャンルになりやすい）
    selected_feeds = random.sample(RSS_FEEDS, min(limit, len(RSS_FEEDS)))
    
    news_list = []
    for feed_url in selected_feeds:
        try:
            parsed = feedparser.parse(feed_url)
            if parsed.entries:
                entry = parsed.entries[0] # そのメディアの最新記事を1つ取得
                news_list.append({
                    "title": entry.title,
                    "link": entry.link,
                    "source": parsed.feed.title if hasattr(parsed.feed, 'title') else "Tech Media"
                })
        except Exception as e:
            print(f"⚠️ 取得エラー ({feed_url}): {e}")
            
    return news_list

def upload_to_github(ai_generated_markdown):
    print(f"\n📝 GitHubへ記事を自動アップロードしています...")
    now = datetime.datetime.now()
    
    # AIが生成したMarkdownからタイトルを抽出（ファイル名にするため）
    title_match = re.search(r'title:\s*"(.*?)"', ai_generated_markdown)
    raw_title = title_match.group(1) if title_match else "tech-news"
    
    safe_title = "".join([c if c.isalnum() else "_" for c in raw_title])[:20]
    file_path = f"_posts/{now.strftime('%Y-%m-%d')}-{safe_title}-{now.strftime('%H%M%S')}.md"
    
    encoded_content = base64.b64encode(ai_generated_markdown.encode('utf-8')).decode('utf-8')
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "message": f"Auto post: {safe_title}",
        "content": encoded_content,
        "branch": "main" 
    }
    
    response = requests.put(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        print("✅ GitHubへのアップロードが完了しました！")
    else:
        print(f"❌ エラーが発生しました: {response.text}")

async def main():
    client = genai.Client()
    
    # 💡 AdSense対策 ＆ 自動カテゴライズ用の強力なプロンプト
    system_instruction = """
    あなたはプロのITジャーナリスト兼編集長です。
    与えられたURLの英語ニュースを読み込み、日本のビジネスパーソン向けに「独自性のある1000文字程度の解説記事」を作成してください。
    
    【重要】必ず以下のマークダウン形式（Jekyllフロントマターを含む）で出力してください。
    コードブロック（
```markdown と ```）は付けずに、直接テキストを出力してください。
    
    ---
    layout: post
    title: "日本語の魅力的なタイトル（30文字以内）"
    categories: [ここに最適なカテゴリを1つ（例: AI, セキュリティ, ガジェット, ビジネス, 開発）]
    tags: [タグ1, タグ2, タグ3]
    ---

    ## ニュースの要約（3行で簡潔に）
    * 
    * 
    * 
    
    ## 詳細な背景と技術解説
    （ここにニュースの詳細な内容を、専門用語を噛み砕いて分かりやすく記述してください）
    
    ## 日本市場・ビジネスへの影響（考察）
    （ここが最も重要です。このニュースが日本の読者やビジネスにどう影響するか、あなたのプロとしての独自考察を深く記述してください）
    
    [元記事はこちら]({URL})
    """
    
    news_items = get_diverse_news(limit=2)
    if not news_items:
        return

    print(f"✅ {len(news_items)}件のニュースを取得しました。記事化を開始します...\n" + "="*40)

    for i, news in enumerate(news_items, 1):
        print(f"🔄 [{i}/{len(news_items)}] 処理中: {news['title']} ({news['source']})")
        prompt = f"以下のURLのニュースを記事化してください。\nURL: {news['link']}"
        
        try:
            response = await client.aio.models.generate_content_stream(
                model='gemini-3.1-pro-preview',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction.replace("{URL}", news['link']),
                    temperature=0.7,
                    tools=[{"google_search": {}}]
                )
            )
            
            full_ai_text = ""
            async for chunk in response:
                full_ai_text += chunk.text
            
            # Markdownのコードブロックタグが誤って出力された場合を除去
            clean_text = full_ai_text.replace("```markdown\n", "").replace("```", "").strip()
            
            upload_to_github(clean_text)
            
        except Exception as e:
            print(f"\n❌ エラーが発生しました: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())
