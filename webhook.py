import os
import stripe
from flask import Flask, request, jsonify
from supabase import create_client, Client

app = Flask(__name__)

# Stripe Setup
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

# Supabase Setup (mit Service Role Key!)
supabase_url = os.environ.get("SUPABASE_URL")
supabase_service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(supabase_url, supabase_service_role_key)


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400
    except Exception as e:
        return str(e), 400

    # 📩 Ereignis auswerten
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        # E-Mail des Käufers auslesen
        customer_email = session.get("customer_email")

        if customer_email:
            try:
                # Nutzer in Supabase auf "paid" setzen
                supabase.table("users").update({
                    "subscription_active": True,
                    "plan": "paid"
                }).eq("email", customer_email).execute()
                print(f"✅ Nutzer {customer_email} auf paid gesetzt.")
            except Exception as e:
                print(f"❌ Fehler beim Update in Supabase: {e}")

    return jsonify(success=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
