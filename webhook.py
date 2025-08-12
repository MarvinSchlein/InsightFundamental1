import os
import json
import logging
from typing import Optional

import stripe
from flask import Flask, request, jsonify
from supabase import create_client, Client

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, force=True)
log = logging.getLogger("webhook")

# ---------- ENV ----------
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")  # Service-Role!

# Für Checkout-/Portal-Session (Option B)
STRIPE_PRICE_ID    = os.environ.get("STRIPE_PRICE_ID")
STRIPE_SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL") or "https://insightfundamental.streamlit.app/?view=news&from=stripe"
STRIPE_CANCEL_URL  = os.environ.get("STRIPE_CANCEL_URL")  or "https://insightfundamental.streamlit.app/?view=register"
STRIPE_PORTAL_RETURN_URL = os.environ.get("STRIPE_PORTAL_RETURN_URL") or STRIPE_SUCCESS_URL

if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("Stripe ENV missing (STRIPE_API_KEY / STRIPE_WEBHOOK_SECRET)")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase ENV missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
if not STRIPE_PRICE_ID:
    raise RuntimeError("Stripe ENV missing (STRIPE_PRICE_ID)")

stripe.api_key = STRIPE_API_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

# ---------- Helpers ----------
def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return email.strip().lower()

def get_email_from_customer_id(customer_id: Optional[str]) -> Optional[str]:
    if not customer_id:
        return None
    try:
        cust = stripe.Customer.retrieve(customer_id)
        return normalize_email(cust.get("email"))
    except Exception as e:
        log.warning("⚠️ could not retrieve customer %s: %s", customer_id, e)
        return None

def supabase_set_subscription(email: str, active: bool) -> dict:
    # 1) exact match
    resp = supabase.table("users").update({"subscription_active": active}).eq("email", email).execute()
    if resp.data:
        return {"mode": "eq", "data": resp.data}
    # 2) case-insensitive
    resp2 = supabase.table("users").update({"subscription_active": active}).ilike("email", email).execute()
    if resp2.data:
        return {"mode": "ilike", "data": resp2.data}
    # 3) upsert
    upsert = supabase.table("users").upsert(
        {"email": email, "subscription_active": active},
        on_conflict="email"
    ).execute()
    return {"mode": "upsert", "data": upsert.data}

# ---------- Health / Debug ----------
@app.route("/", methods=["GET", "HEAD"])
def root():
    return "ok", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200

@app.route("/routes", methods=["GET"])
def list_routes():
    routes = [f"{r.rule} [{','.join(sorted(r.methods))}]" for r in app.url_map.iter_rules()]
    return jsonify(routes=sorted(routes)), 200

# ---------- Create Checkout Session (serverseitig) ----------
# Alle drei Varianten ohne Trailing Slash:
@app.route("/create-checkout-session", methods=["POST"])
@app.route("/create_checkout_session", methods=["POST"])
@app.route("/checkout", methods=["POST"])
def create_checkout_session():
    try:
        data = request.get_json(force=True) or {}
        app_email = normalize_email(data.get("email"))
        if not app_email:
            return jsonify(error="email required"), 400

        # Kunde deterministisch finden/erstellen
        customer_id = None
        try:
            found = stripe.Customer.list(email=app_email, limit=1)
            if found.data:
                customer_id = found.data[0].id
            else:
                customer = stripe.Customer.create(email=app_email)
                customer_id = customer.id
        except Exception as e:
            log.warning("⚠️ could not ensure customer for %s: %s", app_email, e)
            customer_id = None  # Fallback: Stripe mappt über customer_email

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            client_reference_id=app_email,
            metadata={"app_email": app_email},
            customer=customer_id,
            customer_email=None if customer_id else app_email,
            allow_promotion_codes=True,
            automatic_tax={"enabled": True},
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
        )
        return jsonify(url=session.url), 200

    except Exception as e:
        log.error("❌ create-checkout-session error: %s", e, exc_info=True)
        return jsonify(error=str(e)), 500

# ---------- Create Customer Portal Session (Manage subscription) ----------
@app.route("/create-portal-session", methods=["POST"])
@app.route("/create_portal_session", methods=["POST"])
@app.route("/portal", methods=["POST"])
def create_portal_session():
    try:
        data = request.get_json(force=True) or {}
        app_email = normalize_email(data.get("email"))
        if not app_email:
            return jsonify(error="email required"), 400

        customers = stripe.Customer.list(email=app_email, limit=1)
        if not customers.data:
            return jsonify(error="customer not found"), 404

        customer_id = customers.data[0].id
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=STRIPE_PORTAL_RETURN_URL,
        )
        return jsonify(url=session.url), 200

    except Exception as e:
        log.error("❌ create_portal_session error: %s", e, exc_info=True)
        return jsonify(error=str(e)), 500

# ---------- Webhook ----------
@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
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

    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        email = normalize_email(session.get("client_reference_id")) \
                or normalize_email((session.get("metadata") or {}).get("app_email"))
        if not email:
            email = normalize_email((session.get("customer_details") or {}).get("email"))
        if not email:
            email = get_email_from_customer_id(session.get("customer"))
        if not email:
            log.warning("⚠️ No email resolvable in checkout.session.completed.")
            return jsonify(ok=True), 200
        try:
            result = supabase_set_subscription(email, True)
            log.info("📦 Supabase update result (checkout, %s): %s", result.get("mode"), result.get("data"))
        except Exception as e:
            log.error("❌ Supabase update error (checkout): %s", e, exc_info=True)
            return jsonify(ok=True), 200

    elif etype in ("customer.subscription.created", "customer.subscription.updated"):
        sub = event["data"]["object"]
        status = (sub.get("status") or "").lower()
        email = get_email_from_customer_id(sub.get("customer"))
        if not email:
            log.warning("⚠️ No email resolvable in %s", etype)
            return jsonify(ok=True), 200
        make_active = status in ("active", "trialing")
        try:
            result = supabase_set_subscription(email, make_active)
            log.info("🔁 Subscription status=%s -> subscription_active=%s (%s): %s",
                     status, make_active, result.get("mode"), result.get("data"))
        except Exception as e:
            log.error("❌ Supabase update error (subscription.%s): %s", status, e, exc_info=True)

    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        email = get_email_from_customer_id(sub.get("customer"))
        if email:
            try:
                result = supabase_set_subscription(email, False)
                log.info("🔻 Deactivated after cancellation (%s): %s", result.get("mode"), result.get("data"))
            except Exception as e:
                log.error("❌ Supabase update error (subscription.deleted): %s", e, exc_info=True)

    elif etype == "invoice.payment_failed":
        inv = event["data"]["object"]
        email = get_email_from_customer_id(inv.get("customer"))
        if email:
            try:
                result = supabase_set_subscription(email, False)
                log.info("🔻 Deactivated after payment failure (%s): %s", result.get("mode"), result.get("data"))
            except Exception as e:
                log.error("❌ Supabase update error (payment_failed): %s", e, exc_info=True)

    elif etype == "invoice.payment_succeeded":
        inv = event["data"]["object"]
        email = get_email_from_customer_id(inv.get("customer"))
        if email:
            try:
                result = supabase_set_subscription(email, True)
                log.info("✅ Activated after payment succeeded (%s): %s", result.get("mode"), result.get("data"))
            except Exception as e:
                log.error("❌ Supabase update error (payment_succeeded): %s", e, exc_info=True)

    return jsonify(ok=True), 200

# ---------- Serverstart ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
