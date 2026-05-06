import feedparser
import os
import asyncio
import requests
import datetime
import base64
from google import genai
from google.genai import types

# ==========================================
# 🗝️ GitHubの金庫（Secrets）から鍵を自動で呼び出します
# ==========================================
GITHUB_TOKEN = os.environ.get("MY_GITHUB_TOKEN")
GITHUB_REPO = "keiyamada-ui/keiyamada-ui.github.io"
# ==========================================

def get_latest_news(limit=3):
    print("📰 ニュースを自動取得しています...")
    feed_url = "https://techcrunch.com/category/artificial-intelligence/feed/"
    parsed_feed = feedparser.parse(feed_url)
    
    news_list = []
    for entry in parsed_feed.entries[:limit]:
        news_list.append({
            "title": entry.title,
            "link": entry.link
        })
    return news_list

def upload_to_github(news_title, ai_content, news_url):
    print(f"\n📝 GitHubへ記事を自動アップロードしています...")
    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    safe_title = "".join([c if c.isalnum() else "_" for c in news_title])[:20]
    file_path = f"_posts/{date_str}-{safe_title}-{now.strftime('%H%M%S')}.md"
    
    markdown_data = f"""---
layout: post
title: "{news_title.replace('"', ' ')}"
date: {time_str}
---

{ai_content}

[元記事はこちら]({news_url})
"""
    encoded_content = base64.b64encode(markdown_data.encode('utf-8')).decode('utf-8')
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "message": f"Auto post: {news_title}",
        "content": encoded_content,
        "branch": "main" 
    }
    
    response = requests.put(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        print("✅ GitHubへのアップロードが完了しました！")
    else:
        print(f"❌ エラーが発生しました: {response.text}")

async def main():
    # Gemini APIキーも自動で環境変数から読み込まれます
    client = genai.Client()
    system_instruction = """
    あなたはプロのITジャーナリストです。
    指定されたURLの記事内容を調べ、日本語で以下のフォーマットで出力してください。
    
    ## 記事の要約（3行）
    （ここに箇条書きで3行）
    
    ## ビジネスへの影響・考察
    （ここに詳細な考察）
    """
    
    news_items = get_latest_news(limit=2)
    if not news_items:
        return

    print(f"✅ {len(news_items)}件のニュースを取得しました。要約を開始します...\n" + "="*40)

    for i, news in enumerate(news_items, 1):
        print(f"🔄 [{i}/{len(news_items)}] 処理中: {news['title']}")
        prompt = f"以下のURLの内容を要約してください。\nURL: {news['link']}"
        
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
            async for chunk in response:
                full_ai_text += chunk.text
            
            upload_to_github(news['title'], full_ai_text, news['link'])
            
        except Exception as e:
            print(f"\n❌ エラーが発生しました: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())
