# backend/news_ingest.py - FIXED CSV FORMAT + OPENAI API SETUP

import os
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv
from news_processor import analyze_news

# Load environment variables
load_dotenv()

# === 0) OpenAI API-Key setzen (für GitHub Actions & lokal) ===
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("❌ ERROR: OPENAI_API_KEY ist nicht gesetzt!")
    exit(1)

import openai
openai.api_key = openai_api_key

# === 1) Konfiguration ===
try:
    import streamlit as st
    FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY") or st.secrets.get("FINNHUB_API_KEY", "")
except (ImportError, AttributeError, KeyError):
    FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

if not FINNHUB_API_KEY:
    print("❌ ERROR: FINNHUB_API_KEY ist nicht gesetzt. Bitte setze ihn via Umgebungsvariable oder Secrets.")
    exit(1)

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT = DATA_DIR / "news_analysis_results.csv"
NEWS_CATEGORIES = ["general", "forex", "earnings", "economy"]

# === 2) Artikel holen ===
def fetch_latest_articles(api_key: str, from_dt: datetime, to_dt: datetime):
    all_articles = []
    print(f"🔍 Fetching articles from {len(NEWS_CATEGORIES)} categories...")

    for category in NEWS_CATEGORIES:
        url = "https://finnhub.io/api/v1/news"
        params = {"category": category, "token": api_key}

        try:
            print(f"📡 Fetching {category} news...")
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            articles = resp.json()
            print(f"📊 {category}: {len(articles)} articles received from API")

            category_articles = 0
            for article in articles:
                article_dt = datetime.fromtimestamp(article.get('datetime', 0), tz=timezone.utc)
                if from_dt <= article_dt <= to_dt:
                    article['source_category'] = category
                    all_articles.append(article)
                    category_articles += 1

            print(f"✅ {category}: {category_articles} articles in time range")

        except Exception as e:
            print(f"❌ Error fetching {category} news: {e}")
            continue

    print(f"📈 Total articles in time range: {len(all_articles)}")
    all_articles.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    return all_articles

# === 3) CSV schreiben ===
def append_to_csv(articles: list, path: Path):
    fieldnames = [
        "title", "description", "publishedAt", "sentiment", "markets",
        "intensity", "impact", "confidence", "patterns", "explanation", "image"
    ]
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)

    print(f"📝 Writing {len(articles)} articles to {path}")
    print(f"📁 File exists: {path.exists()}")

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
            print("📋 Added CSV header")
        for a in articles:
            published_at = datetime.fromtimestamp(a.get('datetime', 0), tz=timezone.utc).isoformat()
            writer.writerow({
                "title":       a.get("headline", ""),
                "description": a.get("summary", ""),
                "publishedAt": published_at,
                "sentiment":   a.get("sentiment", "Finance"),
                "markets":     a.get("markets", ""),
                "intensity":   a.get("intensity", "medium"),
                "impact":      a.get("impact", "0"),
                "confidence":  a.get("confidence", "medium"),
                "patterns":    a.get("patterns", ""),
                "explanation": a.get("explanation", ""),
                "image":       ""
            })

    print(f"✅ Successfully wrote {len(articles)} articles to CSV")

# === 4) Hauptfunktion ===
def main():
    now = datetime.now(timezone.utc)
    hours_back = int(os.getenv("ARTICLE_LOOKBACK_HOURS", 1))
    time_ago = now - timedelta(hours=hours_back)

    print(f"🕐 Current time: {now.isoformat()}")
    print(f"⏰ Looking for articles from {time_ago.isoformat()} to {now.isoformat()}")
    print(f"⏳ Time window: {hours_back} hours")

    articles = fetch_latest_articles(FINNHUB_API_KEY, time_ago, now)

    if not articles:
        print("⚠️  No articles found in time window!")
        return

    print(f"🎯 Found {len(articles)} articles to analyze")
    analyzed_articles = []

    for i, article in enumerate(articles, 1):
        title = article.get("headline", "")
        description = article.get("summary", "")

        print(f"🔄 [{i}/{len(articles)}] Analyzing: {title[:50]}...")
        try:
            analysis = analyze_news(title, description)
            print(f"✅ Analysis successful for article {i}")
        except Exception as e:
            print(f"❌ Analysis failed for article {i}: {title[:30]}... Error: {e}")
            continue

        article.update({
            "sentiment":   analysis.get("sentiment", "Finance"),
            "markets":     analysis.get("markets", ""),
            "intensity":   analysis.get("intensity", "medium"),
            "impact":      analysis.get("impact", "0"),
            "confidence":  analysis.get("confidence", "medium"),
            "patterns":    analysis.get("patterns", ""),
            "explanation": analysis.get("explanation", ""),
        })

        analyzed_articles.append(article)

    print(f"📊 Analysis summary:")
    print(f"   - Total articles found: {len(articles)}")
    print(f"   - Successfully analyzed: {len(analyzed_articles)}")
    print(f"   - Failed analyses: {len(articles) - len(analyzed_articles)}")

    if analyzed_articles:
        append_to_csv(analyzed_articles, OUTPUT)
        print(f"✅ Appended {len(analyzed_articles)} analyzed articles to {OUTPUT}")
    else:
        print("⚠️  No articles were successfully analyzed.")

if __name__ == "__main__":
    main()
