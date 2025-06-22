import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="Anmelden", layout="centered")
st.title("🔐 Anmelden")

USER_FILE = Path("data/users.json")
if not USER_FILE.exists():
    USER_FILE.write_text("{}")

with open(USER_FILE) as f:
    users = json.load(f)

username = st.text_input("Benutzername")
password = st.text_input("Passwort", type="password")

if st.button("Einloggen"):
    if username in users and users[username] == password:
        st.session_state.logged_in = True
        st.session_state.username = username
        st.success("Erfolgreich angemeldet.")
        st.switch_page("app.py")
    else:
        st.error("Falscher Benutzername oder Passwort.")