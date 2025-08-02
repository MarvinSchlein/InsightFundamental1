import openai
import os
import json
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# API Key handling for both GitHub Actions and Streamlit Cloud
try:
    import streamlit as st
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", "")
except (ImportError, AttributeError, KeyError):
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Initialize OpenAI client (new API style)
if OPENAI_API_KEY:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
else:
    print("❌ ERROR: OPENAI_API_KEY ist nicht gesetzt.")
    client = None

def analyze_news(title, description):
    if not client:
        return get_fallback_analysis(title, description)
        
    prompt = (
        f"You are a professional financial analyst. Your task is to analyze financial news articles exclusively in English.\n\n"
        f"Title: {title}\n"
        f"Description: {description}\n\n"
        f"Respond with a valid JSON object including the following fields:\n"
        f"- impact: A number between -10 (very bearish) and +10 (very bullish)\n"
        f"- confidence: high, medium, or low\n"
        f"- markets: Affected markets or sectors (comma-separated)\n"
        f"- patterns: Similar historical events (in English, max 100 words)\n"
        f"- explanation: A detailed reasoning (at least 150 words, in English)\n\n"
        f"IMPORTANT:\n"
        f"- All text content must be written in **English** only.\n"
        f"- Return only valid JSON – no markdown, no explanation, no commentary.\n"
        f"- Example response:\n"
        f"{{\"impact\": 3, \"confidence\": \"medium\", \"markets\": \"S&P 500, Tech\", \"patterns\": \"Similar to...\", \"explanation\": \"This news indicates...\"}}"
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1000
        )
        raw = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        
        try:
            parsed = json.loads(raw)
            print(f"✅ Successfully analyzed: {title[:50]}...")
        except json.JSONDecodeError as je:
            print(f"⚠️ JSON parsing error for '{title[:30]}...': {je}")
            print(f"Raw response: {raw}")
            return get_fallback_analysis(title, description)
        
        # Ensure all required fields are present with proper types
        return {
            "impact": str(parsed.get("impact", 0)),
            "confidence": parsed.get("confidence", "medium"),
            "markets": parsed.get("markets", "Unknown"),
            "patterns": parsed.get("patterns", "No historical patterns identified"),
            "explanation": parsed.get("explanation", "Analysis not available")
        }
        
    except Exception as e:
        print(f"❌ Error with OpenAI analysis for '{title[:30]}...': {e}")
        return get_fallback_analysis(title, description)

def get_fallback_analysis(title, description):
    """Fallback analysis when OpenAI fails"""
    return {
        "impact": "0",
        "confidence": "low",
        "markets": "General",
        "patterns": "Analysis unavailable due to API error",
        "explanation": f"Unable to analyze article: {title}. Description: {description[:100]}..."
    }
