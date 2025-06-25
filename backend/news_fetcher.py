import requests
import os
import pandas as pd
from dotenv import load_dotenv
from pathlib import Path

# Lade die .env-Datei exakt per Pfad
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=dotenv_path)

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

def fetch_news(query="wirtschaft OR börse OR aktien", language="de", page_size=10):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": language,
        "pageSize": page_size,
        "sortBy": "publishedAt",
        "apiKey": NEWSAPI_KEY
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        print("Fehler beim Abrufen der Nachrichten:", response.text)
        return pd.DataFrame()

    articles = response.json().get("articles", [])
    data = []

    for article in articles:
        data.append({
            "title": article["title"],
            "description": article["description"],
            "content": article["content"],
            "url": article["url"],
            "publishedAt": article["publishedAt"]
        })

    df = pd.DataFrame(data)
    filename = "data/latest_news.csv"
    df.to_csv(filename, index=False)
    print(f"{len(df)} Nachrichten gespeichert in {filename}")
    return df