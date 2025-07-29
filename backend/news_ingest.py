# backend/news_ingest.py

import os
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# === 1) Konfiguration ===
API_KEY = os.getenv("FINNHUB_API_KEY")
if not API_KEY:
    print("❌ ERROR: FINNHUB_API_KEY ist nicht gesetzt. Bitte lege ihn mit\n"
          "   export FINNHUB_API_KEY=\"dein_key\"\n"
          "in deiner Shell ab und lade dein Profil neu (z.B. `source ~/.zshrc`).")
    exit(1)

# Pfad zum Frontend-Datenordner
DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT   = DATA_DIR / "news_analysis_results.csv"

# Finnhub news categories to fetch
NEWS_CATEGORIES = ["general", "forex", "earnings", "economy"]

# === 2) Artikel holen ===
def fetch_latest_articles(api_key: str, from_dt: datetime, to_dt: datetime):
    all_articles = []
    
    for category in NEWS_CATEGORIES:
        url = "https://finnhub.io/api/v1/news"
        params = {
            "category": category,
            "token": api_key
        }
        
        try:
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            articles = resp.json()
            
            # Add source_category to each article and filter by date
            for article in articles:
                # Convert Unix timestamp to datetime
                article_dt = datetime.fromtimestamp(article.get('datetime', 0), tz=timezone.utc)
                
                # Only include articles within our time range
                if from_dt <= article_dt <= to_dt:
                    article['source_category'] = category
                    all_articles.append(article)
                    
        except Exception as e:
            print(f"❌ Error fetching {category} news: {e}")
            continue
    
    # Sort articles by datetime (most recent first)
    all_articles.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    
    return all_articles

# === 3) CSV schreiben (anfügen, falls existiert) ===
def append_to_csv(articles: list, path: Path):
    fieldnames = ["source","author","title","description","url","publishedAt","content","source_category","impact","confidence","markets","patterns","explanation"]
    new_file   = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        for a in articles:
            # Convert Unix timestamp to ISO format
            published_at = datetime.fromtimestamp(a.get('datetime', 0), tz=timezone.utc).isoformat()
            
            writer.writerow({
                "source":         a.get("source", "Finnhub"),
                "author":         "",  # Finnhub doesn't provide author info
                "title":          a.get("headline", ""),
                "description":    a.get("summary", ""),
                "url":            a.get("url", ""),
                "publishedAt":    published_at,
                "content":        a.get("summary", ""),  # Use summary as content
                "source_category": a.get("source_category", "general"),
                "impact":         "",  # Will be filled by analysis
                "confidence":     "",  # Will be filled by analysis
                "markets":        "",  # Will be filled by analysis
                "patterns":       "",  # Will be filled by analysis
                "explanation":    "",  # Will be filled by analysis
            })

# === 4) Hauptfunktion ===
def main():
    now          = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    print(f"[{now.isoformat()}] Fetching articles from "
          f"{one_hour_ago.isoformat()} to {now.isoformat()}…")

    articles = fetch_latest_articles(API_KEY, one_hour_ago, now)
    if articles:
        append_to_csv(articles, OUTPUT)
        print(f"✅ Appended {len(articles)} new articles to {OUTPUT}")
    else:
        print("ℹ️  No new articles in this interval.")

if __name__ == "__main__":
    main()
