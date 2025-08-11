import os
import json
import stripe
from flask import Flask, request
from supabase import create_client

app = Flask(__name__)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))

endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ Webhook signature verification failed: {e}")
        return "Bad signature", 400
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return "Webhook error", 400

    print(f"✅ Event empfangen: {event['type']}")
    print(f"📦 Payload: {json.dumps(event, indent=2)}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_email")

        if not customer_email:
            print("❌ Keine Kunden-E-Mail im Event gefunden")
            return "No email", 400

        try:
            response = supabase.table("users").update({"subscription_active": True}).eq("email", customer_email).execute()
            print(f"✅ Supabase-Update-Response: {response}")
        except Exception as e:
            print(f"❌ Fehler beim Supabase-Update: {e}")
            return "Supabase update error", 500

    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
