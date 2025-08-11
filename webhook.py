import os
import json
import logging
import stripe
from flask import Flask, request, jsonify
from supabase import create_client, Client

# ---------- Logging sauber aktivieren ----------
logging.basicConfig(level=logging.INFO, force=True)
log = logging.getLogger("webhook")

# ---------- ENV laden (genau so wie auf Render gesetzt) ----------
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")  # Service-Role!

if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("Stripe ENV missing (STRIPE_API_KEY / STRIPE_WEBHOOK_SECRET)")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase ENV missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")

stripe.api_key = STRIPE_API_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

# ---------- Helper: robustes Update ----------
def set_subscription_active_by_email(email: str) -> dict:
    """
    Setzt subscription_active=True für die gegebene E-Mail.
    Versucht: exact match -> ILIKE -> Upsert (falls User nicht existiert).
    Gibt die Supabase-Antwort zurück (für Logs).
    """
    # 1) exact match (lowercase-normalisiert)
    resp = supabase.table("users").update({"subscription_active": True}) \
        .eq("email", email).execute()
    if resp.data:
        return {"mode": "eq", "data": resp.data}

    # 2) case-insensitive fallback
    resp2 = supabase.table("users").update({"subscription_active": True}) \
        .ilike("email", email).execute()
    if resp2.data:
        return {"mode": "ilike", "data": resp2.data}

    # 3) optional: upsert (nur wenn du willst, dass Checkout auch ohne Registrierung greift)
    upsert = supabase.table("users").upsert(
        {"email": email, "subscription_active": True},
        on_conflict="email"
    ).execute()
    return {"mode": "upsert", "data": upsert.data}

# ---------- Webhook ----------
@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    # Signatur prüfen
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as e:
        log.error("❌ Signature failed: %s", e)
        return jsonify(ok=False), 400
    except Exception as e:
        log.error("❌ Webhook error: %s", e)
        return jsonify(ok=False), 400

    etype = event.get("type")
    log.info("✅ Event: %s", etype)

    # Nur auf checkout.session.completed reagieren
    if etype == "checkout.session.completed":
        session = event["data"]["object"]

        # Wichtiger Punkt: customer_email ist bei dir NULL; nimm customer_details.email
        customer_email = (session.get("customer_details") or {}).get("email")
        if not customer_email:
            log.warning("⚠️ No customer email in session: %s", json.dumps(session))
            return jsonify(ok=True)  # 200 zurückgeben, damit Stripe nicht spammt

        email_norm = customer_email.strip().lower()
        log.info("📧 Will update Supabase for email: %s", email_norm)

        try:
            result = set_subscription_active_by_email(email_norm)
            log.info("📦 Supabase update result (%s): %s", result.get("mode"), result.get("data"))
        except Exception as e:
            log.error("❌ Supabase update error: %s", e, exc_info=True)
            # 200 zurückgeben, damit Stripe nicht ständig retryt – aber Fehler loggen
            return jsonify(ok=True), 200

    return jsonify(ok=True), 200

# ---------- Serverstart ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
