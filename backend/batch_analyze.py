import pandas as pd
from news_fetcher import fetch_news
from news_processor import analyze_news
from pathlib import Path

# Pfad zur Ausgabedatei
output_path = Path("data/news_analysis_results.csv")

def analyze_all():
    print("Das Skript läuft...")

    # Nachrichten abrufen
    df = fetch_news()

    if df.empty:
        print("Keine Nachrichten gefunden.")
        return

    print(f"{len(df)} Nachrichten gespeichert in data/latest_news.csv")

    results = []

    for i, row in df.iterrows():
        title = row.get("title", "")
        description = row.get("description", "")
        print(f"Analysiere Nachricht {i+1}...")

        result = analyze_news(title, description)

        # Ergänze Metadaten
        result["title"] = title
        result["description"] = description
        result["publishedAt"] = row.get("publishedAt", "")
        result["image"] = row.get("urlToImage", "")

        results.append(result)

    # Neue DataFrame mit Resultaten
    result_df = pd.DataFrame(results)

    # Speichern
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(output_path, index=False)
    print("Analyse abgeschlossen. Datei gespeichert.")

if __name__ == "__main__":
    analyze_all()
