import os
from flask import Flask, request
import stripe
from supabase import create_client, Client

# ==== Stripe Setup ====
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# ==== Supabase Setup ====
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Service Role Key nötig für Updates
supabase = create_client(supabase_url, supabase_key)

app = Flask(__name__)

@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    # === Event Handling ===
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_email")
        if customer_email:
            supabase.table("users").update({"subscription_active": True}).eq("email", customer_email).execute()

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        # Email aus Stripe-API abrufen
        customer = stripe.Customer.retrieve(customer_id)
        email = customer.get("email")
        if email:
            supabase.table("users").update({"subscription_active": False}).eq("email", email).execute()

    return jsonify({"status": "success"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
