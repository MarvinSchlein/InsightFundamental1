import requests
import os
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
import streamlit as st

# Lade die .env-Datei exakt per Pfad
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=dotenv_path)

try:
    import streamlit as st
    FINNHUB_API_KEY = st.secrets["FINNHUB_API_KEY"]
except (ImportError, AttributeError, KeyError):
    import os
    FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
# Finnhub news categories to fetch
NEWS_CATEGORIES = ["general", "forex", "earnings", "economy"]

def fetch_news(categories=None, page_size=50):
    if categories is None:
        categories = NEWS_CATEGORIES
    
    all_articles = []
    
    for category in categories:
        url = "https://finnhub.io/api/v1/news"
        params = {
            "category": category,
            "token": FINNHUB_API_KEY
        }

        try:
            response = requests.get(url, params=params)
            if response.status_code != 200:
                print(f"Fehler beim Abrufen der {category} Nachrichten:", response.text)
                continue

            articles = response.json()
            
            # Add source_category to each article
            for article in articles[:page_size//len(categories)]:  # Distribute page_size across categories
                article['source_category'] = category
                all_articles.append(article)
                
        except Exception as e:
            print(f"Fehler beim Abrufen der {category} Nachrichten: {e}")
            continue

    # Sort articles by datetime (most recent first)
    all_articles.sort(key=lambda x: x.get('datetime', 0), reverse=True)
    
    # Limit to page_size
    all_articles = all_articles[:page_size]
    
    data = []
    for article in all_articles:
        # Convert Unix timestamp to ISO format
        published_at = datetime.fromtimestamp(article.get('datetime', 0), tz=timezone.utc).isoformat()
        
        data.append({
            "title": article.get("headline", ""),
            "description": article.get("summary", ""),
            "content": article.get("summary", ""),
            "url": article.get("url", ""),
            "publishedAt": published_at,
            "source_category": article.get("source_category", "general")
        })

    df = pd.DataFrame(data)
    filename = "data/latest_news.csv"
    df.to_csv(filename, index=False)
    print(f"{len(df)} Nachrichten aus {len(categories)} Kategorien gespeichert in {filename}")
    return df
