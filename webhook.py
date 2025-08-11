import os
import json
from flask import Flask, request
import stripe
from supabase import create_client

app = Flask(__name__)

# Env-Variablen
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(supabase_url, supabase_key)

@app.route("/webhook", methods=["POST"])
def webhook_received():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    # Prüfen, ob Signatur stimmt
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except stripe.error.SignatureVerificationError as e:
        print("❌ Signature error:", e)
        return "Bad signature", 400
    except Exception as e:
        print("❌ Webhook error:", e)
        return "Webhook error", 400

    print("✅ Event empfangen:", event["type"])

    # Nur bei erfolgreichem Checkout-Event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_email")
        print("📧 Customer email:", customer_email)

        if customer_email:
            try:
                # Update in Supabase
                result = supabase.table("users").update({"subscription_active": True}).eq("email", customer_email).execute()
                print("📦 Supabase-Update-Result:", result)
            except Exception as e:
                print("❌ Supabase update error:", e)

    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
