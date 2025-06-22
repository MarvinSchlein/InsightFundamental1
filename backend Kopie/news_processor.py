import openai
import os
import json
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def analyze_news(title, description):
    prompt = (
        f"Du bist ein professioneller Finanzanalyst. Analysiere folgende Nachricht:\n\n"
        f"Titel: {title}\n"
        f"Beschreibung: {description}\n\n"
        f"Gib die Auswertung als korrektes JSON zurück mit diesen Feldern:\n"
        f"- sentiment: Eine dieser Kategorien: 'Wirtschaft', 'Politik', 'Finanzen', 'Technologie'. Wähle die passendste.\n"
        f"- markets: betroffene Märkte oder Branchen\n"
        f"- intensity: schwach, mittel, stark\n"
        f"- impact: Skala von -10 (sehr bearish) bis +10 (sehr bullish)\n"
        f"- confidence: hoch, mittel, niedrig\n"
        f"- patterns: ähnliche Ereignisse aus der Vergangenheit\n"
        f"- description: hochwertige Zusammenfassung der Nachricht (80–120 Wörter)\n"
        f"- explanation: ausführliche Analysebegründung (mind. 200 Wörter)\n\n"
        f"Gib ausschließlich korrektes JSON zurück. Beispiel:\n"
        f"{{\"sentiment\": \"Wirtschaft\", \"markets\": \"DAX\", ... }}"
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1000
        )
        raw = response.choices[0].message.content.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            print("⚠️ Fehler beim JSON-Parsing. Originalantwort:")
            print(raw)
            parsed = {
                "sentiment": "Wirtschaft",
                "markets": "-",
                "intensity": "mittel",
                "impact": 0,
                "confidence": "mittel",
                "patterns": "-",
                "description": description,
                "explanation": raw
            }

        return {
            "title": title,
            "description": parsed.get("description", description),
            "publishedAt": datetime.now().isoformat(),
            **parsed
        }

    except Exception as e:
        print("❌ Fehler bei OpenAI:", e)
        return {
            "title": title,
            "description": description,
            "publishedAt": datetime.now().isoformat(),
            "sentiment": "Wirtschaft",
            "markets": "-",
            "intensity": "mittel",
            "impact": 0,
            "confidence": "mittel",
            "patterns": "-",
            "explanation": "Analyse nicht verfügbar."
        }