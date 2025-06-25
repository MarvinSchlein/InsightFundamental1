import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="Registrieren", layout="centered")
st.title("📝 Registrieren")

USER_FILE = Path("data/users.json")
if not USER_FILE.exists():
    USER_FILE.write_text("{}")

with open(USER_FILE) as f:
    users = json.load(f)

username = st.text_input("Benutzername")
password = st.text_input("Passwort", type="password")

if st.button("Registrieren"):
    if username in users:
        st.warning("Benutzername bereits vergeben.")
    else:
        users[username] = password
        with open(USER_FILE, "w") as f:
            json.dump(users, f)
        st.session_state.logged_in = True
        st.session_state.username = username
        st.success("Registrierung erfolgreich.")
        st.switch_page("app.py")