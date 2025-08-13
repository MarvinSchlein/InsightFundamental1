import os
import json
import logging
import stripe
from flask import Flask, request, jsonify, redirect
from supabase import create_client, Client

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, force=True)
log = logging.getLogger("webhook")

# ---------- ENV ----------
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")  # Service-Role!
# Rücksprungziel aus dem Billing-Portal (kannst du in Render als STRIPE_PORTAL_RETURN_URL setzen)
STRIPE_PORTAL_RETURN_URL = os.environ.get("STRIPE_PORTAL_RETURN_URL") or "https://insightfundamental.streamlit.app/?view=news"

if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("Stripe ENV missing (STRIPE_API_KEY / STRIPE_WEBHOOK_SECRET)")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase ENV missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")

stripe.api_key = STRIPE_API_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)

# ---------- Helpers ----------
def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    return email.strip().lower()

def get_email_from_customer_id(customer_id: str | None) -> str | None:
    if not customer_id:
        return None
    try:
        cust = stripe.Customer.retrieve(customer_id)
        return normalize_email(cust.get("email"))
    except Exception as e:
        log.warning("⚠️ could not retrieve customer %s: %s", customer_id, e)
        return None

def supabase_set_subscription(email: str, active: bool) -> dict:
    """
    Setzt subscription_active für email.
    Versucht exact match -> ILIKE -> Upsert (falls User noch nicht existiert).
    """
    # 1) exact match
    resp = supabase.table("users").update({"subscription_active": active}).eq("email", email).execute()
    if resp.data:
        return {"mode": "eq", "data": resp.data}

    # 2) case-insensitive
    resp2 = supabase.table("users").update({"subscription_active": active}).ilike("email", email).execute()
    if resp2.data:
        return {"mode": "ilike", "data": resp2.data}

    # 3) upsert (falls Checkout vor Registration passiert ist)
    upsert = supabase.table("users").upsert(
        {"email": email, "subscription_active": active},
        on_conflict="email"
    ).execute()
    return {"mode": "upsert", "data": upsert.data}

# ---------- Health / Root ----------
@app.route("/", methods=["GET", "HEAD"])
def root():
    return "ok", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200

# ---------- NEU: GET /portal (Stripe Billing-Portal im neuen Tab) ----------
# Unterstützt beide Varianten: /portal UND /portal/
@app.route("/portal", methods=["GET"])
@app.route("/portal/", methods=["GET"])
def portal_get():
    """
    Öffnet das Stripe Billing-Portal direkt (GET), damit das Frontend
    einfach einen Link in neuem Tab öffnen kann.
    ?email=<app_email>
    """
    email = normalize_email(request.args.get("email"))
    if not email:
        return "email required", 400

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return "customer not found", 404

        session = stripe.billing_portal.Session.create(
            customer=customers.data[0].id,
            return_url=STRIPE_PORTAL_RETURN_URL,
        )
        # Browser direkt zu Stripe umleiten
        return redirect(session.url, code=302)
    except Exception as e:
        log.error("❌ portal error: %s", e, exc_info=True)
        return "internal error", 500

# ---------- DEBUG: registrierte Routen anzeigen ----------
@app.route("/routes", methods=["GET"])
def list_routes():
    routes = [f"{r.rule} [{','.join(sorted(r.methods))}]" for r in app.url_map.iter_rules()]
    return jsonify(routes=routes), 200

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

    # ========== checkout.session.completed ==========
    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        # In manchen Events ist customer_email null → customer_details.email verwenden
        email = normalize_email((session.get("customer_details") or {}).get("email"))
        if not email:
            # Fallback via customer_id
            email = get_email_from_customer_id(session.get("customer"))

        if not email:
            log.warning("⚠️ No email resolvable in checkout.session.completed: %s", json.dumps(session))
            return jsonify(ok=True), 200

        try:
            result = supabase_set_subscription(email, True)
            log.info("📦 Supabase update result (checkout, %s): %s", result.get("mode"), result.get("data"))
        except Exception as e:
            log.error("❌ Supabase update error (checkout): %s", e, exc_info=True)
            return jsonify(ok=True), 200

    # ========== customer.subscription.created / updated ==========
    elif etype in ("customer.subscription.created", "customer.subscription.updated"):
        sub = event["data"]["object"]
        status = (sub.get("status") or "").lower()  # active, trialing, past_due, canceled, unpaid, incomplete, ...
        customer_id = sub.get("customer")
        email = get_email_from_customer_id(customer_id)

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

    # ========== customer.subscription.deleted ==========
    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        email = get_email_from_customer_id(sub.get("customer"))
        if email:
            try:
                result = supabase_set_subscription(email, False)
                log.info("🔻 Deactivated after cancellation (%s): %s", result.get("mode"), result.get("data"))
            except Exception as e:
                log.error("❌ Supabase update error (subscription.deleted): %s", e, exc_info=True)

    # ========== invoice.payment_failed ==========
    elif etype == "invoice.payment_failed":
        inv = event["data"]["object"]
        email = get_email_from_customer_id(inv.get("customer"))
        if email:
            try:
                result = supabase_set_subscription(email, False)
                log.info("🔻 Deactivated after payment failure (%s): %s", result.get("mode"), result.get("data"))
            except Exception as e:
                log.error("❌ Supabase update error (payment_failed): %s", e, exc_info=True)

    # ========== invoice.payment_succeeded ==========
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
    # Render setzt PORT; fallback auf 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
