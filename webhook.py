# webhook.py
import json
import os
from flask import Flask, request

import stripe

app = Flask(__name__)

USERS_FILE = "users.json"
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
stripe.api_key = os.getenv("STRIPE_API_KEY")


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return f"Webhook error: {e}", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session["customer_details"]["email"]

        try:
            with open(USERS_FILE, "r") as f:
                users = json.load(f)
        except FileNotFoundError:
            users = {}

        if customer_email in users:
            if isinstance(users[customer_email], dict):
                users[customer_email]["subscription_active"] = True
            else:
                users[customer_email] = {
                    "pwd": users[customer_email],
                    "subscription_active": True,
                }

            with open(USERS_FILE, "w") as f:
                json.dump(users, f, indent=4)

            print(f"✅ Subscription activated for {customer_email}")
        else:
            print(f"⚠️ User {customer_email} not found in users.json")

    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
