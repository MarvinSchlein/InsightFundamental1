import streamlit as st
import pandas as pd
from pathlib import Path
from urllib.parse import unquote

st.set_page_config(page_title="Nachrichtendetail", layout="wide")

st.markdown("<h1 style='color:#0b2545'>Nachrichtendetails</h1>", unsafe_allow_html=True)

# Daten laden
df = pd.read_csv("data/news_analysis_results.csv") if Path("data/news_analysis_results.csv").exists() else pd.DataFrame()

title_param = st.query_params.get("title", [None])[0]
if not title_param:
    st.error("Keine Nachricht ausgewählt.")
    st.stop()

title_param = unquote(title_param)
row = df[df["title"] == title_param]
if row.empty:
    st.warning("Nachricht nicht gefunden.")
    st.stop()

row = row.iloc[0]  # Einzelner Eintrag

# Impact-Styling
impact_class = "impact-neutral"
if "bullish" in str(row["impact"]).lower():
    impact_class = "impact-bullish"
elif "bearish" in str(row["impact"]).lower():
    impact_class = "impact-bearish"

# Anzeige
st.markdown(f"<h2>{row['title']}</h2>", unsafe_allow_html=True)
if pd.notna(row.get("publishedAt", None)):
    st.markdown(f"<div style='color:#555;'>🕒 {row['publishedAt']}</div>", unsafe_allow_html=True)

if pd.notna(row.get("image", None)):
    st.image(row["image"], use_column_width=True)

st.markdown(f"<p><b>Impact Score:</b> <span style='color:{'green' if row['impact'] > 0 else 'red' if row['impact'] < 0 else 'black'}'>{row['impact']}</span></p>", unsafe_allow_html=True)
st.markdown(f"**Märkte betroffen:** {row.get('markets', '-')}")
st.markdown(f"**Konfidenzgrad:** {row.get('confidence', '-')}")
st.markdown(f"**Historische Muster:** {row.get('patterns', '-')}")

# Ausführlichere Begründung
original = str(row.get("explanation", "-"))
st.markdown("### 🧠 Ausführliche Begründung")
st.write(f"**{original}**")  # Optional: GPT-unterstützte Version später

st.markdown("[Zurück zur Startseite](../)")