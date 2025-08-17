import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import hashlib
import json
import yfinance as yf
import streamlit.components.v1 as components
import numpy as np
import requests
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from urllib.parse import urlencode
import secrets
from urllib.parse import quote, unquote
# Optional: quote, falls du es woanders brauchst
# from urllib.parse import quote

# Lies zuerst aus st.secrets (Streamlit Cloud), dann aus ENV, sonst Fallback
SUPABASE_URL = (
    (st.secrets.get("SUPABASE_URL") if hasattr(st, "secrets") else None)
    or os.getenv("SUPABASE_URL")
    or "https://DEIN_PROJECT_REF.supabase.co"
)
SUPABASE_KEY = (
    (st.secrets.get("SUPABASE_ANON_KEY") or st.secrets.get("SUPABASE_KEY") if hasattr(st, "secrets") else None)
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_KEY")
)

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY. Bitte in st.secrets oder ENV hinterlegen.")
    st.stop()


# === .env laden (lokal) ===
load_dotenv()

# === Streamlit Page Config ===
st.set_page_config(page_title="InsightFundamental", layout="wide")

# === Basis-Konfiguration / Secrets ===
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ABSENDER = SMTP_USER

# Für Reset-Link (Basis-URL deiner App; z.B. Streamlit Cloud URL)
APP_BASE_URL = (
    (st.secrets.get("APP_BASE_URL") if hasattr(st, "secrets") else None)
    or os.getenv("APP_BASE_URL")
    or "https://insightfundamental.streamlit.app"
).rstrip("/")

# === Supabase-Client (Frontend NUR mit Anon Key!) ===
SUPABASE_URL = (
    (st.secrets.get("SUPABASE_URL") if hasattr(st, "secrets") else None)
    or os.getenv("SUPABASE_URL")
    or "https://hpjprbhavtewgpbjwdic.supabase.co"
)

SUPABASE_ANON_KEY = (
    (st.secrets.get("SUPABASE_ANON_KEY") if hasattr(st, "secrets") else None)
    or os.getenv("SUPABASE_ANON_KEY")
    # Fallback auf deinen bisherigen Key (bitte langfristig NICHT hardcoden!)
    or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhwanByYmhhdnRld2dwYmp3ZGljIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTQ2NTMyMzcsImV4cCI6MjA3MDIyOTIzN30.9Dk0YhonY5nT80UdRo6VtQ76jfSOXEavmjMH_FwaMvw"
)

supabase: Client | None = None
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
except Exception as e:
    st.warning(f"Supabase client could not be created: {e}")
    supabase = None

# === Nutzer-Datei (Altbestand; bleibt als Fallback/Debug) ===
USER_FILE = Path("data/users.json")
USER_FILE.parent.mkdir(parents=True, exist_ok=True)
if not USER_FILE.exists():
    USER_FILE.write_text(json.dumps({}))  # leeres JSON schreiben

def load_users() -> dict:
    try:
        if USER_FILE.exists() and USER_FILE.read_text().strip():
            return json.loads(USER_FILE.read_text())
        else:
            return {}
    except Exception as e:
        st.error(f"Fehler beim Laden der Nutzerdaten: {e}")
        return {}

def save_users(users: dict):
    try:
        USER_FILE.write_text(json.dumps(users, indent=4))
    except Exception as e:
        st.error(f"Fehler beim Speichern der Nutzerdaten: {e}")

# === Navigation ===
if "view" not in st.session_state:
    st.session_state["view"] = "landing"

def redirect_to(page_name: str):
    st.query_params["view"] = page_name
    st.rerun()

view = st.query_params.get("view", "landing")

# === Supabase-Utils ===
def insert_user_to_supabase(email: str, pwd_hash: str):
    """
    Legt den Nutzer in der Supabase-Tabelle 'users' an.
    WICHTIG: Spalte heißt 'pwd' (nicht 'password'); Email klein schreiben.
    """
    if supabase is None:
        return False, "Supabase client not configured"

    data = {
        "email": email.strip().lower(),
        "pwd": pwd_hash,
        "subscription_active": False
    }
    try:
        res = supabase.table("users").insert(data).execute()
        return True, res.data
    except Exception as e:
        return False, str(e)

def refresh_subscription_status():
    """
    Holt 'subscription_active' des eingeloggten Nutzers aus Supabase
    und setzt session: subscription_active + user_plan ('paid'|'free').
    """
    try:
        state = st.session_state
        if supabase is None or not state.get("username"):
            return

        email = state["username"].strip().lower()
        resp = supabase.table("users").select("subscription_active").eq("email", email).execute()
        if resp.data:
            active = bool(resp.data[0].get("subscription_active"))
            state.subscription_active = active
            state.user_plan = "paid" if active else "free"
    except Exception as e:
        st.warning(f"Refresh error: {e}")

# === Forgot-Password: Helper (Supabase) ===
def create_reset_token() -> str:
    # URL-sicherer Token
    return secrets.token_urlsafe(32)

def store_reset_token(email: str, token: str, ttl_hours: int = 2) -> bool:
    """
    Speichert den Reset-Token in 'password_resets' mit Ablaufzeit.
    Erwartete Spalten: email(text), token(text unique), expires_at(timestamptz)
    """
    if supabase is None:
        return False
    try:
        expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        supabase.table("password_resets").insert({
            "email": email.strip().lower(),
            "token": token,
            "expires_at": expires.isoformat()
        }).execute()
        return True
    except Exception as e:
        st.error(f"Could not store reset token: {e}")
        return False

def fetch_reset_by_token(token: str):
    """
    Liefert den Reset-Eintrag für einen Token zurück (oder None).
    """
    if supabase is None:
        return None
    try:
        res = supabase.table("password_resets").select("*").eq("token", token).limit(1).execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        st.error(f"Could not fetch reset token: {e}")
        return None

def delete_reset_token(token: str) -> None:
    if supabase is None:
        return
    try:
        supabase.table("password_resets").delete().eq("token", token).execute()
    except Exception:
        pass

def set_user_password(email: str, new_pwd_hash: str) -> bool:
    """
    Setzt das neue Passwort (Hash) in 'users.pwd' für die gegebene E-Mail.
    """
    if supabase is None:
        return False
    try:
        res = supabase.table("users").update({"pwd": new_pwd_hash}).eq("email", email.strip().lower()).execute()
        return bool(res.data)
    except Exception as e:
        st.error(f"Could not update password: {e}")
        return False

def build_reset_link(token: str) -> str:
    """
    Baut die Reset-URL, die in der E-Mail verschickt wird.
    """
    qs = urlencode({"view": "reset_password", "token": token})
    return f"{APP_BASE_URL}/?{qs}"

# === Text Content (English as default) ===

TEXTS = {
    "en": {
        # Navigation
        "home": "Home",
        "news_analysis": "News Analysis",
        "features": "Features",
        "login": "Login",
        "register": "Register",
        "logout": "Logout",
        "free_trial": "Start 14-day free trial now!",

        # Landing Page
        "hero_title": "Make informed investment decisions easily.",
        "hero_subtitle": "Discover the future of market understanding with AI-powered analysis of economic and political news in real-time.",
        "discover_features": "Discover Features",
        "why_insight": "Why InsightFundamental?",
        "start_free": "Start for free now",

        # Features
        "impact_score": "Impact Score",
        "impact_score_desc": "Our AI automatically evaluates the potential impact of each news item on important markets and gives you a clear impact score from -10 to 10.",
        "affected_markets": "Affected Markets",
        "affected_markets_desc": "Instantly identify which indices, sectors, countries or currencies are affected by a news item.",
        "historical_patterns": "Historical Patterns",
        "historical_patterns_desc": "Compare current developments with similar historical events and their market impacts.",
        "confidence_level": "Confidence Level",
        "confidence_level_desc": "Get an assessment of how reliable our AI analysis is - from 'high' to 'low' confidence.",

        # Benefits
        "your_benefits": "Your Benefits",
        "better_decisions": "Better Investment Decisions",
        "better_decisions_desc": "Understand the true drivers behind market movements and make more informed investment decisions.",
        "time_saving": "Time Saving",
        "time_saving_desc": "Save hours of research – our AI analyzes and evaluates news in seconds.",
        "always_informed": "Always Informed",
        "always_informed_desc": "Stay informed about market developments and increase your knowledge of economics and politics.",
        "focused_info": "Focused Information",
        "focused_info_desc": "Focus on what matters – we filter out the most important news for you.",

        # Login/Register
        "login_title": "Login",
        "email": "Email",
        "password": "Password",
        "confirm_password": "Confirm Password",
        "stay_logged_in": "Stay logged in",
        "login_button": "Login",
        "forgot_password": "Forgot password?",
        "register_title": "Register",
        "accept_terms": "I accept the terms and conditions",
        "register_button": "Register",
        "invalid_credentials": "Invalid credentials",
        "email_already_registered": "Email is already registered",
        "passwords_dont_match": "Passwords don't match",
        "accept_terms_error": "Please accept the terms and conditions.",

        # Password Reset
        "reset_password": "Reset Password",
        "reset_password_desc": "Please enter your email address",
        "request_reset": "Request Reset Link",
        "reset_sent": "If the email exists, a reset link has been sent.",
        "new_password": "Set New Password",
        "save_password": "Save Password",
        "password_too_short": "Password too short.",
        "password_changed": "Password successfully changed. You can now log in.",
        "password_saved": "Password successfully changed.",
        "to_login": "To Login",
        "invalid_link": "Invalid or expired link.",

        # Dashboard
        "user_settings": "User Settings",
        "profile": "Profile",
        "subscription": "Subscription",
        "support": "Support",
        "change_password": "Change Password",
        "save_password_dash": "Save Password",
        "cancel_subscription": "Cancel Subscription",
        "subscription_cancelled": "Your subscription has been cancelled.",
        "subscription_already_cancelled": "Your subscription is already cancelled.",
        "subject": "Subject",
        "message": "Message",
        "send": "Send",
        "fill_all_fields": "Please fill in subject and message.",
        "message_sent": "Your message has been sent successfully. We'll get back to you soon!",
        "manage_subscription": "Manage subscription",
        "refresh_access": "Refresh access",
        "portal_open_error": "Could not open the customer portal. Please try again.",
        
        # Status
        "active": "Active",
        "trial": "Trial",
        "cancelled": "Cancelled",
        "unknown": "Unknown",
        "status": "Status:",

        # News
        "filter": "Filter",
        "impact_score_filter": "Impact Score",
        "confidence_level_filter": "Confidence Level",
        "confidence_high": "High",
        "confidence_medium": "Medium",
        "confidence_low": "Low",
        "no_news": "No news available.",
        "learn_more": "Learn More",
        "historical_patterns_news": "Historical Patterns:",
        "analysis": "Analysis:",

        # Features Page
        "features_detail": "Features in Detail",
        "features_subtitle": "Discover all possibilities of InsightFundamental and how they help you make better investment decisions",
        "ready_to_test": "Ready to Test?",
        "ready_to_test_desc": "Start today with InsightFundamental and experience the future of market analysis.",
        "start_trial": "Start 14-day free trial",
        "continue_later": "Continue Later",

        # Language Selection
        "language": "Language",
        "german": "Deutsch",
        "english": "English",

        # Pricing
        "pricing": "Pricing",
        "pricing_title": "Simple, Transparent Pricing",
        "pricing_subtitle": "Get access to all features with our monthly subscription",
        "monthly_price": "19.99€",
        "per_month": "per month",
        "get_started": "Get Started",
        "all_features_included": "All features included:"
    },
    "de": {
        # Navigation
        "home": "Startseite",
        "news_analysis": "Nachrichtenanalyse",
        "features": "Funktionen",
        "login": "Anmelden",
        "register": "Registrieren",
        "logout": "Abmelden",
        "free_trial": "Jetzt 14 Tage kostenlos testen!",
        
        # Landing Page
        "hero_title": "Treffe fundierte Investment-Entscheidungen einfach.",
        "hero_subtitle": "Entdecke die Zukunft des Marktverständnisses mit KI-gestützter Analyse von Wirtschafts- und Politiknachrichten in Echtzeit.",
        "discover_features": "Funktionen entdecken",
        "why_insight": "Warum InsightFundamental?",
        "start_free": "Jetzt kostenlos starten",
        
        # Features
        "impact_score": "Impact Score",
        "impact_score_desc": "Unsere KI bewertet automatisch die potenzielle Auswirkung jeder Nachricht auf wichtige Märkte und gibt dir einen klaren Impact Score von -10 bis 10.",
        "affected_markets": "Betroffene Märkte",
        "affected_markets_desc": "Erkenne sofort, welche Indizes, Sektoren, Länder oder Währungen von einer Nachricht betroffen sind.",
        "historical_patterns": "Historische Muster",
        "historical_patterns_desc": "Vergleiche aktuelle Entwicklungen mit ähnlichen historischen Ereignissen und deren Marktauswirkungen.",
        "confidence_level": "Confidence Level",
        "confidence_level_desc": "Erhalte eine Einschätzung, wie zuverlässig unsere KI-Analyse ist – von 'hoch' bis 'niedrig'.",
        
        # Benefits
        "your_benefits": "Deine Vorteile",
        "better_decisions": "Bessere Investment-Entscheidungen",
        "better_decisions_desc": "Verstehe die wahren Treiber hinter Marktbewegungen und triff fundiertere Investment-Entscheidungen.",
        "time_saving": "Zeitersparnis",
        "time_saving_desc": "Spare Stunden an Recherche – unsere KI analysiert und bewertet Nachrichten in Sekunden.",
        "always_informed": "Immer informiert",
        "always_informed_desc": "Bleibe über Marktgeschehen informiert und erweitere dein Wissen über Wirtschaft und Politik.",
        "focused_info": "Fokussierte Informationen",
        "focused_info_desc": "Konzentriere dich auf das Wesentliche – wir filtern die wichtigsten Nachrichten für dich heraus.",
        
        # Login/Register
        "login_title": "Anmelden",
        "email": "E-Mail",
        "password": "Passwort",
        "confirm_password": "Passwort bestätigen",
        "stay_logged_in": "Angemeldet bleiben",
        "login_button": "Anmelden",
        "forgot_password": "Passwort vergessen?",
        "register_title": "Registrieren",
        "accept_terms": "Ich akzeptiere die AGB",
        "register_button": "Registrieren",
        "invalid_credentials": "Ungültige Zugangsdaten",
        "email_already_registered": "E-Mail ist bereits registriert",
        "passwords_dont_match": "Passwörter stimmen nicht überein",
        "accept_terms_error": "Bitte akzeptiere die AGB.",
        
        # Password Reset
        "reset_password": "Passwort zurücksetzen",
        "reset_password_desc": "Bitte gib deine E-Mail-Adresse ein",
        "request_reset": "Reset-Link anfordern",
        "reset_sent": "Falls die E-Mail existiert, wurde ein Reset-Link versendet.",
        "new_password": "Neues Passwort setzen",
        "save_password": "Passwort speichern",
        "password_too_short": "Passwort zu kurz.",
        "password_changed": "Passwort erfolgreich geändert. Du kannst dich jetzt anmelden.",
        "password_saved": "Passwort erfolgreich geändert.",
        "to_login": "Zum Login",
        "invalid_link": "Ungültiger oder abgelaufener Link.",
        
        # Dashboard
        "user_settings": "Nutzereinstellungen",
        "profile": "Profil",
        "subscription": "Abo",
        "support": "Support",
        "change_password": "Passwort ändern",
        "save_password_dash": "Passwort speichern",
        "cancel_subscription": "Abo kündigen",
        "subscription_cancelled": "Dein Abo wurde gekündigt.",
        "subscription_already_cancelled": "Dein Abo ist bereits gekündigt.",
        "subject": "Betreff",
        "message": "Nachricht",
        "send": "Senden",
        "fill_all_fields": "Bitte Betreff und Nachricht ausfüllen.",
        "message_sent": "Deine Nachricht wurde erfolgreich gesendet. Wir melden uns bald!",
        
        # Status
        "active": "Aktiv",
        "trial": "Testphase",
        "cancelled": "Gekündigt",
        "unknown": "Unbekannt",
        "status": "Status:",
        
        # News
        "filter": "Filter",
        "impact_score_filter": "Impact Score",
        "confidence_level_filter": "Confidence Level",
        "confidence_high": "Hoch",
        "confidence_medium": "Mittel",
        "confidence_low": "Niedrig",
        "no_news": "Keine Nachrichten verfügbar.",
        "learn_more": "Mehr erfahren",
        "historical_patterns_news": "Historische Muster:",
        "analysis": "Analyse:",
        
        # Features Page
        "features_detail": "Funktionen im Detail",
        "features_subtitle": "Entdecke alle Möglichkeiten von InsightFundamental und wie sie dir helfen, bessere Investment-Entscheidungen zu treffen",
        "ready_to_test": "Bereit zum Testen?",
        "ready_to_test_desc": "Starte heute mit InsightFundamental und erlebe die Zukunft der Marktanalyse.",
        "start_trial": "14 Tage kostenlos testen",
        "continue_later": "Später fortfahren",
        
        # Language Selection
        "language": "Sprache",
        "german": "Deutsch",
        "english": "Englisch",

        # Pricing
        "pricing": "Preise",
        "pricing_title": "Einfache, transparente Preise",
        "pricing_subtitle": "Erhalte Zugang zu allen Funktionen mit unserem monatlichen Abonnement",
        "monthly_price": "19,99€",
        "per_month": "pro Monat",
        "get_started": "Jetzt starten",
        "all_features_included": "Alle Funktionen enthalten:"
    }
}

def get_text(key: str) -> str:
    """Gets the translated text for the given key"""
    lang = SESSION.get("language", "en")
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)

# === Session & Nutzerverwaltung ===
USER_FILE = Path("data/users.json")
USER_FILE.parent.mkdir(exist_ok=True, parents=True)

# Wenn Datei nicht existiert oder leer ist → leeres JSON schreiben
if not USER_FILE.exists() or not USER_FILE.read_text().strip():
    USER_FILE.write_text(json.dumps({}))

SESSION = st.session_state

def load_users() -> dict:
    try:
        if USER_FILE.exists() and USER_FILE.read_text().strip():
            return json.loads(USER_FILE.read_text())
        else:
            return {}
    except Exception as e:
        st.error(f"Fehler beim Laden der Nutzerdaten: {e}")
        return {}

def save_users(users: dict):
    try:
        USER_FILE.write_text(json.dumps(users, indent=4))
    except Exception as e:
        st.error(f"Fehler beim Speichern der Nutzerdaten: {e}")

def save_users(users: dict):
    USER_FILE.write_text(json.dumps(users, indent=4))

def init_session_state():
    if "logged_in" not in SESSION:
        SESSION.logged_in = False
    if "username" not in SESSION:
        SESSION.username = ""
    if "user_plan" not in SESSION:
        SESSION.user_plan = None
    if "language" not in SESSION:
        SESSION.language = "en"

init_session_state()


# === Globales CSS inklusive Landing-Page & Dark-Sidebar ===

st.markdown("""
<style>
/* Enhanced Grundlayout with better typography */
html, body, .main, .block-container { 
    background: #fff; 
    color: #000; 
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
    line-height: 1.6;
}
h1,h2,h3 { 
    color: #0b2545; 
    margin: 0; 
    font-weight: 700;
    letter-spacing: -0.025em;
}

/* Landing-Page Hintergrund-Gradient */
.stApp { background: linear-gradient(135deg, #0b2545 0%, #1b325c 50%, #2a4a7a 100%); }

/* Dark Sidebar + weiße Schrift */
section[data-testid="stSidebar"] { background: #0b2545 !important; color: #fff !important; }
section[data-testid="stSidebar"] * { color: #fff !important; }

/* Enhanced Buttons with smooth animations */
button, .stButton>button { 
    background: #0b2545 !important; 
    color: #fff !important; 
    border: none !important; 
    border-radius: 12px !important; 
    padding: 12px 24px !important; 
    font-weight: 600 !important;
    font-size: 0.95em !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    box-shadow: 0 2px 8px rgba(11, 37, 69, 0.15) !important;
    cursor: pointer !important;
}
button:hover, .stButton>button:hover {
    background: #1b325c !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 16px rgba(11, 37, 69, 0.25) !important;
}
button:active, .stButton>button:active {
    transform: translateY(0px) !important;
    box-shadow: 0 2px 8px rgba(11, 37, 69, 0.15) !important;
}
input, textarea {
    background: #fff !important;
    border: 2px solid #0b2545 !important;
    border-radius: 8px !important;
    color: #0b2545 !important;
}

label, .stTextInput label, .stCheckbox span, .st-bb, .st-c6, .st-c7 {
    color: #0b2545 !important;
    font-weight: 600;
}

/* Comprehensive checkbox text color fixes */
.stCheckbox label, .stCheckbox span, .stCheckbox div, .stCheckbox * {
    color: #000000 !important;
}
/* Specific targeting for login and register pages */
div[class*="checkbox"] .stCheckbox *, div[class*="checkbox"] label, div[class*="checkbox"] span {
    color: #000000 !important;
}

/* Input-Feld rechts ohne Rand und ohne Border-Radius, wenn Button daneben */
.stTextInput>div>div>input[type="password"] {
    border-right: none !important;
    border-top-right-radius: 0 !important;
    border-bottom-right-radius: 0 !important;
    margin-right: 0 !important;
    padding-right: 0 !important;
}
/* Button ohne eigenen Rand, nur rechts Border-Radius */
button[title="Passwort anzeigen"], button[title="Passwort ausblenden"], .stTextInput button {
    background: #fff !important;
    border-top: 2px solid #0b2545 !important;
    border-right: 2px solid #0b2545 !important;
    border-bottom: 2px solid #0b2545 !important;
    border-left: none !important;
    border-radius: 0 8px 8px 0 !important;
    box-shadow: none !important;
    margin: 0 !important;
    padding: 0.2em 0.5em !important;
    position: static !important;
    z-index: 2;
}
button[title="Passwort anzeigen"]:hover, button[title="Passwort ausblenden"]:hover, .stTextInput button:hover {
    background: #fff !important;
    border: none !important;
    box-shadow: none !important;
}
button[title="Passwort anzeigen"] svg, button[title="Passwort ausblenden"] svg, .stTextInput button svg {
    color: #0b2545 !important;
    fill: #0b2545 !important;
}
/* Umgebende Container des Passwort-Buttons weiß färben */
.stTextInput, .stTextInput>div, .stTextInput>div>div, .stTextInput>div>div>button, .stTextInput>div>div>button>div {
    background: #fff !important;
    box-shadow: none !important;
    border: none !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Button exakt an das Input-Feld kleben */
button[title="Passwort anzeigen"], button[title="Passwort ausblenden"], .stTextInput button {
    position: relative !important;
    left: 0 !important;
    margin-left: -4px !important;
    z-index: 2;
}

/* Header-Navigation */
.header-nav { display:flex; align-items:center; justify-content:space-between; padding:1rem 2rem; background:rgba(11,37,69,0.9); backdrop-filter:blur(10px); border-radius:0 0 15px 15px; }
.header-nav h1 { font-size:2.4em; color:#fff; font-weight:700; }
.header-nav a { margin-left:1.5rem; color:#fff; text-decoration:none; font-weight:600; transition:all 0.3s ease; }
.header-nav a:hover { color:#4a9eff; transform:translateY(-2px); }
/* Header Button Style - einheitlich mit Standard Streamlit Buttons */
.header-nav a.button {
    background: #0b2545 !important;
    color: #fff !important;
    border: 2px solid #0b2545 !important;
    border-radius: 25px !important;
    font-weight: 700;
    box-shadow: none !important;
    padding: 1rem 2rem !important;
}
.header-nav a.button:hover {
    background: #1b325c !important;
    color: #fff !important;
    box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
}

/* Landing-Hero */
.landing-hero { text-align:center; color:#fff; padding:6rem 2rem; }
.landing-hero h2 { font-size:4em; margin-bottom:1rem; font-weight:800; background:linear-gradient(45deg, #fff, #4a9eff); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.landing-hero p { font-size:1.4em; margin-bottom:2rem; line-height:1.6; opacity:0.9; }
.hero-buttons { display:flex; gap:1rem; justify-content:center; margin-top:2rem; }
.hero-buttons a { display:inline-block; padding:1rem 2rem; border-radius:30px; text-decoration:none; font-weight:600; transition:all 0.3s ease; }
.hero-buttons .primary { background:#0b2545; color:#fff; box-shadow:0 6px 20px rgba(11,37,69,0.4); }
.hero-buttons .secondary { background:rgba(255,255,255,0.1); color:#fff; border:2px solid rgba(255,255,255,0.3); backdrop-filter:blur(10px); }
.hero-buttons a:hover { transform:translateY(-3px); box-shadow:0 8px 25px rgba(11,37,69,0.5); }

/* Features Section */
.features-section { padding:4rem 2rem; background:rgba(255,255,255,0.05); backdrop-filter:blur(10px); margin:2rem 0; border-radius:20px; }
.features-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:2rem; margin-top:3rem; }
.feature-card { background:rgba(255,255,255,0.1); padding:2rem; border-radius:15px; backdrop-filter:blur(10px); border:1px solid rgba(255,255,255,0.2); transition:all 0.3s ease; }
.feature-card:hover { transform:translateY(-5px); background:rgba(255,255,255,0.15); }
.feature-icon { font-size:3em; margin-bottom:1rem; }
.feature-card h3 { color:#4a9eff; font-size:1.5em; margin-bottom:1rem; }
.feature-card p { color:#fff; opacity:0.9; line-height:1.6; }

/* Benefits Section */
.benefits-section { padding:4rem 2rem; }
.benefit-item { display:flex; align-items:center; margin:2rem 0; padding:1.5rem; background:rgba(255,255,255,0.05); border-radius:15px; backdrop-filter:blur(10px); }
.benefit-icon { font-size:2.5em; margin-right:1.5rem; color:#4a9eff; }
.benefit-text h4 { color:#fff; font-size:1.3em; margin-bottom:0.5rem; }
.benefit-text p { color:#fff; opacity:0.8; }

/* CTA Section */
.cta-section { text-align:center; padding:4rem 2rem; background:linear-gradient(45deg, rgba(74,158,255,0.2), rgba(107,182,255,0.2)); border-radius:20px; margin:2rem 0; }
.cta-section h3 { color:#fff; font-size:2.5em; margin-bottom:1rem; }
.cta-section p { color:#fff; font-size:1.2em; margin-bottom:2rem; opacity:0.9; }

/* Markt-Boxen */
.market-box { border:2px solid #0b2545; border-radius:8px; padding:12px; text-align:center; }

/* Hintergrund-Gradient auf den gesamten App-Container anwenden */
section[data-testid="stAppViewContainer"] > div:first-child {
    background: linear-gradient(135deg, #0b2545 0%, #1b325c 50%, #2a4a7a 100%) !important;
}

/* Responsive Design */
@media (max-width: 768px) {
    .landing-hero h2 { font-size:2.5em; }
    .hero-buttons { flex-direction:column; align-items:center; }
    .features-grid { grid-template-columns:1fr; }
    .header-nav { flex-direction:column; gap:1rem; }
}

/* Eltern-Container des Input-Feldes und Buttons anpassen */
.stTextInput>div, .stTextInput>div>div, .stTextInput>div>div>div {
    background: #fff !important;
    margin: 0 !important;
    padding: 0 !important;
    box-shadow: none !important;
}
/* Button leicht nach links schieben, um Lücke zu überdecken */
button[title="Passwort anzeigen"], button[title="Passwort ausblenden"], .stTextInput button {
    margin-left: -2px !important;
}
/* Button mit Auge nahtlos im Input-Feld, ohne eigenen Rand/Hintergrund */
.stTextInput {
    position: static !important;
}
button[title="Passwort anzeigen"], button[title="Passwort ausblenden"], .stTextInput button {
    background: #fff !important;
    border: none !important;
    border-radius: 0 8px 8px 0 !important;
    box-shadow: none !important;
    margin-left: 12px !important;
    padding: 0.2em 0.5em !important;
    position: static !important;
    z-index: 2;
}
button[title="Passwort anzeigen"] svg, button[title="Passwort ausblenden"] svg, .stTextInput button svg {
    color: #0b2545 !important;
    fill: #0b2545 !important;
}
.stTextInput input[type="password"] {
    width: calc(100% - 40px) !important; /* etwas schmaler, damit das Auge Platz hat */
    padding-right: 0.5em !important;
    box-sizing: border-box !important;
}
/* Passwortfeld und Auge-Icon: saubere, einheitliche Darstellung */
.stTextInput>div>div>input[type="password"] {
    width: calc(100% - 38px) !important;
    border-right: none !important;
    border-radius: 8px 0 0 8px !important;
    margin: 0 !important;
    padding-right: 0 !important;
    box-sizing: border-box !important;
}
.stTextInput>div>div>button {
    width: 38px !important;
    min-width: 38px !important;
    max-width: 38px !important;
    background: #fff !important;
    border: 2px solid #0b2545 !important;
    border-left: none !important;
    border-radius: 0 8px 8px 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    box-shadow: none !important;
    position: static !important;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: center;
}
.stTextInput>div>div {
    display: flex !important;
    flex-direction: row !important;
    align-items: stretch !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
/* Verstecke die horizontale Progressbar/Leiste */
div[data-testid="stProgress"] {
    display: none !important;
}
/* Verstecke leere dunkelblaue Balken */
.css-1dp5vir, .css-1avcm0n, .css-1kyxreq {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Hide the sidebar completely */
section[data-testid="stSidebar"] {
    display: none !important;
    width: 0px !important;
    height: 0px !important;
    margin: 0px !important;
    padding: 0px !important;
    visibility: hidden !important;
}
/* Expand the main content to full width */
.main .block-container {
    max-width: 100% !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
.block-container, .main, .block-container > div:first-child {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
section[data-testid="stSidebar"] {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
.content-col {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
/* Linke und mittlere Spalte (Dashboard und Nachrichten) nach oben rücken */
div[data-testid="column"]:nth-of-type(1),
div[data-testid="column"]:nth-of-type(2) {
    margin-top: 0 !important;
    padding-top: 0 !important;
}
</style>
""", unsafe_allow_html=True)

# === Header mit Navigation ===

params = dict(st.query_params)
view = params.get("view", "landing")

# -- HEADER MIT HAMBURGER-BUTTON (nur auf News-Seite) ---

show_hamburger = view in ["news", "Alle Nachrichten"]

# Header wie vorher (ohne Sprachwahl)
header_html = """
<div class="header-nav" style="display:flex;align-items:center;">
    <div style='display:flex;align-items:center;'>
        <h1 style='margin-left:0.7em;'>InsightFundamental</h1>
"""

if show_hamburger:
    header_html += "<span id='dashboard-hamburger-placeholder'></span>"

header_html += "</div><div style='display:flex;align-items:center;'>"

# Only show navigation links if user is not logged in or not on news page
if not SESSION.logged_in or view not in ["news", "Alle Nachrichten"]:
    header_html += f"<a href='/?view=landing'>{get_text('home')}</a>"
    header_html += f"<a href='/?view=news'>{get_text('news_analysis')}</a>"
    header_html += f"<a href='/?view=funktionen'>{get_text('features')}</a>"

if not SESSION.logged_in:
    header_html += f"<a href='/?view=login' class='button'>{get_text('login')}</a>"
    header_html += f"<a href='/?view=register' class='button' style='margin-left:0.7em;'>{get_text('register')}</a>"
    header_html += f"<a href='/?view=register' class='button' style='margin-left:0.7em;'>{get_text('free_trial')}</a>"
else:
    header_html += f"<span style='margin-left:1.5rem; color:#fff; font-weight:600;'>{SESSION.username}</span>"
    header_html += f"<a href='/?logout=1' class='button' style='margin-left:1.5rem;'>{get_text('logout')}</a>"

header_html += "</div></div>"
st.markdown(header_html, unsafe_allow_html=True)
st.markdown("<div style='margin-bottom:2rem;'></div>", unsafe_allow_html=True)

# Logout-Logik
if 'logout' in params:
    SESSION.logged_in = False
    SESSION.username = ''
    SESSION.user_plan = ''
    # Clear filter states on logout to prevent issues
    if "impact_filter_news" in SESSION:
        del SESSION.impact_filter_news
    if "confidence_level_news" in SESSION:
        del SESSION.confidence_level_news
    st.query_params["view"] = "landing"
    st.rerun()

# === Landing-Page ===
if view == "landing":
    # Kein Farbverlauf, Buttons und Feature-Boxen wieder klar umrandet, CTA-Buttons achsensymmetrisch, keine Unterstreichung auf Buttons
    st.markdown("""
    <style>
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border: 2px solid #0b2545 !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: none !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        text-decoration: none !important;
    }
    /* CTA-Buttons klar umrandet, keine Unterstreichung */
    .cta-btn {
        display: inline-block;
        background: #0b2545 !important;
        color: #fff !important;
        border: none !important;
        border-radius: 25px !important;
        font-weight: 700;
        font-size: 1.1em;
        padding: 1rem 2rem;
        text-decoration: none !important;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        transition: background 0.2s, color 0.2s;
        margin: 0.5rem 0.5rem;
    }
    .cta-btn:hover {
        background: #1b325c !important;
        color: #fff !important;
        text-decoration: none !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    /* Feature-Boxen klar umrandet */
    .feature-box {
        background: #fff !important;
        border: 2px solid #0b2545 !important;
        border-radius: 16px !important;
        box-shadow: 0 4px 24px rgba(11,37,69,0.08);
        padding: 2rem 1.2rem 1.2rem 1.2rem;
        margin: 1.2rem 0.5rem;
        min-height: 220px;
        text-align: center;
    }
    .feature-icon {
        font-size: 2.5em;
        margin-bottom: 0.5rem;
    }
    .feature-title {
        color: #0b2545 !important;
        font-size: 1.2em;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .feature-text {
        color: #111 !important;
        opacity: 0.95;
        font-size: 1em;
    }
    </style>
    """, unsafe_allow_html=True)

    # Hero-Bereich mit zentriertem Button
    st.markdown(f"""
    <div class='news-card' style='background:#fff; border:2px solid #e6f0fa; border-radius:18px; box-shadow:0 4px 18px rgba(11,37,69,0.07); padding:2rem 1.5rem 1.2rem 1.5rem; margin:2.2rem auto; max-width:700px; text-align:center;'>
        <h2 style='font-size:3em; color:#0b2545; font-weight:800; margin-top:2rem;'>{get_text('hero_title')}</h2>
        <p style='color:#111; font-size:1.3em; margin-bottom:2.5rem;'>
            {get_text('hero_subtitle')}
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Streamlit button for navigation
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        if st.button(get_text('discover_features'), key="hero_discover_btn"):
            redirect_to("funktionen")
    st.markdown("<br>", unsafe_allow_html=True)

    # Features-Bereich
    st.markdown(f"<h3 style='color:#0b2545; text-align:center; margin-top:3rem;'>{get_text('why_insight')}</h3>", unsafe_allow_html=True)
    
    feature_icons = ["📊", "🎯", "📈", "🔒"]
    feature_titles = [
        get_text('impact_score'),
        get_text('affected_markets'),
        get_text('historical_patterns'),
        get_text('confidence_level')
    ]
    feature_texts = [
        get_text('impact_score_desc'),
        get_text('affected_markets_desc'),
        get_text('historical_patterns_desc'),
        get_text('confidence_level_desc')
    ]
    
    # Erste Zeile der Features
    cols = st.columns(2)
    for i in range(2):
        with cols[i]:
            st.markdown(f"""
            <div class='feature-box'>
                <div class='feature-icon'>{feature_icons[i]}</div>
                <div class='feature-title'>{feature_titles[i]}</div>
                <div class='feature-text'>{feature_texts[i]}</div>
            </div>
            """, unsafe_allow_html=True)
    
    # Zweite Zeile der Features
    cols = st.columns(2)
    for i in range(2, 4):
        with cols[i-2]:
            st.markdown(f"""
            <div class='feature-box'>
                <div class='feature-icon'>{feature_icons[i]}</div>
                <div class='feature-title'>{feature_titles[i]}</div>
                <div class='feature-text'>{feature_texts[i]}</div>
            </div>
            """, unsafe_allow_html=True)

    # Vorteile-Bereich mit einzeln umrandeten Boxen
    st.markdown(f"<h3 style='color:#0b2545; text-align:center; margin-top:3rem;'>{get_text('your_benefits')}</h3>", unsafe_allow_html=True)
    
    benefit_icons = ["💰", "⏰", "📱", "🎯"]
    benefit_titles = [
        get_text('better_decisions'),
        get_text('time_saving'),
        get_text('always_informed'),
        get_text('focused_info')
    ]
    benefit_texts = [
        get_text('better_decisions_desc'),
        get_text('time_saving_desc'),
        get_text('always_informed_desc'),
        get_text('focused_info_desc')
    ]
    
    for i in range(4):
        st.markdown(f"""
        <div style='background:#fff; border:2px solid #0b2545; border-radius:12px; box-shadow:0 2px 12px rgba(11,37,69,0.07); padding:1.2rem 1rem; margin:1.2rem auto; max-width:700px; display:flex; align-items:center; color:#111;'>
            <div style='font-size:2em; margin-right:1.2rem;'>{benefit_icons[i]}</div>
            <div>
                <div style='color:#0b2545; font-size:1.1em; font-weight:700;'>{benefit_titles[i]}</div>
                <div style='color:#111; opacity:0.85;'>{benefit_texts[i]}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Call-to-Action unten
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        if st.button(get_text('start_free'), key="cta_start_free_btn"):
            redirect_to("register")

# === Platzhalter für andere Views ===
elif view == "news-analysis":
    if not st.session_state.get("logged_in") or not st.session_state.get("subscription_active"):
        redirect_to("login")
        st.rerun()
    
    st.title("News Analysis")
    st.write("Hier erscheinen später die analysierten Nachrichten.")

elif view == "reset-password":
    st.title("Reset Password")
    st.write("Hier kann das Passwort zurückgesetzt werden.")

elif view == "cancel-subscription":
    st.title("Cancel Subscription")
    st.write("Hier wird das Abo gekündigt.")

# === Funktionen-Seite ===
if view == "funktionen":
    # Komplett weißer Hintergrund für sanften Übergang
    st.markdown("""
    <style>
    .stApp, .block-container, section[data-testid="stAppViewContainer"] > div:first-child {
        background: #fff !important;
    }
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a, .header-nav a.button {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        border: none !important;
        padding: 1rem 2rem !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    /* Features page specific styling */
    .function-section {
        background: #fff;
        border: 2px solid #0b2545;
        border-radius: 16px;
        padding: 2.5rem;
        margin: 2rem 0;
        box-shadow: 0 4px 24px rgba(11,37,69,0.08);
    }
    .function-header {
        display: flex;
        align-items: center;
        margin-bottom: 1.5rem;
    }
    .function-icon {
        font-size: 3em;
        margin-right: 1.5rem;
    }
    .function-title {
        color: #0b2545;
        font-size: 2em;
        font-weight: 700;
        margin: 0;
    }
    .function-description {
        color: #111;
        font-size: 1.1em;
        line-height: 1.7;
        margin-bottom: 1.5rem;
    }
    .function-benefits {
        background: #f8f9fa;
        border-left: 4px solid #0b2545;
        padding: 1.5rem;
        margin: 1.5rem 0;
        border-radius: 0 8px 8px 0;
    }
    .function-benefits h4 {
        color: #0b2545;
        margin-bottom: 1rem;
        font-size: 1.2em;
    }
    .function-benefits ul {
        margin: 0;
        padding-left: 1.5rem;
    }
    .function-benefits li {
        margin: 0.5rem 0;
        color: #111;
    }
    .function-example {
        background: #e6f0fa;
        border: 1px solid #0b2545;
        border-radius: 8px;
        padding: 1.5rem;
        margin: 1.5rem 0;
    }
    .function-example h4 {
        color: #0b2545;
        margin-bottom: 1rem;
        font-size: 1.1em;
    }
    .function-example p {
        color: #111;
        margin: 0;
        font-style: italic;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="text-align:center; color:#0b2545; padding:3rem 0;">
        <h1 style="font-size:3em; margin-bottom:1rem;">{get_text('features_detail')}</h1>
        <p style="font-size:1.3em; color:#111;">{get_text('features_subtitle')}</p>
    </div>
    """, unsafe_allow_html=True)

    # Feature 1: Real-time News
    st.markdown("""
    <div class="function-section">
        <div class="function-header">
            <div class="function-icon">📰</div>
            <h2 class="function-title">Real-time News</h2>
        </div>
        <div class="function-description">
            We aggregate the most important economic and political news from over 50+ renowned sources worldwide. From Reuters and Bloomberg to specialized financial portals – we keep an eye on everything so you never miss any important market developments.
        </div>
        <div class="function-benefits">
            <h4>Your Benefits:</h4>
            <ul>
                <li><strong>Time saving:</strong> No more tedious searching for relevant news</li>
                <li><strong>Quality filter:</strong> Only reputable, verified sources are considered</li>
                <li><strong>Global perspective:</strong> International news from all major markets</li>
            </ul>
        </div>
        <div class="function-example">
            <h4>Example:</h4>
            <p>Instead of spending hours browsing various news portals, you get a central overview of all relevant developments. An important ECB interest rate decision is immediately displayed with all details and market impact.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Feature 2: Impact Score
    st.markdown("""
    <div class="function-section">
        <div class="function-header">
            <div class="function-icon">📊</div>
            <h2 class="function-title">Impact Score (-10 to 10)</h2>
        </div>
        <div class="function-description">
            Our AI automatically evaluates the potential impact of each news item on important markets. The Impact Score from -10 to 10 gives you an instant, clear assessment of how strongly a news item could affect the markets. A score of 10 means maximum positive market impact, while -10 signals maximum negative relevance.
        </div>
        <div class="function-benefits">
            <h4>Your Benefits:</h4>
            <ul>
                <li><strong>Instant assessment:</strong> AI-powered analysis in seconds</li>
                <li><strong>Objective evaluation:</strong> No human bias or emotion</li>
                <li><strong>Prioritization:</strong> Focus on the truly important news</li>
                <li><strong>Consistent rating:</strong> Same criteria for all news</li>
            </ul>
        </div>
        <div class="function-example">
            <h4>Example:</h4>
            <p>A news item about an unexpected Fed rate hike receives an Impact Score of 9/10, while a local economic news item only gets a score of 3/10. This way, you immediately know which news deserves your attention.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Feature 3: Affected Markets
    st.markdown("""
    <div class="function-section">
        <div class="function-header">
            <div class="function-icon">🎯</div>
            <h2 class="function-title">Affected Markets</h2>
        </div>
        <div class="function-description">
            Instantly get a detailed overview of which indices (DAX, S&P 500), sectors (Tech, Pharma), countries or currencies are affected by a news item. This precise market assignment helps you react specifically to relevant developments and adjust your portfolios accordingly.
        </div>
        <div class="function-benefits">
            <h4>Your Benefits:</h4>
            <ul>
                <li><strong>Precise assignment:</strong> Exact identification of affected markets</li>
                <li><strong>Opportunities:</strong> Spotting chances in affected sectors</li>
                <li><strong>Global perspective:</strong> Overview of international market impacts</li>
            </ul>
        </div>
        <div class="function-example">
            <h4>Example:</h4>
            <p>A news item about new data protection regulation immediately shows: "Affected markets: Tech sector, DAX, Nasdaq, European tech stocks". You instantly know that your tech investments should be reviewed.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Feature 4: Confidence Level
    st.markdown("""
    <div class="function-section">
        <div class="function-header">
            <div class="function-icon">🔒</div>
            <h2 class="function-title">Confidence Level</h2>
        </div>
        <div class="function-description">
            Shows you how reliable our AI analysis is. From "high" (very reliable) to "low" (caution in interpretation) – you always know how much trust you can place in the assessment. The confidence level is based on the quality of data sources, the clarity of the news, and the historical accuracy of our analyses.
        </div>
        <div class="function-benefits">
            <h4>Your Benefits:</h4>
            <ul>
                <li><strong>Transparency:</strong> You always know how reliable the analysis is</li>
                <li><strong>Risk awareness:</strong> Caution with low confidence values</li>
                <li><strong>Trust:</strong> Act with increased certainty at high confidence values</li>
                <li><strong>Quality control:</strong> Continuous improvement of analyses</li>
                <li><strong>Decision support:</strong> Take reliability into account in your decisions</li>
            </ul>
        </div>
        <div class="function-example">
            <h4>Example:</h4>
            <p>A clear ECB interest rate decision receives a "high" confidence level, while a vague hint from a politician only gets "low" confidence. This way, you can weigh your decisions accordingly.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Feature 5: Historical Patterns
    st.markdown("""
    <div class="function-section">
        <div class="function-header">
            <div class="function-icon">📈</div>
            <h2 class="function-title">Historical Patterns</h2>
        </div>
        <div class="function-description">
            Compare new developments with similar historical events and their market impacts. Learn from the past for better future decisions. Our AI automatically identifies similar situations and shows you how the markets behaved back then.
        </div>
        <div class="function-benefits">
            <h4>Your Benefits:</h4>
            <ul>
                <li><strong>Learning from the past:</strong> Historical data as a decision-making aid</li>
                <li><strong>Pattern recognition:</strong> Automatic identification of similar situations</li>
                <li><strong>Risk minimization:</strong> Avoid repeating mistakes</li>
                <li><strong>Opportunity recognition:</strong> Use proven strategies</li>
                <li><strong>Market understanding:</strong> Better understanding of market dynamics</li>
            </ul>
        </div>
        <div class="function-example">
            <h4>Example:</h4>
            <p>For a new trade dispute, the system shows: "Similar patterns: US-China trade war 2018-2020. Back then: DAX -15%, tech sector -20% in 3 months." This way, you can adjust your strategy accordingly.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# === Login ===
if view == "login":
    st.markdown("""
    <style>
    .login-card {
        background: none !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0;
        margin: 3rem auto 2rem auto;
        max-width: 370px;
        min-width: 270px;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    .login-card h2 {
        color:#0b2545;
        font-size:1.7em;
        font-weight:700;
        margin-bottom:1.2em;
        text-align:center;
    }
    .login-card .stTextInput, .login-card .stTextInput>div, .login-card .stTextInput>div>div {
        width: 120px !important;
        max-width: 120px !important;
        min-width: 60px !important;
    }
    .login-card .stTextInput>div>div>input {
        width: 120px !important;
        max-width: 120px !important;
        min-width: 60px !important;
    }
    .login-card .stButton>button {
        width:100%;
        font-size:1.1em;
        padding:0.5em 0;
        border-radius:8px;
        margin-top:1.2em;
    }
    .login-card label, .login-card .stCheckbox {
        width:100%;
        text-align:left;
    }
    .login-card .stCheckbox span {
        color: #000000 !important;
    }
    .stay-checkbox .stCheckbox span {
        color: #000000 !important;
    }
    .stay-checkbox *, .stay-checkbox label, .stay-checkbox span, .stay-checkbox div {
        color: #000000 !important;
    }
    .login-card .stCheckbox *, .login-card .stCheckbox label, .login-card .stCheckbox span {
        color: #000000 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    cols = st.columns([2,1,2])
    with cols[1]:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        st.markdown('<h2>Sign in to your account</h2>', unsafe_allow_html=True)

        email = st.text_input("Email", key="login_email")
        pwd = st.text_input("Password", type="password", key="login_pwd")

        st.markdown('<div class="stay-checkbox">', unsafe_allow_html=True)
        keep_logged_in = st.checkbox("Keep me signed in", key="keep_logged_in")
        st.markdown('</div>', unsafe_allow_html=True)

        login_clicked = st.button("Log in")
        forgot_clicked = st.button("Forgot your password?", key="forgot_pwd_btn")

        if login_clicked:
            email_norm = (email or "").strip().lower()
            if not email_norm or not pwd:
                st.error("Please enter email and password.")
                st.stop()

            try:
                # 1) Primär: Supabase-Python-SDK
                user_id = None
                access_token = None
                refresh_token = None

                try:
                    sb_auth_res = supabase.auth.sign_in_with_password({
                        "email": email_norm,
                        "password": pwd,
                    })
                    # user/session herausziehen (SDK-Struktur!)
                    user_obj = getattr(sb_auth_res, "user", None)
                    sess_obj = getattr(sb_auth_res, "session", None)
                    if user_obj:
                        user_id = getattr(user_obj, "id", None)
                    if sess_obj:
                        access_token = getattr(sess_obj, "access_token", None)
                        refresh_token = getattr(sess_obj, "refresh_token", None)
                except Exception:
                    # SDK könnte auf Streamlit Cloud fehlen/anders reagieren – wir fallen unten auf REST zurück
                    pass

                # 2) Fallback: REST-Endpoint /auth/v1/token?grant_type=password
                if not user_id or not access_token:
                    import requests
                    token_url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
                    r = requests.post(
                        token_url,
                        headers={
                            "apikey": SUPABASE_KEY,
                            "Content-Type": "application/json",
                        },
                        json={"email": email_norm, "password": pwd},
                        timeout=15,
                    )
                    if r.status_code == 200:
                        j = r.json()
                        access_token = j.get("access_token")
                        refresh_token = j.get("refresh_token")
                        user_id = (j.get("user") or {}).get("id")
                    else:
                        st.error("Invalid email or password.")
                        st.stop()

                # ✅ Login erfolgreich
                SESSION.logged_in = True
                SESSION.username = email_norm
                SESSION.user_id = user_id
                SESSION.sb_access_token = access_token
                SESSION.sb_refresh_token = refresh_token
                SESSION.keep_logged_in = bool(keep_logged_in)

                # Abo-Status weiterhin aus deiner 'users'-Tabelle holen
                refresh_subscription_status()

                redirect_to("news")

            except Exception:
                # Keine Details leaken
                st.error("Invalid email or password.")

        if forgot_clicked:
            redirect_to("forgot_password")

        st.markdown('</div>', unsafe_allow_html=True)

    st.stop()

# === Forgot Password (Supabase Auth: E-Mail anfordern) ===
if view == "forgot_password":
    st.markdown("## Forgot your password?")
    st.write("Enter your email address and we'll send you a reset link.")

    with st.form("forgot_form"):
        fp_email = st.text_input("Email address", key="fp_email")
        submitted = st.form_submit_button("Send reset link")

    if submitted:
        email_norm = (fp_email or "").strip().lower()
        if not email_norm:
            st.error("Please enter your email.")
            st.stop()

        # Supabase Auth: /auth/v1/recover – Link und Mail kommen von Supabase
        try:
            import requests
            RECOVER_URL = f"{SUPABASE_URL}/auth/v1/recover"
            headers = {
                "apikey": SUPABASE_KEY,                 # dein anon key
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
            }
            # redirect_to optional – wir nutzen primär den Link aus der E-Mail-Vorlage
            params = {"redirect_to": "https://insightfundamental.streamlit.app/?view=reset_password"}
            r = requests.post(RECOVER_URL, headers=headers, json={"email": email_norm}, params=params, timeout=15)
            if r.status_code in (200, 204):
                st.success("If an account exists for this email, a reset link has been sent.")
            else:
                # keine Details leaken
                st.success("If an account exists for this email, a reset link has been sent.")
        except Exception as e:
            # aus Sicherheitsgründen auch hier Erfolgstext
            st.success("If an account exists for this email, a reset link has been sent.")

        st.markdown("[Back to login](/?view=login)")
        st.stop()

import requests

# === Reset Password (robust, REST only) ===
if view == "reset_password":
    import requests

    st.markdown("## Choose a new password")

    # --- Helfer für Query-Params ---
    def _qp(name: str) -> str:
        v = st.query_params.get(name)
        if isinstance(v, list):
            v = v[0] if v else ""
        return (v or "").strip()

    email      = _qp("email")
    token_hash = _qp("token_hash")
    token_code = _qp("token")   # 6-stellig
    debug      = _qp("debug") in ("1", "true", "yes")

    # Falls fälschlich ein Hash im "token" steckt (lang, nicht nur Ziffern)
    if not token_hash and token_code and (len(token_code) > 12 or not token_code.isdigit()):
        token_hash, token_code = token_code, ""

    pw1 = st.text_input("New password", type="password", key="rp1")
    pw2 = st.text_input("Confirm new password", type="password", key="rp2")
    btn = st.button("Set new password")

    def verify_with(payload: dict):
        url = f"{SUPABASE_URL}/auth/v1/verify"
        try:
            r = requests.post(
                url,
                headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
            if debug:
                st.info(f"/verify → {r.status_code} | {r.text[:300]}")
            if r.status_code // 100 == 2 and "application/json" in r.headers.get("content-type",""):
                return (r.json() or {}).get("access_token")
        except Exception as e:
            if debug: st.warning(f"/verify exception: {e}")
        return None

    if btn:
        if not email or not (token_hash or token_code):
            st.error("Reset failed. The link may be invalid or expired. Please request a new reset link.")
            st.stop()
        if pw1 != pw2:
            st.error("Passwords must match.")
            st.stop()

        access_token = None

        # 1) Zuerst HASH versuchen (benötigt KEINE E-Mail)
        if token_hash:
            access_token = verify_with({"type": "recovery", "token_hash": token_hash})

        # 2) Falls kein Erfolg: CODE versuchen (hier E-Mail MITGEBEN!)
        if not access_token and token_code:
            access_token = verify_with({"type": "recovery", "email": email, "token": token_code})

        if not access_token:
            st.error("Reset failed. The link may be invalid or expired. Please request a new reset link.")
            st.stop()

        # 3) Passwort setzen
        try:
            r = requests.put(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"password": pw1},
                timeout=20,
            )
            if debug:
                st.info(f"/user → {r.status_code} | {r.text[:300]}")
        except Exception as e:
            if debug: st.warning(f"/user exception: {e}")
            st.error("Could not set password. Please request a new reset link and try again.")
            st.stop()

        if r.status_code // 100 == 2:
            st.success("Password updated. You can now log in.")
            st.markdown("[Back to login](/?view=login)")
            st.stop()
        else:
            st.error("Could not set password. Please request a new reset link and try again.")

# === Registration ===
if view == "register":
    st.markdown("""
    <style>
    .register-card {
        background: none !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0;
        margin: 3rem auto 2rem auto;
        max-width: 370px;
        min-width: 270px;
        display: flex;
        flex-direction: column;
        align-items: center;
    }
    .register-card h2 {
        color:#0b2545;
        font-size:1.7em;
        font-weight:700;
        margin-bottom:1.2em;
        text-align:center;
    }
    .register-card .stTextInput>div>div>input {
        width: 120px !important;
    }
    .register-card .stButton>button {
        width:100%;
        font-size:1.1em;
        padding:0.5em 0;
        border-radius:8px;
        margin-top:1.2em;
    }
    .terms-checkbox * {
        color: #000000 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    cols = st.columns([2, 1, 2])
    with cols[1]:
        st.markdown('<div class="register-card">', unsafe_allow_html=True)
        st.markdown('<h2>Register</h2>', unsafe_allow_html=True)

        email = st.text_input("Email", key="reg_email")
        pwd = st.text_input("Password", type="password", key="reg_pwd")
        pwd_confirm = st.text_input("Confirm Password", type="password", key="reg_pwd_confirm")

        st.markdown('<div class="terms-checkbox">', unsafe_allow_html=True)
        agb = st.checkbox("I accept the Terms and Conditions", key="reg_agb")
        st.markdown('</div>', unsafe_allow_html=True)

        if st.button("Register"):
            if not agb:
                st.error("You must accept the terms to register.")
            elif pwd != pwd_confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    # Prüfen, ob E-Mail schon existiert
                    existing_user = supabase.table("users").select("*").eq("email", email).execute()
                    if existing_user.data and len(existing_user.data) > 0:
                        st.error("This email is already registered.")
                    else:
                        # Passwort-Hash
                        pwd_hash = hashlib.sha256(pwd.encode()).hexdigest()

                        # Nutzer in Supabase speichern (mit [data] Fix)
                        data = {
                            "email": email,
                            "pwd": pwd_hash,
                            "subscription_active": False
                        }
                        result = supabase.table("users").insert([data]).execute()

                        if result.data:
                            SESSION.logged_in = True
                            SESSION.username = email
                            SESSION.user_plan = "free"

                            st.success("Your account has been successfully created!")

                            # Stripe Button anzeigen
                            stripe_url = "https://buy.stripe.com/eVq14m88aagx4ah3hNbAs01"
                            st.markdown(
                                f"""
                                <div style='margin-top: 1.5rem; text-align: center;'>
                                    <a href="{stripe_url}" target="_blank">
                                        <button style='padding: 0.6em 1.2em; font-size: 1.1em; border-radius: 8px; background-color: #635bff; color: white; border: none; cursor: pointer;'>
                                            Start 14-day free trial now!
                                        </button>
                                    </a>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                            st.stop()
                        else:
                            st.error("Unknown error: User could not be inserted into Supabase.")

                except Exception as e:
                    st.error(f"Registration failed: {e}")

        st.markdown('</div>', unsafe_allow_html=True)

# === Stripe-Testphase-Platzhalterseite ===

if view == "abo_starten":
    st.header(f"{get_text('start_trial')}!")
    st.info("Hier würde der Stripe-Checkout für die Testphase eingebunden werden.")
    st.markdown(f"<a href='/?view=news' class='button'>{get_text('continue_later')}</a>", unsafe_allow_html=True)
    st.stop()

# === Protected News-Startseite ===
# if not SESSION.logged_in or SESSION.user_plan != "paid":
#     st.warning("Zugang nur für zahlende Abonnenten.")
#     st.stop()

# === Translation Functions ===

def translate_text(text, target_lang):
    """Comprehensive German to English translation function"""
    if target_lang == "en" and text and text != '-':
        # Check if text is already in English (contains common English words)
        english_indicators = ['the', 'and', 'is', 'are', 'was', 'were', 'will', 'would', 'could', 'should', 'market', 'analysis', 'forecast']
        text_lower = text.lower()
        if any(word in text_lower for word in english_indicators):
            return text  # Already in English
        
        # Comprehensive German to English translation patterns
        translations = {
            # Complete sentence patterns
            "Die Prognose von Morgan Stanley, dass der S&P 500 wahrscheinlicher auf 7.200 Punkte im nächsten Jahr steigen wird, basiert auf zwei Hauptfaktoren: bessere Gewinne und ein stetig hohes KGV.": "Morgan Stanley's forecast that the S&P 500 is more likely to reach 7,200 points next year is based on two main factors: better earnings and a consistently high P/E ratio.",
            
            "Die Analyse von Citrini Research weist auf eine starke Korrelation zwischen den aktuellen Marktbedingungen und denen des Jahres 1998 hin.": "Citrini Research's analysis points to a strong correlation between current market conditions and those of 1998.",
            
            "Die Nachricht fällt unter die Kategorie 'Finanzen', da sie sich auf persönliche Finanzen, Altersvorsorge und Versicherung bezieht.": "The news falls under the 'Finance' category as it relates to personal finance, retirement planning, and insurance.",
            
            "Die bevorstehende Pressekonferenz von Powell wird als entscheidend angesehen, da er unter erheblichem Druck steht.": "Powell's upcoming press conference is considered crucial as he is under significant pressure.",
            
            # Common German sentence starters
            "Die Prognose": "The forecast",
            "Die Analyse": "The analysis",
            "Die Nachricht": "The news",
            "Die Entscheidung": "The decision",
            "Die Ankündigung": "The announcement",
            "Diese Nachricht": "This news",
            "Dieser Vorfall": "This incident",
            "Diese Ankündigung": "This announcement",
            "Diese Entwicklung": "This development",
            "Dieses Ereignis": "This event",
            "Diese Situation": "This situation",
            
            # Verbs and actions
            "basiert auf": "is based on",
            "deutet darauf hin": "indicates",
            "weist auf": "points to",
            "führt zu": "leads to",
            "hat zur Folge": "results in",
            "könnte dazu führen": "could lead to",
            "wird erwartet": "is expected",
            "wird angenommen": "is assumed",
            "wird geschätzt": "is estimated",
            "zeigt sich": "shows",
            "ergibt sich": "results",
            "stellt dar": "represents",
            "bedeutet dies": "this means",
            "lässt sich": "can be",
            "ist zu erwarten": "is to be expected",
            "sollte beachtet werden": "should be noted",
            "ist wichtig zu beachten": "it is important to note",
            "es ist jedoch wichtig zu beachten": "however, it is important to note",
            
            # Modal verbs
            "könnte": "could",
            "würde": "would",
            "sollte": "should",
            "müsste": "would have to",
            "dürfte": "is likely to",
            "kann": "can",
            "mag": "may",
            "wird": "will",
            "soll": "shall",
            
            # Common verbs
            "bedeutet": "means",
            "zeigt": "shows",
            "beeinflusst": "influences",
            "betrifft": "affects",
            "verursacht": "causes",
            "ermöglicht": "enables",
            "verhindert": "prevents",
            "unterstützt": "supports",
            "gefährdet": "endangers",
            "verstärkt": "strengthens",
            "schwächt": "weakens",
            
            # Financial and market terms
            "Märkte": "markets",
            "Aktienmarkt": "stock market",
            "Finanzmärkte": "financial markets",
            "Kapitalmärkte": "capital markets",
            "Unternehmen": "companies",
            "Investoren": "investors",
            "Anleger": "investors",
            "Wirtschaft": "economy",
            "Handel": "trade",
            "Handelsabkommen": "trade agreement",
            "Handelsbeziehungen": "trade relations",
            "Zölle": "tariffs",
            "Zollsätze": "tariff rates",
            "Auswirkungen": "effects",
            "Marktauswirkungen": "market effects",
            "Einfluss": "influence",
            "Markteinfluss": "market influence",
            "Entwicklung": "development",
            "Marktentwicklung": "market development",
            "Situation": "situation",
            "Marktsituation": "market situation",
            "Ereignis": "event",
            "Marktereignis": "market event",
            "Faktoren": "factors",
            "Marktfaktoren": "market factors",
            "Risiken": "risks",
            "Marktrisiken": "market risks",
            "Chancen": "opportunities",
            "Marktchancen": "market opportunities",
            "Prognose": "forecast",
            "Marktprognose": "market forecast",
            "Erwartungen": "expectations",
            "Markterwartungen": "market expectations",
            "Vertrauen": "confidence",
            "Marktvertrauen": "market confidence",
            "Unsicherheit": "uncertainty",
            "Marktunsicherheit": "market uncertainty",
            "Volatilität": "volatility",
            "Marktvolatilität": "market volatility",
            "Wachstum": "growth",
            "Wirtschaftswachstum": "economic growth",
            "Rückgang": "decline",
            "Marktrückgang": "market decline",
            "Steigerung": "increase",
            "Verbesserung": "improvement",
            "Verschlechterung": "deterioration",
            
            # Time and temporal expressions
            "in der Vergangenheit": "in the past",
            "in Zukunft": "in the future",
            "derzeit": "currently",
            "gegenwärtig": "currently",
            "zukünftig": "in the future",
            "künftig": "in the future",
            "bisher": "so far",
            "bereits": "already",
            "noch": "still",
            "weiterhin": "continue to",
            "nach wie vor": "still",
            
            # Conjunctions and connectors
            "jedoch": "however",
            "allerdings": "however",
            "dennoch": "nevertheless",
            "trotzdem": "nevertheless",
            "daher": "therefore",
            "deshalb": "therefore",
            "folglich": "consequently",
            "somit": "thus",
            "außerdem": "furthermore",
            "darüber hinaus": "furthermore",
            "zusätzlich": "additionally",
            "ebenso": "likewise",
            "gleichzeitig": "simultaneously",
            "währenddessen": "meanwhile",
            "andererseits": "on the other hand",
            "hingegen": "on the other hand",
            
            # Adjectives and descriptors
            "erheblich": "significant",
            "beträchtlich": "considerable",
            "wesentlich": "substantial",
            "wichtig": "important",
            "entscheidend": "crucial",
            "kritisch": "critical",
            "positiv": "positive",
            "negativ": "negative",
            "stark": "strong",
            "schwach": "weak",
            "hoch": "high",
            "niedrig": "low",
            "groß": "large",
            "klein": "small",
            "schnell": "fast",
            "langsam": "slow",
            "neu": "new",
            "alt": "old",
            "aktuell": "current",
            "zukünftig": "future",
            "vergangen": "past",
            
            # Common phrases
            "auf Basis": "based on",
            "aufgrund": "due to",
            "wegen": "because of",
            "infolge": "as a result of",
            "im Hinblick auf": "with regard to",
            "in Bezug auf": "in relation to",
            "hinsichtlich": "regarding",
            "bezüglich": "regarding",
            "im Vergleich zu": "compared to",
            "gegenüber": "compared to",
            "im Gegensatz zu": "in contrast to",
            "anstatt": "instead of",
            "statt": "instead of",
            "sowie": "as well as",
            "sowohl": "both",
            "entweder": "either",
            "weder": "neither",
        }
        
        # Apply translations in order of length (longest first to avoid partial replacements)
        translated = text
        for german_phrase in sorted(translations.keys(), key=len, reverse=True):
            if german_phrase in translated:
                translated = translated.replace(german_phrase, translations[german_phrase])
        
        return translated
    else:
        return text

# === News-Startseite (nur für zahlende Nutzer) ===
if view in ["news", "Alle Nachrichten"]:
    # Zugriff nur für eingeloggte und zahlende Nutzer
    if not SESSION.logged_in or SESSION.user_plan != "paid":
        st.warning("Access denied. You must start the free trial to access the News Analysis.")
        
        stripe_url = "https://buy.stripe.com/eVq14m88aagx4ah3hNbAs01"  # Dein Stripe-Link
        st.markdown(
            f"""
            <div style='margin-top: 1.5rem; text-align: center;'>
                <a href="{stripe_url}" target="_blank">
                    <button style='padding: 0.6em 1.2em; font-size: 1.1em; border-radius: 8px; background-color: #635bff; color: white; border: none; cursor: pointer;'>
                        Start 14-day free Trial to get access
                    </button>
                </a>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.stop()

    st.markdown("<style>.block-container {padding-top: 0.5rem !important;}</style>", unsafe_allow_html=True)

    # --- Linke Spalte: Dashboard ---
    left_col, mid_col = st.columns([1,2])
    with left_col:
        st.markdown('<div class="content-col">', unsafe_allow_html=True)
        
        # --- Benutzer-Einstellungen Header ---
        st.markdown(f"""
        <div style='background:#0b2545; color:#fff; border-radius:14px; height:48px; display:flex; align-items:center; justify-content:center; font-size:1.15em; font-weight:700; margin-bottom:0; margin-top:0.5em; box-shadow:0 2px 8px rgba(11,37,69,0.08); letter-spacing:0.5px;'>
            {get_text('user_settings')}
        </div>
        """, unsafe_allow_html=True)
        
        # --- Benutzer-Dashboard ---
        st.markdown("""
        <style>
        .user-dashboard {
            background: transparent !important;
            color: #0b2545;
            border-radius: 0 !important;
            padding: 0 1.5rem 1.5rem 1.5rem;
            margin-top: 0 !important;
            margin-bottom: 2.5rem;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            box-shadow: none !important;
        }
        .user-dashboard h3:first-child {
            margin-top: 0 !important;
        }
        .dashboard-section-box {
            background: #fff;
            color: #0b2545;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(11,37,69,0.08);
            padding: 1.2em 1em 1.2em 1em;
            margin-bottom: 1.5em;
        }
        .dashboard-section-box h3 {
            color: #0b2545;
            font-size: 1.15em;
            font-weight: 700;
            margin-bottom: 0.7em;
            margin-top: 0;
        }
        .user-dashboard label, .user-dashboard .stTextInput label {
            color: #0b2545 !important;
            font-weight: 600;
        }
        .user-dashboard .stTextInput>div>div>input, .user-dashboard textarea {
            background: #fff !important;
            color: #0b2545 !important;
            border: 2px solid #0b2545 !important;
            border-radius: 8px !important;
        }
        .user-dashboard .stButton>button {
            background: #0b2545 !important;
            color: #fff !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 700 !important;
            margin-top: 0.7em;
            margin-bottom: 0.7em;
        }
        .user-dashboard .abo-status {
            font-size: 1.1em;
            font-weight: 600;
            margin-bottom: 0.5em;
        }
        .user-dashboard .abo-status.active {
            color: #1a7f3c;
        }
        .user-dashboard .abo-status.cancelled {
            color: #b80000;
        }
        .user-dashboard .abo-status.trial {
            color: #bfa100;
        }
        </style>
        """, unsafe_allow_html=True)

        st.markdown('<div class="user-dashboard">', unsafe_allow_html=True)

        # --- PROFIL ---
        st.markdown(f'<h3>{get_text("profile")}</h3>', unsafe_allow_html=True)
        user_email = st.session_state.get("username", "Unbekannt")
        st.write(f"**E-Mail:** {user_email}")
        
        with st.expander(get_text("change_password")):
            pwd1 = st.text_input(get_text("password"), type="password", key="dash_pwd1")
            pwd2 = st.text_input(get_text("confirm_password"), type="password", key="dash_pwd2")
            if st.button(get_text("save_password_dash"), key="dash_pwd_btn"):
                if pwd1 != pwd2:
                    st.error(get_text("passwords_dont_match"))
                elif len(pwd1) < 6:
                    st.error(get_text("password_too_short"))
                else:
                    users = json.loads(USER_FILE.read_text())
                    users[user_email] = hashlib.sha256(pwd1.encode()).hexdigest()
                    save_users(users)
                    st.success(get_text("password_saved"))
        
        st.markdown("<hr style='margin:1.5em 0; border: none; border-top: 1.5px solid #e6f0fa;'>", unsafe_allow_html=True)

        # --- ABONNEMENT / SUBSCRIPTION ---
        st.markdown(f'<h3>{get_text("subscription")}</h3>', unsafe_allow_html=True)

        active = bool(st.session_state.get("subscription_active", False))
        status_text = get_text("active") if active else get_text("cancelled")
        status_class = "active" if active else "cancelled"
        st.markdown(
            f'<div class="abo-status {status_class}">{get_text("status")} {status_text}</div>',
            unsafe_allow_html=True
        ) 

        # --- Manage subscription (Stripe Billing Portal) ---
        RENDER_API_BASE = (
            (st.secrets.get("RENDER_API_BASE") if hasattr(st, "secrets") else None)
            or os.getenv("RENDER_API_BASE")
            or "https://insightfundamental1-webhook-automation.onrender.com"
        ).rstrip("/")

        app_email = (st.session_state.get("username") or "").strip().lower()
        portal_link = f"{RENDER_API_BASE}/portal?email={quote(app_email)}"

        col1, col2 = st.columns([1, 1])

        with col1:
            if st.button("Manage subscription", key="dash_manage_sub"):
                if not app_email:
                    st.error("No email in session.")
                else:
                    # Stripe-Portal in neuem Tab öffnen
                    components.html(f"<script>window.open('{portal_link}', '_blank');</script>", height=0)

        with col2:
            if st.button("Refresh access", key="dash_refresh_access"):
                refresh_subscription_status()
                st.rerun()

        st.markdown("<hr style='margin:1.5em 0; border: none; border-top: 1.5px solid #e6f0fa;'>", unsafe_allow_html=True)

        # --- SUPPORT ---
        st.markdown(f'<h3>{get_text("support")}</h3>', unsafe_allow_html=True)
        with st.form("support_form"):
            subject = st.text_input(get_text("subject"), key="support_subject")
            message = st.text_area(get_text("message"), key="support_message")
            submitted = st.form_submit_button(get_text("send"))
            if submitted:
                if not subject or not message:
                    st.error(get_text("fill_all_fields"))
                else:
                    st.success(get_text("message_sent"))
        
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Mittlere Spalte: News Cards ---
    with mid_col:
        st.markdown('<div class="content-col">', unsafe_allow_html=True)
        
        data_file = Path("data/news_analysis_results.csv")
        df = pd.read_csv(data_file) if data_file.exists() else pd.DataFrame()
       
        # Sortiere nach Datum, neueste zuerst
        if not df.empty and "publishedAt" in df.columns:
            df["publishedAt"] = pd.to_datetime(df["publishedAt"], errors="coerce")
            df = df.sort_values(by="publishedAt", ascending=False)
        
        # Mapping für deutsche zu englischen Confidence-Werten
        confidence_map = {"hoch": "high", "mittel": "medium", "niedrig": "low"}
        if "confidence" in df.columns:
            df["confidence"] = df["confidence"].replace(confidence_map)
        
        if df.empty:
            st.info("No news available.")
        else:
            df["publishedAt"] = pd.to_datetime(df["publishedAt"], errors="coerce")
            
            # Remove duplicate news items based on title and publishedAt
            df = df.drop_duplicates(subset=['title', 'publishedAt'], keep='first')
            
            st.markdown("""
            <style>
            .news-card {
                background:#fff; 
                border:2px solid #e6f0fa; 
                border-radius:18px; 
                box-shadow:0 4px 18px rgba(11,37,69,0.07); 
                padding:2rem 1.5rem 1.2rem 1.5rem; 
                margin:2.2rem 0; 
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                position: relative;
                overflow: hidden;
            }
            .news-card::before {
                content: '';
                position: absolute;
                top: 0;
                left: -100%;
                width: 100%;
                height: 100%;
                background: linear-gradient(90deg, transparent, rgba(11,37,69,0.03), transparent);
                transition: left 0.6s;
            }
            .news-card:hover::before {
                left: 100%;
            }
            .news-card:hover {
                box-shadow:0 12px 40px rgba(11,37,69,0.15); 
                transform:translateY(-6px) scale(1.02);
                border-color: #0b2545;
            }
            .news-card:active {
                transform:translateY(-2px) scale(1.01);
                transition: all 0.1s ease;
            }
            .badge {
                display:inline-block; 
                border-radius:12px; 
                padding:0.2em 0.9em; 
                font-size:1em; 
                font-weight:600; 
                margin-right:0.5em; 
                margin-bottom:0.3em;
            }
            .impact-badge {
                background:#e6f0fa; 
                color:#0b2545;
            }
            .impact-badge.high {
                background:#d1f5e0; 
                color:#1a7f3c;
            }
            .impact-badge.mid {
                background:#fff7d6; 
                color:#bfa100;
            }
            .impact-badge.low {
                background:#ffe0e0; 
                color:#b80000;
            }
            .confidence-badge {
                background:#e6f0fa; 
                color:#0b2545;
            }
            .confidence-badge.high {
                background:#d1f5e0; 
                color:#1a7f3c;
            }
            .confidence-badge.mid {
                background:#fff7d6; 
                color:#bfa100;
            }
            .confidence-badge.low {
                background:#ffe0e0; 
                color:#b80000;
            }
            .market-chip {
                background:#f0f4fa; 
                color:#0b2545; 
                border-radius:10px; 
                padding:0.2em 0.8em; 
                font-size:0.98em; 
                margin-right:0.4em; 
                margin-bottom:0.2em; 
                display:inline-block;
            }
            .news-title {
                font-size:1.35em; 
                font-weight:700; 
                color:#0b2545; 
                margin-bottom:0.2em;
            }
            .news-date {
                color:#888; 
                font-size:0.98em; 
                margin-bottom:0.7em;
            }
            .news-summary {
                margin:0.7em 0 1.1em 0; 
                color:#222;
            }
            .news-divider {
                margin:1.5em 0 0.5em 0; 
                border:none; 
                border-top:1px solid #e6f0fa;
            }
            .news-btn {
                background:#0b2545; 
                color:#fff; 
                border:none; 
                border-radius:8px; 
                padding:0.5em 1.2em; 
                font-weight:600; 
                font-size:1em; 
                margin-top:0.7em; 
                transition:background 0.2s; 
                cursor:pointer;
            }
            .news-btn:hover {
                background:#1b325c;
            }
            </style>
            """, unsafe_allow_html=True)
            
            # Display all news without filtering
            for _, r in df.iterrows():
                
                # Get impact and confidence values
                impact = r.get('impact', '-')
                confidence = str(r.get('confidence', '-') or '').lower()
                
                # Impact Score Badge Farbe
                try:
                    if impact is not None and impact != '-' and impact != '':
                        impact_val = float(impact)
                        if impact_val >= 4:
                            impact_class = 'high'
                        elif impact_val <= -4:
                            impact_class = 'low'
                        else:
                            impact_class = 'mid'
                    else:
                        impact_class = ''
                except Exception:
                    impact_class = ''
                
                # Confidence Badge Farbe
                if 'high' in confidence:
                    conf_class = 'high'
                elif 'medium' in confidence:
                    conf_class = 'mid'
                elif 'low' in confidence:
                    conf_class = 'low'
                else:
                    conf_class = ''
                
                # Märkte Chips
                markets = r.get('markets','-')
                if isinstance(markets, str):
                    # Versuche, die Liste aus dem String zu extrahieren
                    if markets.startswith('[') and markets.endswith(']'):
                        import ast
                        try:
                            market_list = ast.literal_eval(markets)
                        except Exception:
                            market_list = [m.strip() for m in markets.split(',') if m.strip()]
                    else:
                        market_list = [m.strip() for m in markets.split(',') if m.strip()]
                else:
                    market_list = []
                
                # Datum robust formatieren
                published_at = r.get('publishedAt', None)
                date_str = ''
                if published_at is not None:
                    try:
                        if hasattr(published_at, 'strftime'):
                            date_str = published_at.strftime('%d.%m.%Y %H:%M')
                        elif isinstance(published_at, (list, tuple, np.ndarray)):
                            date_str = pd.to_datetime(published_at[0]).strftime('%d.%m.%Y %H:%M')
                        elif isinstance(published_at, pd.Series):
                            date_str = pd.to_datetime(published_at.iloc[0]).strftime('%d.%m.%Y %H:%M')
                        else:
                            date_str = pd.to_datetime(published_at).strftime('%d.%m.%Y %H:%M')
                    except Exception:
                        date_str = ''
                
                # Card-Layout (alles englisch)
                confidence_val = r.get('confidence', '-')
                confidence_str = str(confidence_val) if confidence_val is not None else '-'
                title_val = r.get('title', '') if 'title' in r else ''
                description_val = r.get('description', '') if 'description' in r else ''
                
                # Ensure patterns and explanation content is in English
                patterns_val = r.get('patterns', '-') if 'patterns' in r else '-'
                explanation_val = r.get('explanation', '-') if 'explanation' in r else '-'
                
                # Force English display for patterns and explanation content
                if patterns_val and patterns_val != '-':
                    patterns_val = translate_text(str(patterns_val), "en")
                if explanation_val and explanation_val != '-':
                    explanation_val = translate_text(str(explanation_val), "en")
                
                st.markdown(f"""
                <div class='news-card'>
                    <div class='news-title'>{title_val}</div>
                    <div class='news-date'>{date_str}</div>
                    <div style='margin-bottom:0.7em;'>
                        <span class='badge impact-badge {impact_class}'>Impact Score: {impact}</span>
                        <span class='badge confidence-badge {conf_class}'>Confidence Level: {confidence_str.capitalize()}</span>
                        {''.join([f"<span class='market-chip'>{m}</span>" for m in market_list])}
                    </div>
                    <div class='news-summary'>{description_val}</div>
                    <details>
                        <summary style='font-weight:600; color:#0b2545; cursor:pointer;'>{get_text('learn_more')}</summary>
                        <div style='margin-top:1em;'>
                            <b>{get_text('historical_patterns_news')}</b> {patterns_val}<br>
                            <b>{get_text('analysis')}</b> {explanation_val}
                        </div>
                    </details>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Rechte Spalte: Filter (removed) ---
    # The right column filter section has been removed as it's no longer needed


#==== Footer (appears on all pages) ===
st.markdown("""
<style>
/* Footer Styling */
.website-footer {
    background: #0b2545;
    color: #fff;
    padding: 2rem 1rem;
    margin-top: 4rem;
    border-top: 3px solid #1b325c;
}

.footer-content {
    max-width: 1200px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1.5rem;
}

.footer-links {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 2rem;
    align-items: center;
}

.footer-links a {
    color: #fff;
    text-decoration: none;
    font-weight: 500;
    font-size: 0.95em;
    transition: all 0.3s ease;
    padding: 0.5rem 0;
}

.footer-links a:hover {
    color: #4a9eff;
    transform: translateY(-2px);
}

.footer-social {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.footer-social a {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: #fff;
    text-decoration: none;
    font-weight: 500;
    font-size: 0.95em;
    transition: all 0.3s ease;
    padding: 0.5rem;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.1);
}

.footer-social a:hover {
    color: #4a9eff;
    background: rgba(74, 158, 255, 0.2);
    transform: translateY(-2px);
}

.footer-divider {
    width: 100%;
    height: 1px;
    background: rgba(255, 255, 255, 0.2);
    margin: 0.5rem 0;
}

/* X (Twitter) Icon SVG */
.x-icon {
    width: 16px;
    height: 16px;
    fill: currentColor;
}

/* Responsive Design */
@media (max-width: 768px) {
    .footer-links {
        flex-direction: column;
        gap: 1rem;
        text-align: center;
    }
    
    .footer-content {
        gap: 1rem;
    }
    
    .website-footer {
        padding: 1.5rem 1rem;
        margin-top: 2rem;
    }
}
</style>

<footer class="website-footer">
    <div class="footer-content">
        <div class="footer-links">
            <a href="/?view=impressum">Impressum</a>
            <a href="/?view=datenschutz">Datenschutzerklärung</a>
            <a href="/?view=agb">AGB</a>
            <a href="/?view=nutzungsbedingungen">Nutzungsbedingungen</a>
            <a href="/?view=cookie-hinweis">Cookie-Hinweis</a>
        </div>
    </div>
</footer>
""", unsafe_allow_html=True)

# === Legal Document Pages ===

# Impressum Page
if view == "impressum":
    st.markdown("""
    <style>
    .stApp, .block-container, section[data-testid="stAppViewContainer"] > div:first-child {
        background: #fff !important;
    }
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a, .header-nav a.button {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        border: none !important;
        padding: 1rem 2rem !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    .legal-content {
        max-width: 800px;
        margin: 2rem auto;
        padding: 2rem;
        background: #fff;
        border: 2px solid #0b2545;
        border-radius: 16px;
        box-shadow: 0 4px 24px rgba(11,37,69,0.08);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif !important;
    }
    .legal-content h1 {
        color: #0b2545;
        font-size: 2.5em;
        margin-bottom: 2rem;
        text-align: center;
        font-family: inherit !important;
    }
    .legal-content h2 {
        color: #0b2545;
        font-size: 1.5em;
        margin: 2rem 0 1rem 0;
        font-family: inherit !important;
    }
    .legal-content p, .legal-content li {
        color: #111;
        line-height: 1.7;
        margin-bottom: 1rem;
        font-family: inherit !important;
        font-size: 1rem;
    }
    .legal-content strong {
        color: #0b2545;
        font-weight: 700;
        font-family: inherit !important;
    }
    .legal-content a {
        color: #0b2545;
        text-decoration: underline;
    }
    .legal-content a:hover {
        color: #1b325c;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Use native Streamlit components for better text rendering
    st.markdown("# Impressum", unsafe_allow_html=True)
    
    st.markdown("**Angaben gemäß § 5 TMG**", unsafe_allow_html=True)
    
    st.markdown("""
    **InsightFundamental**  
    Marvin Schlein  
    Hengstbachstraße 19  
    63303 Dreieich  
    Deutschland
    """, unsafe_allow_html=True)
    
    st.markdown("""
    **Kontakt:**  
    Telefon: +49 (0)175 7685390  
    E-Mail: support@insightfundamental.com  
    Website: [https://insightfundamental.com](https://insightfundamental.com)
    """, unsafe_allow_html=True)
    
    st.markdown("""
    **Verantwortlich für den Inhalt nach § 55 Abs. 2 RStV:**  
    Marvin Schlein  
    Anschrift wie oben
    """, unsafe_allow_html=True)
    
    st.markdown("""
    **Hinweis:**  
    Als Einzelunternehmer bin ich aktuell nicht im Handelsregister eingetragen. Eine Umsatzsteuer-ID liegt derzeit nicht vor.
    """, unsafe_allow_html=True)
    
    st.markdown("""
    **Online-Streitbeilegung gemäß Art. 14 Abs. 1 ODR-VO:**  
    Die Europäische Kommission stellt eine Plattform zur Online-Streitbeilegung (OS) bereit:  
    [https://ec.europa.eu/consumers/odr/](https://ec.europa.eu/consumers/odr/)
    """, unsafe_allow_html=True)
    
    st.markdown("Ich bin nicht verpflichtet oder bereit, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.", unsafe_allow_html=True)

# Datenschutzerklärung Page
if view == "datenschutz":
    st.markdown("""
    <style>
    .stApp, .block-container, section[data-testid="stAppViewContainer"] > div:first-child {
        background: #fff !important;
    }
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a, .header-nav a.button {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        border: none !important;
        padding: 1rem 2rem !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Use native Streamlit components for better text rendering
    st.markdown("# Datenschutzerklärung", unsafe_allow_html=True)
    
    st.markdown("## 1. Verantwortlicher", unsafe_allow_html=True)
    st.markdown("""
    **Marvin Schlein**  
    InsightFundamental  
    Hengstbachstraße 19  
    63303 Dreieich  
    Deutschland  
    E-Mail: support@insightfundamental.com
    """, unsafe_allow_html=True)
    
    st.markdown("## 2. Allgemeine Hinweise zur Datenverarbeitung", unsafe_allow_html=True)
    st.markdown("Der Schutz Ihrer persönlichen Daten ist mir ein besonderes Anliegen. Ich verarbeite Ihre Daten daher ausschließlich auf Grundlage der gesetzlichen Bestimmungen (DSGVO, TMG, BDSG). In dieser Datenschutzerklärung informiere ich Sie über die wichtigsten Aspekte der Datenverarbeitung im Rahmen meiner Web App 'InsightFundamental'.", unsafe_allow_html=True)
    
    st.markdown("## 3. Erhebung und Verarbeitung personenbezogener Daten", unsafe_allow_html=True)
    st.markdown("Ich verarbeite folgende personenbezogene Daten:", unsafe_allow_html=True)
    st.markdown("""
    - E-Mail-Adresse
    - Passwort (verschlüsselt gespeichert)
    - Zahlungsdaten (via Stripe)
    """, unsafe_allow_html=True)
    st.markdown("Zweck: Vertragserfüllung gemäß Art. 6 Abs. 1 lit. b DSGVO.", unsafe_allow_html=True)
    
    st.markdown("## 4. Zahlungsabwicklung via Stripe", unsafe_allow_html=True)
    st.markdown("Zur Zahlungsabwicklung nutze ich Stripe. Die Datenschutzerklärung von Stripe:  \n[https://stripe.com/de/privacy](https://stripe.com/de/privacy)", unsafe_allow_html=True)
    
    st.markdown("## 5. Hosting", unsafe_allow_html=True)
    st.markdown("Gehostet wird über Streamlit Community Cloud (Snowflake Inc.).", unsafe_allow_html=True)
    
    st.markdown("## 6. OpenAI API & Finnhub.io", unsafe_allow_html=True)
    st.markdown("Externe APIs für Analyse und Nachrichtenbereitstellung. Es werden keine personenbezogenen Daten an diese Dienste übertragen.", unsafe_allow_html=True)
    
    st.markdown("## 7. Speicherdauer", unsafe_allow_html=True)
    st.markdown("Nur solange erforderlich bzw. gesetzlich vorgeschrieben.", unsafe_allow_html=True)
    
    st.markdown("## 8. Betroffenenrechte", unsafe_allow_html=True)
    st.markdown("Recht auf Auskunft, Berichtigung, Löschung, Einschränkung, Datenübertragbarkeit und Widerspruch.", unsafe_allow_html=True)
    
    st.markdown("## 9. Widerruf", unsafe_allow_html=True)
    st.markdown("Einwilligungen können jederzeit widerrufen werden.", unsafe_allow_html=True)
    
    st.markdown("## 10. Beschwerderecht", unsafe_allow_html=True)
    st.markdown("Bei der zuständigen Datenschutzaufsichtsbehörde.", unsafe_allow_html=True)
    
    st.markdown("## 11. Sicherheit", unsafe_allow_html=True)
    st.markdown("HTTPS, verschlüsselte Passwörter, Zugriffskontrolle.", unsafe_allow_html=True)
    
    st.markdown("## 12. Änderungen", unsafe_allow_html=True)
    st.markdown("Diese Datenschutzerklärung kann bei rechtlichen oder technischen Änderungen angepasst werden.", unsafe_allow_html=True)

# AGB Page
if view == "agb":
    st.markdown("""
    <style>
    .stApp, .block-container, section[data-testid="stAppViewContainer"] > div:first-child {
        background: #fff !important;
    }
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a, .header-nav a.button {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        border: none !important;
        padding: 1rem 2rem !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Use native Streamlit components for better text rendering
    st.markdown("# Allgemeine Geschäftsbedingungen (AGB)", unsafe_allow_html=True)
    
    st.markdown("## 1. Geltungsbereich", unsafe_allow_html=True)
    st.markdown("Diese AGB gelten für alle Verträge zwischen Marvin Schlein (InsightFundamental) und den Nutzern der Web App 'InsightFundamental'.", unsafe_allow_html=True)
    
    st.markdown("## 2. Leistungen", unsafe_allow_html=True)
    st.markdown("Bereitstellung einer SaaS-Plattform zur Analyse von Wirtschaftsnachrichten.", unsafe_allow_html=True)
    
    st.markdown("## 3. Registrierung und Vertragsschluss", unsafe_allow_html=True)
    st.markdown("Erfordert Registrierung und Zustimmung zu diesen AGB. Vertrag kommt mit Abschluss der Registrierung zustande.", unsafe_allow_html=True)
    
    st.markdown("## 4. Preise und Zahlungsabwicklung", unsafe_allow_html=True)
    st.markdown("19,99 €/Monat. Abwicklung über Stripe. Es gelten deren Bedingungen.", unsafe_allow_html=True)
    
    st.markdown("## 5. Testphase", unsafe_allow_html=True)
    st.markdown("14 Tage kostenlos. Danach automatische Umstellung auf kostenpflichtig, sofern nicht gekündigt.", unsafe_allow_html=True)
    
    st.markdown("## 6. Kündigung", unsafe_allow_html=True)
    st.markdown("Jederzeit zum Laufzeitende kündbar. Keine Rückerstattung.", unsafe_allow_html=True)
    
    st.markdown("## 7. Verfügbarkeit", unsafe_allow_html=True)
    st.markdown("Keine Garantie für permanente Verfügbarkeit. Wartungsarbeiten oder Störungen möglich.", unsafe_allow_html=True)
    
    st.markdown("## 8. Nutzungsrechte", unsafe_allow_html=True)
    st.markdown("Einfaches, nicht übertragbares Nutzungsrecht. Keine Weitergabe der Inhalte erlaubt.", unsafe_allow_html=True)
    
    st.markdown("## 9. Haftung", unsafe_allow_html=True)
    st.markdown("Haftung nur für Vorsatz und grobe Fahrlässigkeit.", unsafe_allow_html=True)
    
    st.markdown("## 10. Änderungen", unsafe_allow_html=True)
    st.markdown("Änderungen der AGB sind möglich. Nutzer werden informiert.", unsafe_allow_html=True)
    
    st.markdown("## 11. Schlussbestimmungen", unsafe_allow_html=True)
    st.markdown("Es gilt deutsches Recht. Gerichtsstand ist der Sitz des Anbieters.", unsafe_allow_html=True)

# Nutzungsbedingungen Page
if view == "nutzungsbedingungen":
    st.markdown("""
    <style>
    .stApp, .block-container, section[data-testid="stAppViewContainer"] > div:first-child {
        background: #fff !important;
    }
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a, .header-nav a.button {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        border: none !important;
        padding: 1rem 2rem !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Use native Streamlit components for better text rendering
    st.markdown("# Nutzungsbedingungen", unsafe_allow_html=True)
    
    st.markdown("## 1. Registrierung", unsafe_allow_html=True)
    st.markdown("Erfordert Erstellung eines Kontos mit wahrheitsgemäßen Angaben.", unsafe_allow_html=True)
    
    st.markdown("## 2. Zugangsdaten", unsafe_allow_html=True)
    st.markdown("Vertraulich behandeln. Keine Haftung bei Missbrauch durch Dritte.", unsafe_allow_html=True)
    
    st.markdown("## 3. Nutzung der Inhalte", unsafe_allow_html=True)
    st.markdown("Nur für persönliche, nicht-kommerzielle Nutzung erlaubt.", unsafe_allow_html=True)
    
    st.markdown("## 4. Verfügbarkeit", unsafe_allow_html=True)
    st.markdown("Keine Garantie auf ständige Verfügbarkeit.", unsafe_allow_html=True)
    
    st.markdown("## 5. Änderungen", unsafe_allow_html=True)
    st.markdown("Funktionen können angepasst werden, wenn zumutbar.", unsafe_allow_html=True)
    
    st.markdown("## 6. Ausschluss von Nutzern", unsafe_allow_html=True)
    st.markdown("Bei Verstößen kann Zugang gesperrt werden.", unsafe_allow_html=True)
    
    st.markdown("## 7. Haftung", unsafe_allow_html=True)
    st.markdown("Keine Finanzberatung. Keine Haftung für Entscheidungen auf Basis der Inhalte.", unsafe_allow_html=True)
    
    st.markdown("## 8. Gerichtsstand", unsafe_allow_html=True)
    st.markdown("Es gilt deutsches Recht. Gerichtsstand ist der Sitz des Anbieters.", unsafe_allow_html=True)

# Cookie-Hinweis Page
if view == "cookie-hinweis":
    st.markdown("""
    <style>
    .stApp, .block-container, section[data-testid="stAppViewContainer"] > div:first-child {
        background: #fff !important;
    }
    .header-nav {
        background: #fff !important;
        color: #0b2545 !important;
        box-shadow: none !important;
        border-radius: 0 !important;
    }
    .header-nav h1, .header-nav a, .header-nav a.button {
        color: #0b2545 !important;
        background: none !important;
    }
    .header-nav a.button {
        background: #0b2545 !important;
        color: #fff !important;
        border-radius: 25px !important;
        font-weight: 700;
        box-shadow: 0 4px 15px rgba(11,37,69,0.3) !important;
        border: none !important;
        padding: 1rem 2rem !important;
    }
    .header-nav a.button:hover {
        background: #1b325c !important;
        color: #fff !important;
        box-shadow: 0 6px 20px rgba(11,37,69,0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Use native Streamlit components for better text rendering
    st.markdown("# Cookie-Hinweis", unsafe_allow_html=True)
    
    st.markdown("Unsere Website verwendet derzeit **keine Cookies**, insbesondere keine Tracking- oder Analyse-Cookies.", unsafe_allow_html=True)
    
    st.markdown("Es werden keine Cookies auf Ihrem Gerät gespeichert oder ausgelesen, die eine Einwilligung nach § 25 Abs. 1 TTDSG erfordern würden.", unsafe_allow_html=True)
    
    st.markdown("Sollten sich künftig Änderungen ergeben (z. B. Einsatz von Analysetools), werden wir Sie rechtzeitig informieren und gegebenenfalls Ihre Zustimmung einholen.", unsafe_allow_html=True)
