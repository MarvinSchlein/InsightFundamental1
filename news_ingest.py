# backend/news_ingest.py

import os
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

# === 1) Konfiguration ===
API_KEY = os.getenv("NEWSAPI_KEY")
if not API_KEY:
    print("❌ ERROR: NEWSAPI_KEY ist nicht gesetzt. Bitte lege ihn mit\n"
          "   export NEWSAPI_KEY=\"dein_key\"\n"
          "in deiner Shell ab und lade dein Profil neu (z.B. `source ~/.zshrc`).")
    exit(1)

# Pfad zum Frontend-Datenordner
DATA_DIR = Path(__file__).parent.parent / "frontend" / "data"
OUTPUT   = DATA_DIR / "news_analysis_results.csv"

# === 2) Artikel holen ===
def fetch_latest_articles(api_key: str, from_dt: datetime, to_dt: datetime):
    url = "https://newsapi.org/v2/everything"
    frm = from_dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    to  = to_dt  .replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "apiKey":   api_key,
        "from":     frm,
        "to":       to,
        "language": "de",
        "sortBy":   "publishedAt",
        "pageSize": 100,
        "q":        "news",          # <- hier der Suchbegriff
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("articles", [])

# === 3) CSV schreiben (anfügen, falls existiert) ===
def append_to_csv(articles: list, path: Path):
    fieldnames = ["source","author","title","description","url","publishedAt","content"]
    new_file   = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        for a in articles:
            writer.writerow({
                "source":      a["source"]["name"],
                "author":      a.get("author"),
                "title":       a.get("title"),
                "description": a.get("description"),
                "url":         a.get("url"),
                "publishedAt": a.get("publishedAt"),
                "content":     a.get("content"),
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