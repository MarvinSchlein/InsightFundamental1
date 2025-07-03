import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import hashlib
import json
import yfinance as yf
import streamlit.components.v1 as components

# === Nachrichten laden GANZ OBEN! ===
data_file = Path("data/news_analysis_results.csv")
df = pd.read_csv(data_file) if data_file.exists() else pd.DataFrame()

st.set_page_config(page_title="InsightFundamental", layout="wide")

# === Nutzerverwaltung ===
USER_FILE = Path("data/users.json")
USER_FILE.parent.mkdir(parents=True, exist_ok=True)
if not USER_FILE.exists():
    USER_FILE.write_text(json.dumps({}))

SESSION = st.session_state
if "logged_in" not in SESSION:
    SESSION.logged_in = False
    SESSION.username = ""
if "dashboard_tab" not in SESSION:
    SESSION.dashboard_tab = "Profil"
if "user_plan" not in SESSION:
    SESSION.user_plan = "Standard"

def redirect_to(view: str):
    st.query_params = {"view": [view]}

def save_users(users: dict):
    USER_FILE.write_text(json.dumps(users))

# === CSS ===
st.markdown("""
    <style>
      html, body, .main, .block-container { background: #fff; color: #000; font-family: Georgia, serif; }
      h1, h2, h3 { color: #0b2545; margin: 0; }
      .timestamp { color: #555; font-size: .9em; }
      input[data-baseweb="input"], input[type="text"], input[type="password"] {
        background:#fff !important;
        border:2px solid #0b2545 !important;
        border-radius:6px;
        padding:8px 12px;
        font-size:16px;
        color:#000 !important;
        width:50% !important;   /* Größere Eingabefelder für alle gleich! */
        min-width: 300px !important;
      }
      section[data-testid="stSidebar"] input[data-baseweb="input"], 
      section[data-testid="stSidebar"] input[type="text"], 
      section[data-testid="stSidebar"] input[type="password"] {
        background:#0b2545 !important;
        border:2px solid #fff !important;
        border-radius:6px;
        color:#fff !important;
        width:98% !important;
        font-size:16px;
        padding:8px 12px;
      }
      section[data-testid="stSidebar"] label, 
      section[data-testid="stSidebar"] .stTextInput label {
        color: #fff !important;
      }
      .stTextInput > div,
      .stTextInput > div > div {
        background: #fff !important;
        border: none !important;
      }
      form label, .stTextInput label { color: #0b2545 !important; }
      ::placeholder { color:#0b2545 !important; opacity:1 !important; }
      .impact-bullish { color:green; font-weight:bold; }
      .impact-bearish { color:red; font-weight:bold; }
      .impact-neutral { color:black; font-weight:bold; }
      .market-box { border:2px solid #0b2545; border-radius:6px; padding:8px; text-align:center; }
      button, div.stButton > button, form button, input[type="submit"] {
        background-color: #0b2545 !important;
        color: white !important;
        border: none !important;
        border-radius: 4px !important;
        padding: 6px 12px !important;
        font-size: 16px !important;
        cursor: pointer !important;
        white-space: nowrap !important; /* EINZEILIG */
      }
      section[data-testid="stSidebar"] {
        background: #0b2445 !important;
        color: #fff !important;
      }
      .dashboard-btn {
        font-size:22px;
        font-weight:bold;
        color:#fff !important;
        padding:15px 22px;
        margin:6px 16px 6px 16px;
        border-radius:10px;
        background: transparent;
        cursor:pointer;
        border: none;
        text-align:left;
        transition: background 0.16s;
        outline: none !important;
        display: block;
        width: 100%;
      }
      .dashboard-btn.active {
        background: #1b325c;
        border-radius: 10px;
      }
      .current-tab {
        font-size: 26px;
        font-weight: bold;
        color: #fff !important;
        margin-bottom: 18px;
        text-align: center;
        letter-spacing:1px;
      }
    </style>
""", unsafe_allow_html=True)

# Header Button Style
st.markdown("""
    <style>
    .header-btn {
        background-color: #fff !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
        cursor: pointer;
        outline: none !important;
        display: inline-block;
    }
    .header-btn span {
        font-size:2.4em;
        font-weight:bold;
        color:#0b2545 !important;
        font-family:Georgia,serif;
        background-color: #fff !important;
        border: none !important;
        box-shadow: none !important;
        display: inline-block;
    }
    </style>
""", unsafe_allow_html=True)

# === Kopfzeile ===
c1, c2 = st.columns([6, 2])
with c1:
    col1, col2 = st.columns([6,1])
    with col1:
        button_html = """
        <form action="/" method="get" style="display:inline;">
            <button type="submit" class="header-btn"
                onmouseover="this.children[0].style.textDecoration='underline';"
                onmouseout="this.children[0].style.textDecoration='none';"
            >
                <span>InsightFundamental</span>
            </button>
        </form>
        """
        st.markdown(button_html, unsafe_allow_html=True)
    with col2:
        if SESSION.logged_in and SESSION.user_plan == "Standard":
            if st.button("PLUS", key="btn_plus", help="Vorteile ansehen"):
                redirect_to("abo")
with c2:
    if SESSION.logged_in:
        st.markdown(
            f"<div style='background:#0b2545;color:#fff;padding:6px 12px;border-radius:4px'>👤 {SESSION.username}</div>",
            unsafe_allow_html=True
        )
        # Abmelden-Button wurde HIER entfernt! (Siehe nächste Änderung im Dashboard)
    else:
        current_view = st.query_params.get("view", ["Alle Nachrichten"])[0]
        if current_view not in ["login", "register", "vorteile"]:
            btn_cols = st.columns([1.5, 0.18, 1.5, 0.3, 1.5])  # Abstand angepasst!
            with btn_cols[0]:
                if st.button("Vorteile", key="btn_vorteile", help="Erfahre mehr über die Vorteile von InsightFundamental"):
                    redirect_to("vorteile")
            with btn_cols[2]:
                if st.button("Anmelden", key="btn_login", help="Einloggen"):
                    redirect_to("login")
            with btn_cols[4]:
                if st.button("Registrieren", key="btn_reg", help="Konto erstellen"):
                    redirect_to("register")
        elif current_view == "vorteile":
            btn_cols = st.columns([1.5, 0.3, 1.5])
            with btn_cols[0]:
                if st.button("Anmelden", key="btn_login", help="Einloggen"):
                    redirect_to("login")
            with btn_cols[2]:
                if st.button("Registrieren", key="btn_reg", help="Konto erstellen"):
                    redirect_to("register")

st.markdown("<div style='margin-bottom:30px'></div>", unsafe_allow_html=True)

# === View auslesen ===
view = st.query_params.get("view", ["Alle Nachrichten"])[0]

# === Vorteile-Seite ===
if view == "vorteile":
    st.markdown("""
    <h2 style='color:#0b2545; margin-bottom:24px;'>Vorteile von InsightFundamental</h2>
    <div style="
        background: #f5f8fa;
        border: 2px solid #0b2545;
        border-radius: 12px;
        padding: 24px;
        max-width: 800px;
        margin: auto;
    ">
      <ul style="font-size:18px; line-height:1.6; margin:0;">
        <li>Top-aktuelle Wirtschafts-, Politik- und Finanznachrichten</li>
        <li>Automatische Erkennung von Markteinflüssen und Sentiment</li>
        <li>Praktische Suchfunktion für relevante News</li>
        <li>Favoriten & individuelles Dashboard nach Login</li>
        <li>Exklusive PLUS-Features wie Impact Score, Marktzuordnung & mehr</li>
      </ul>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# === Tägliche Marktveränderungen (nur wenn NICHT Login/Register) ===
if view == "Alle Nachrichten":
    symbols = {
        "DAX":"^GDAXI",
        "S&P 500":"^GSPC",
        "Nasdaq":"^IXIC",
        "Dow Jones":"^DJI",
        "EUR/USD":"EURUSD=X",
        "10Y US Treasury":"^TNX",
        "USD/JPY":"JPY=X"
    }
    market_data = {}
    market_prices = {}
    for name, sym in symbols.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2d")["Close"]
            price = hist.iloc[-1]
            pct = round((hist.iloc[-1] - hist.iloc[-2]) / hist.iloc[-2] * 100, 2)
            market_data[name] = pct
            if "EUR/USD" in name or "USD/JPY" in name:
                price_str = f"{price:.4f}"
            elif "10Y" in name:
                price_str = f"{price:.3f}"
            else:
                price_str = f"{price:,.2f}"
            market_prices[name] = price_str
        except Exception as e:
            market_data[name] = None
            market_prices[name] = "N/A"

    cols = st.columns(len(market_data))
    for i, (n, pct) in enumerate(market_data.items()):
        with cols[i]:
            html = f"<div class='market-box'><b>{n}</b>"
            html += f"<div style='font-size:18px;font-weight:bold;'>{market_prices[n]}</div>"
            if pct is not None:
                clr  = "green" if pct>0 else "red" if pct<0 else "black"
                sign = "+" if pct>0 else ""
                html += f"<div style='color:{clr}; font-size:18px'>{sign}{pct}%</div>"
            else:
                html += "<div style='color:gray; font-size:18px'>N/A</div>"
            html += "</div>"
            st.markdown(html, unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom:30px'></div>", unsafe_allow_html=True)

# === ABONNEMENT-SEITE ===
if view == "abo":
    # Überschrift
    st.markdown(
        "<h2 style='color:#0b2545; margin-bottom:32px;'>InsightFundamental Abo-Modelle</h2>",
        unsafe_allow_html=True
    )

    # Plan-Karten
    st.markdown("""
    <div style="display: flex; gap: 32px; flex-wrap: wrap;">
      <div style="flex:1; min-width:270px; max-width:360px; background:#f5f8fa; border-radius:18px; 
                  box-shadow:0 4px 18px #0b25451a; padding:32px 26px; border:2px solid #c3d0e6;">
        <h3 style="color:#0b2545;">Standard</h3>
        <div style="font-size:2em; font-weight:bold; margin:18px 0; color:#111;">Kostenlos</div>
        <ul style="color:#222; font-size:18px; line-height:1.55;">
          <li>Alle aktuellen Nachrichten</li>
        </ul>
      </div>
      <div style="flex:1; min-width:270px; max-width:360px; background:#fff; border-radius:18px; 
                  box-shadow:0 4px 24px #0b254533; padding:32px 26px; border:2.5px solid #0b2545; 
                  position:relative;">
        <span style="position:absolute; top:18px; right:16px; background:#0b2545; color:#fff; 
                     padding:6px 13px; font-size:0.98em; border-radius:10px; font-weight:bold;">
          PLUS
        </span>
        <h3 style="color:#0b2545;">InsightFundamental PLUS</h3>
        <div style="font-size:2em; font-weight:bold; margin:18px 0; color:#0b2545;">
          19,99 € <span style="font-size:0.5em; color:#555;">/ Monat</span>
        </div>
        <ul style="color:#222; font-size:18px; line-height:1.55;">
          <li>Impact Score & Marktzuordnung</li>
          <li>Konfidenz­grad & historische Muster</li>
          <li>Erweiterte Analysen & exklusive Features</li>
        </ul>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Abstand
    st.markdown("<div style='margin-bottom:40px'></div>", unsafe_allow_html=True)

    # Stripe-Checkout-Button nur für Standard-Nutzer
    if SESSION.logged_in and SESSION.user_plan == "Standard":
        checkout_url = "https://buy.stripe.com/eVq14m88aagx4ah3hNbAs01"
        st.markdown(f'''
            <a href="{checkout_url}" target="_blank" style="text-decoration:none;">
              <div style="
                  display: inline-block;
                  background-color: #0b2545;
                  color: white;
                  padding: 12px 28px;
                  border-radius: 6px;
                  font-size: 18px;
                  font-weight: bold;
                  cursor: pointer;
              ">
                InsightFundamental PLUS jetzt testen!
              </div>
            </a>
        ''', unsafe_allow_html=True)

    # Bereits PLUS-Mitglied?
    elif SESSION.logged_in and SESSION.user_plan == "Premium":
        st.success("Du bist bereits PLUS-Mitglied 🎉")

    # Nicht eingeloggt
    else:
        st.info("Bitte melde dich an, um das PLUS-Abo abzuschließen.")
        if st.button("Anmelden"):
            redirect_to("login")

    st.stop()

# --- LOGIN ---
if view == "login":
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_center = st.columns([3,4,3])[1]
    with col_center:
        st.markdown("<h2 style='color:#0b2545; margin-bottom:16px; margin-left:4px; text-align:left;'>Anmelden</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            email = st.text_input("E-Mail")
            pwd   = st.text_input("Passwort", type="password")
            if st.form_submit_button("Einloggen"):
                users = json.loads(USER_FILE.read_text())
                if users.get(email) == hashlib.sha256(pwd.encode()).hexdigest():
                    SESSION.logged_in = True
                    SESSION.username = email
                    SESSION.user_plan = "Standard"
                    redirect_to("Alle Nachrichten")
                elif users.get(email) and isinstance(users.get(email), dict):
                    if users[email].get("pwd") == hashlib.sha256(pwd.encode()).hexdigest():
                        SESSION.logged_in = True
                        SESSION.username = email
                        SESSION.user_plan = users[email].get("plan", "Standard")
                        redirect_to("Alle Nachrichten")
                else:
                    st.error("Ungültige Anmeldedaten")
        if st.button("Zurück zur Startseite"):
            redirect_to("Alle Nachrichten")
    st.stop()

# --- REGISTER ---
if view == "register":
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_center = st.columns([3,4,3])[1]
    with col_center:
        st.markdown("<h2 style='color:#0b2545; margin-bottom:16px; margin-left:4px; text-align:left;'>Registrieren</h2>", unsafe_allow_html=True)
        with st.form("reg_form"):
            email       = st.text_input("E-Mail")
            pwd         = st.text_input("Passwort", type="password")
            pwd_confirm = st.text_input("Passwort bestätigen", type="password")
            if st.form_submit_button("Registrieren"):
                if pwd != pwd_confirm:
                    st.error("Passwörter stimmen nicht überein")
                else:
                    users = json.loads(USER_FILE.read_text())
                    if email in users:
                        st.error("E-Mail bereits registriert")
                    else:
                        users[email] = hashlib.sha256(pwd.encode()).hexdigest()
                        save_users(users)
                        st.success("Registrierung erfolgreich!")
                        redirect_to("login")
        if st.button("Zurück zur Startseite"):
            redirect_to("Alle Nachrichten")
    st.stop()

# === EINDEUTIGE ID FÜR NACHRICHTEN VERGEBEN ===
def news_id(row):
    base = f"{row.get('title','')}_{row.get('publishedAt','')}"
    return hashlib.md5(base.encode()).hexdigest()

if "news_id" not in df.columns and not df.empty:
    df["news_id"] = df.apply(news_id, axis=1)

# === AUTOMATISCHE KATEGORISIERUNG (optional, kann bleiben, falls du später Filter wieder willst) ===
def categorize_news(row):
    text = f"{row.get('title','')} {row.get('description','')}".lower()
    if any(word in text for word in ["wirtschaft", "konjunktur", "bip", "aufschwung", "inflation", "arbeitsmarkt"]):
        return "Wirtschaft"
    if any(word in text for word in ["wahl", "regierung", "parlament", "politik", "gesetz", "minister", "bundestag"]):
        return "Politik"
    if any(word in text for word in ["aktie", "börse", "finanz", "geld", "zins", "anleihe", "dividende", "markt"]):
        return "Finanzen"
    if any(word in text for word in ["tech", "technologie", "innovation", "digital", "ai", "künstliche intelligenz", "software", "startup"]):
        return "Technologie"
    return "Wirtschaft"

if "kategorie" not in df.columns and not df.empty:
    df["kategorie"] = df.apply(categorize_news, axis=1)

# --- SIDEBAR DASHBOARD ---
if SESSION.logged_in:
    dash_tabs = ["Profil", "Abo & Billing", "Favoriten", "Support"]
    st.sidebar.markdown('<h2 style="margin-bottom:32px;">Dashboard</h2>', unsafe_allow_html=True)
    for tab in dash_tabs:
        is_active = (SESSION.dashboard_tab == tab)
        btn_class = "dashboard-btn active" if is_active else "dashboard-btn"
        if st.sidebar.button(tab, key=f"btn_{tab}"):
            SESSION.dashboard_tab = tab
        st.sidebar.markdown(
            f"""<style>
                #{f"btn_{tab}"} button.dashboard-btn {{
                    {'background:#1b325c;' if is_active else 'background:transparent;'}
                    font-size:22px;
                    font-weight:bold;
                    color:#fff !important;
                    padding:15px 22px;
                    border-radius:10px;
                    border:none;
                    text-align:left;
                    width:100%;
                }}
            </style>""",
            unsafe_allow_html=True
        )
    st.sidebar.markdown('<hr style="border: 1.5px solid #fff; margin: 16px 0 18px 0; border-radius:2px;">', unsafe_allow_html=True)
    st.sidebar.markdown(f'<div class="current-tab">{SESSION.dashboard_tab}</div>', unsafe_allow_html=True)

    # --- Tabs Inhalt ---
    if SESSION.dashboard_tab == "Profil":
        st.sidebar.markdown(f"<b>E-Mail:</b> {SESSION.username}", unsafe_allow_html=True)
        if "pw_change_open" not in SESSION:
            SESSION.pw_change_open = False
        if st.sidebar.button("Passwort ändern", key="btn_pw_change"):
            SESSION.pw_change_open = not SESSION.pw_change_open
        if SESSION.pw_change_open:
            old = st.sidebar.text_input("Aktuelles Passwort", type="password", key="old_pw")
            new = st.sidebar.text_input("Neues Passwort", type="password", key="new_pw")
            if st.sidebar.button("Aktualisieren", key="btn_upd_pw"):
                users = json.loads(USER_FILE.read_text())
                if users.get(SESSION.username) == hashlib.sha256(old.encode()).hexdigest():
                    users[SESSION.username] = hashlib.sha256(new.encode()).hexdigest()
                    save_users(users)
                    st.sidebar.success("Passwort geändert")
                    SESSION.pw_change_open = False
                else:
                    st.sidebar.error("Aktuelles Passwort falsch")
        # HIER: Abmelden-Button im Dashboard, Tab "Profil" (ganz unten)
        if st.sidebar.button("Abmelden", key="btn_logout_sidebar"):
            SESSION.logged_in = False
            SESSION.username = ""
            redirect_to("Alle Nachrichten")
    elif SESSION.dashboard_tab == "Abo & Billing":
        st.sidebar.markdown(f"**Plan:** {SESSION.user_plan}")
        if SESSION.user_plan == "Premium":
            st.sidebar.markdown("**Nächste Abbuchung:** 01.06.2025")
            if st.sidebar.button("Abo kündigen"):
                SESSION.user_plan = "Standard"
                st.sidebar.warning("Abo gekündigt")
        elif SESSION.user_plan == "Standard":
            if st.sidebar.button("InsightFundamental PLUS"):
                SESSION.user_plan = "Premium"
                st.sidebar.success("Abo auf Premium umgestellt!")
    elif SESSION.dashboard_tab == "Favoriten":
        st.sidebar.markdown("### Deine Favoriten")
        users = json.loads(USER_FILE.read_text())
        user_data = users.get(SESSION.username, {})
        if isinstance(user_data, str):
            user_data = {"pwd": user_data, "favorites": []}
            users[SESSION.username] = user_data
            save_users(users)
        favorites = user_data.get("favorites", [])

        fav_df = pd.DataFrame()
        if not favorites == [] and not df.empty:
            fav_df = df[df["news_id"].isin(favorites)].copy()
            fav_df["publishedAt"] = pd.to_datetime(fav_df["publishedAt"], errors="coerce")
            fav_df = fav_df.sort_values("publishedAt", ascending=False)

        if fav_df.empty:
            st.sidebar.info("Noch keine Favoriten gespeichert.")
        else:
            for _, row in fav_df.iterrows():
                headline = row['title']
                datum = row['publishedAt'].strftime('%d.%m.%Y %H:%M') if pd.notna(row['publishedAt']) else '-'
                st.sidebar.markdown(
                    f"<a href='/?view=news_detail&news_id={row['news_id']}' target='_self'>"
                    f"<b>{headline}</b></a><br><span style='color:#666;font-size:12px'>{datum}</span><hr>",
                    unsafe_allow_html=True
                )
    elif SESSION.dashboard_tab == "Support":
        fb = st.sidebar.text_area("Feedback / Support")
        if st.sidebar.button("Abschicken"):
            st.sidebar.success("Danke für dein Feedback!")

# === Suchleiste ===
if view not in ["login", "register"]:
    search = st.text_input("", placeholder="Suchen...", label_visibility="collapsed", key="search_bar")
    st.markdown("<div style='margin-bottom:30px'></div>", unsafe_allow_html=True)

# --- MARKETS (Charts) ---
view = st.query_params.get("view", ["Alle Nachrichten"])[0]
if view == "Märkte":
    st.subheader("Marktübersicht – 1-Tages-Kerzencharts")
    def tv(sym, title):
        st.markdown(f"""
        <h4>{title}</h4>
        <iframe src="https://s.tradingview.com/widgetembed/?symbol={sym}&interval=D&hidesidetoolbar=1&theme=light&style=1"
                width="100%" height="400" frameborder="0" scrolling="no"></iframe>
        """, unsafe_allow_html=True)
    tv("OANDA:DE30EUR","DAX")
    tv("AMEX:SPY","S&P 500")
    tv("OANDA:NAS100USD","Nasdaq")
    tv("OANDA:US30USD","Dow Jones")
    st.stop()

# === Detail-Ansicht für einzelne Nachrichten ===
if view == "news_detail":
    news_id = st.query_params.get("news_id", [None])[0]
    if news_id and not df.empty:
        row = df[df["news_id"] == news_id]
        if not row.empty:
            r = row.iloc[0]
            st.markdown(f"## {r['title']}")
            if pd.notna(r["publishedAt"]):
                st.markdown(
                    f"<div class='timestamp'>{r['publishedAt'].strftime('%d.%m.%Y %H:%M')}</div>",
                    unsafe_allow_html=True
                )
            if pd.notna(r.get("description")) and r.get("description"):
                st.markdown(f"{r['description']}")
            if r.get("image") and pd.notna(r['image']):
                st.image(r["image"], use_column_width=True)
            cls = (
                "impact-bearish" if "bearish" in r['impact_label']
                else "impact-bullish" if "bullish" in r['impact_label']
                else "impact-neutral"
            )
            st.markdown(
                f"<p><b>Impact Score:</b> <span class='{cls}'>{r['impact_label']}</span></p>",
                unsafe_allow_html=True
            )
            st.markdown(f"**Märkte betroffen:** {r.get('markets','-')}")
            st.markdown(f"**Konfidenzgrad:** {r.get('confidence','-')}")
            st.markdown(f"**Historische Muster:** {r.get('patterns','-')}")
            st.markdown(
                f"<details><summary><strong>Analyse anzeigen</strong></summary><p>{r.get('explanation','-')}</p></details>",
                unsafe_allow_html=True
            )
            st.markdown("---")
        else:
            st.warning("Nachricht nicht gefunden.")
    else:
        st.warning("Keine Nachricht ausgewählt oder keine Daten verfügbar.")
    st.stop()

# === Filtern & Aufbereiten ===
if df.empty:
    st.info("Keine Nachrichten verfügbar.")
    st.stop()

df["impact"] = pd.to_numeric(df.get("impact", 0), errors="coerce").fillna(0)
def grade(v):
    if v <= -7: return "sehr negativ"
    if v <= -3: return "negativ"
    if v >= 7:  return "sehr positiv"
    if v >= 3:  return "positiv"
    return "neutral"
df["impact_label"] = df["impact"].apply(grade)
df = df[df["impact_label"] != "neutral"]
df["publishedAt"] = pd.to_datetime(df.get("publishedAt"), errors="coerce")
df["sentiment"] = df.get("sentiment", "").astype(str).str.strip().str.lower()

if view not in ["login", "register"]:
    if 'search' in locals() and search:
        q = search.lower()
        df = df[df["title"].str.lower().str.contains(q, na=False) |
                df["description"].str.lower().str.contains(q, na=False)]

    for _, r in df.iterrows():
        st.markdown(f"### {r['title']}")
        if pd.notna(r["publishedAt"]):
            st.markdown(
                f"<div class='timestamp'>{r['publishedAt'].strftime('%d.%m.%Y %H:%M')}</div>",
                unsafe_allow_html=True
            )
        if pd.notna(r.get("description")) and r.get("description"):
            st.markdown(f"{r['description']}")
        if r.get("image") and pd.notna(r['image']):
            st.image(r["image"], use_column_width=True)
        cls = (
            "impact-bearish" if "bearish" in r['impact_label']
            else "impact-bullish" if "bullish" in r['impact_label']
            else "impact-neutral"
        )
        st.markdown(
            f"<p><b>Impact Score:</b> <span class='{cls}'>{r['impact_label']}</span></p>",
            unsafe_allow_html=True
        )
        st.markdown(f"**Märkte betroffen:** {r.get('markets','-')}")
        st.markdown(f"**Konfidenzgrad:** {r.get('confidence','-')}")
        st.markdown(f"**Historische Muster:** {r.get('patterns','-')}")
        st.markdown(
            f"<details><summary><strong>Analyse anzeigen</strong></summary><p>{r.get('explanation','-')}</p></details>",
            unsafe_allow_html=True
        )
        if SESSION.logged_in:
            users = json.loads(USER_FILE.read_text())
            user_data = users.get(SESSION.username, {})
            if isinstance(user_data, str):
                user_data = {"pwd": user_data, "favorites": []}
                users[SESSION.username] = user_data
                save_users(users)
            favorites = user_data.get("favorites", [])
            news_id = r["news_id"]
            if news_id in favorites:
                if st.button("Aus Favoriten entfernen", key=f"fav_remove_{news_id}"):
                    favorites.remove(news_id)
                    user_data["favorites"] = favorites
                    users[SESSION.username] = user_data
                    save_users(users)
                    st.rerun()
            else:
                if st.button("Zu Favoriten", key=f"fav_add_{news_id}"):
                    favorites.append(news_id)
                    user_data["favorites"] = favorites
                    users[SESSION.username] = user_data
                    save_users(users)
                    st.rerun()
        st.markdown("---")