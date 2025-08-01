import openai
import os
import json
from dotenv import load_dotenv
from datetime import datetime
import streamlit as st


load_dotenv()
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
def analyze_news(title, description):
    prompt = (
    f"You are a professional financial analyst. Your task is to analyze financial news articles exclusively in English.\n\n"
    f"Title: {title}\n"
    f"Description: {description}\n\n"
    f"Respond with a valid JSON object including the following fields:\n"
    f"- sentiment: One of: 'Economy', 'Politics', 'Finance', 'Technology'\n"
    f"- markets: Affected markets or sectors\n"
    f"- intensity: weak, medium, or strong\n"
    f"- impact: A number between -10 (very bearish) and +10 (very bullish)\n"
    f"- confidence: high, medium, or low\n"
    f"- patterns: Similar historical events (in English)\n"
    f"- description: A high-quality summary of the news article (80–120 words, in English)\n"
    f"- explanation: A detailed reasoning (at least 200 words, in English)\n\n"
    f"IMPORTANT:\n"
    f"- All text content must be written in **English** only.\n"
    f"- Return only valid JSON – no markdown, no explanation, no commentary.\n"
    f"- Example response:\n"
    f"{{\"sentiment\": \"Finance\", \"markets\": \"S&P 500\", ... }}"
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
            print("⚠️ Error parsing JSON. Original response:")
            print(raw)
            parsed = {
                "sentiment": "Finance",
                "markets": "-",
                "intensity": "medium",
                "impact": 0,
                "confidence": "medium",
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
        print("❌ Error with OpenAI:", e)
        return {
            "title": title,
            "description": description,
            "publishedAt": datetime.now().isoformat(),
            "sentiment": "Finance",
            "markets": "-",
            "intensity": "medium",
            "impact": 0,
            "confidence": "medium",
            "patterns": "-",
            "explanation": "Analysis not available."
        }
