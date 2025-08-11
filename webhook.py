import os
import json
from flask import Flask, request
from supabase import create_client, Client
import stripe

# === Flask App ===
app = Flask(__name__)

# === Keys ===
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
stripe.api_key = STRIPE_SECRET

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    # Verifiziere Webhook-Signatur
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        print("❌ Invalid payload:", e)
        return "Bad request", 400
    except stripe.error.SignatureVerificationError as e:
        print("❌ Invalid signature:", e)
        return "Unauthorized", 400

    print("✅ Event received:", event["type"])

    # === Logging der Daten ===
    try:
        print("📦 Event data object:", json.dumps(event["data"]["object"], indent=2))
    except Exception as e:
        print("⚠️ Could not pretty print event data:", e)

    # === Handling checkout.session.completed ===
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")

        if not customer_email:
            print("⚠️ No customer email found in session")
            return "No email", 200

        print(f"🔍 Searching Supabase user with email: {customer_email}")

        # Update in Supabase
        try:
            result = supabase.table("users").update(
                {"subscription_active": True}
            ).eq("email", customer_email).execute()

            if result.data:
                print(f"✅ Subscription activated for {customer_email}")
            else:
                print(f"⚠️ No user found with email {customer_email}")

        except Exception as e:
            print("❌ Error updating Supabase:", e)
            return "DB error", 500

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
