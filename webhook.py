import os
import stripe
from flask import Flask, request, jsonify
from supabase import create_client, Client

# --------------------
# Environment Variables
# --------------------
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key!

if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
    raise ValueError("Stripe API Key oder Webhook Secret fehlen in Environment Variables.")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL oder Service Role Key fehlen in Environment Variables.")

# --------------------
# Initialize Clients
# --------------------
stripe.api_key = STRIPE_API_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

# --------------------
# Stripe Webhook Route
# --------------------
@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    # Event verifizieren
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        print(f"✅ Webhook Event empfangen: {event['type']}")
    except stripe.error.SignatureVerificationError as e:
        print("❌ Webhook Signature Verification failed:", e)
        return jsonify(success=False), 400
    except Exception as e:
        print("❌ Fehler beim Verarbeiten des Webhooks:", e)
        return jsonify(success=False), 400

    # --------------------
    # Spezifische Events
    # --------------------
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")
        subscription_id = session.get("subscription")

        print(f"ℹ️ Checkout abgeschlossen für {customer_email}, Sub-ID: {subscription_id}")

        if customer_email and subscription_id:
            try:
                response = (
                    supabase.table("users")
                    .update({"subscription_status": "active"})
                    .eq("email", customer_email)
                    .execute()
                )
                print("✅ Supabase Update Response:", response)
            except Exception as e:
                print("❌ Fehler beim Supabase Update:", e)

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")

        print(f"ℹ️ Subscription gelöscht, Customer-ID: {customer_id}")

        if customer_id:
            try:
                # Customer E-Mail über Stripe abfragen
                customer = stripe.Customer.retrieve(customer_id)
                customer_email = customer.get("email")

                if customer_email:
                    response = (
                        supabase.table("users")
                        .update({"subscription_status": "canceled"})
                        .eq("email", customer_email)
                        .execute()
                    )
                    print("✅ Supabase Update Response:", response)
            except Exception as e:
                print("❌ Fehler beim Subscription-Cancel-Update:", e)

    return jsonify(success=True)

# --------------------
# Local / Render Server
# --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
