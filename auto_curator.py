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
# 🗝️ GitHubの金庫から各種鍵を呼び出します
# ==========================================
GITHUB_TOKEN = os.environ.get("MY_GITHUB_TOKEN")
GITHUB_REPO = "keiyamada-ui/keiyamada-ui.github.io"

# SNS用の鍵（今回はまだ空っぽでOKです）
THREADS_ACCESS_TOKEN = os.environ.get("THREADS_ACCESS_TOKEN")
THREADS_USER_ID = os.environ.get("THREADS_USER_ID")

# 📰 情報源リスト
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
    print("🌍 最新ニュースを探索中...")
    selected_feeds = random.sample(RSS_FEEDS, min(limit, len(RSS_FEEDS)))
    news_list = []
    for feed_url in selected_feeds:
        try:
            parsed = feedparser.parse(feed_url)
            if parsed.entries:
                entry = parsed.entries[0]
                news_list.append({
                    "title": entry.title,
                    "link": entry.link,
                    "source": parsed.feed.title if hasattr(parsed.feed, 'title') else "Tech Media"
                })
        except Exception as e:
            pass
    return news_list

def post_to_threads(sns_text):
    """Threadsへ自動投稿する機能（準備中）"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        print("ℹ️ ThreadsのAPIキーが未設定のため、SNS投稿はスキップします。")
        print(f"📝 投稿予定だった文章:\n{sns_text}\n")
        return

    print("📱 Threadsへ投稿中...")
    try:
        # 1. コンテナの作成
        url_create = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
        payload = {"media_type": "TEXT", "text": sns_text, "access_token": THREADS_ACCESS_TOKEN}
        res_create = requests.post(url_create, data=payload).json()
        
        if "id" in res_create:
            creation_id = res_create["id"]
            # 2. 投稿の公開
            url_publish = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
            publish_payload = {"creation_id": creation_id, "access_token": THREADS_ACCESS_TOKEN}
            res_publish = requests.post(url_publish, data=publish_payload)
            if res_publish.status_code == 200:
                print("✅ Threadsへの自動投稿が成功しました！")
            else:
                print(f"❌ Threads公開エラー: {res_publish.text}")
        else:
            print(f"❌ Threadsコンテナ作成エラー: {res_create}")
    except Exception as e:
        print(f"❌ Threads通信エラー: {e}")

def upload_to_github(ai_generated_markdown):
    now = datetime.datetime.now()
    slug_match = re.search(r'slug:\s*"?([^"\n]+)"?', ai_generated_markdown)
    raw_slug = slug_match.group(1) if slug_match else "tech-news"
    safe_slug = "".join([c if c.isalnum() or c == '-' else "" for c in raw_slug.replace(" ", "-")]).strip('-')[:40]
    if not safe_slug: safe_slug = "tech-news"
        
    file_path = f"_posts/{now.strftime('%Y-%m-%d')}-{safe_slug}-{now.strftime('%H%M%S')}.md"
    encoded_content = base64.b64encode(ai_generated_markdown.encode('utf-8')).decode('utf-8')
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    title_match = re.search(r'title:\s*"(.*?)"', ai_generated_markdown)
    article_title = title_match.group(1) if title_match else safe_slug

    data = {"message": f"Auto post: {article_title}", "content": encoded_content, "branch": "main"}
    response = requests.put(url, headers=headers, json=data)
    
    if response.status_code in [200, 201]:
        print("✅ GitHubへのアップロードが完了しました！")
        
        # --- ここからSNS用の文章を自動作成 ---
        # 記事の「要約（箇条書きの最初の1つ）」を抽出してチラ見せする
        snippet = "テクノロジーの最新動向をお届けします。" # デフォルト値
        snippet_match = re.search(r'\*\s(.*?)\n', ai_generated_markdown)
        if snippet_match:
            snippet = snippet_match.group(1)[:80] + "..." # 長すぎないようにカット
            
        # 記事のURLを組み立てる（Jekyllの標準URLフォーマット）
        article_url = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{now.strftime('%Y/%m/%d')}/{safe_slug}.html"
        
        # ご要望のSNSフォーマットを作成！
        sns_text = f"『{article_title}』\n\n{snippet}\n\n続きはこちら👇\n{article_url}\n\n#AI #ニュース #Tech"
        
        # SNS投稿関数を呼び出し
        post_to_threads(sns_text)
        
    else:
        print(f"❌ エラーが発生しました: {response.text}")

async def main():
    client = genai.Client()
    system_instruction = """
    あなたはプロのITジャーナリスト兼編集長です。
    与えられたURLの英語ニュースを読み込み、日本のビジネスパーソン向けに「独自性のある1000文字程度の解説記事」を作成してください。
    【重要】必ず以下のマークダウン形式（Jekyllフロントマターを含む）で出力してください。
    コードブロック（```markdown と ```）は付けずに、直接テキストを出力してください。
    ※各項目の「:」の後には必ず半角スペースを1つ入れてください！
    
    ---
    layout: post
    title: "日本語の魅力的なタイトル（30文字以内）"
    slug: "english-short-title-for-url"
    categories: [ここに最適なカテゴリを1つ（例: AI, セキュリティ, ビジネス）]
    tags: [タグ1, タグ2, タグ3]
    ---

    ## この記事を3行で
    * * * ## 詳細な背景と技術解説
    （ここにニュースの詳細な内容を記述）
    
    ## 日本市場・ビジネスへの影響
    （独自考察を記述）
    """
    
    news_items = get_diverse_news(limit=2)
    if not news_items: return

    for i, news in enumerate(news_items, 1):
        prompt = f"以下のURLのニュースを記事化してください。\nURL: {news['link']}"
        try:
            response = await client.aio.models.generate_content_stream(
                model='gemini-3.1-pro-preview',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    tools=[{"google_search": {}}]
                )
            )
            full_ai_text = ""
            async for chunk in response: full_ai_text += chunk.text
            
            clean_text = full_ai_text.replace("```markdown\n", "").replace("```", "").strip()
            clean_text = clean_text.replace("tags:[", "tags: [").replace("categories:[", "categories: [")
            upload_to_github(clean_text)
            
        except Exception as e:
            print(f"❌ エラー: {e}")

if __name__ == "__main__":
    asyncio.run(main())
