import os
import json
import logging
from typing import Optional

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

# === NEU: user_id per RPC aus auth.users ziehen ===
def _get_auth_user_id(email: str) -> Optional[str]:
    """
    Ruft die auth.users.id über die SQL-Funktion public.user_id_by_email(email) ab.
    Die Funktion muss in Supabase bereits existieren (Schritt 1).
    """
    try:
        res = supabase.rpc("user_id_by_email", {"email": email}).execute()
        data = res.data
        # robust extrahieren (je nach Rückgabeform)
        if not data:
            return None
        if isinstance(data, str):
            return data
        if isinstance(data, dict) and data.get("user_id"):
            return data["user_id"]
        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict) and first.get("user_id"):
                return first["user_id"]
        return None
    except Exception as e:
        log.error("❌ RPC user_id_by_email failed for %s: %s", email, e, exc_info=True)
        return None

# === NEU: Abo-Status in public.profiles setzen (statt public.users) ===
def set_profile_subscription(email: str, active: bool) -> dict:
    """
    Setzt subscription_active in public.profiles für den zugehörigen auth.users.id.
    Falls kein Profil existiert, wird (best effort) ein Insert versucht.
    """
    email_norm = normalize_email(email)
    if not email_norm:
        return {"mode": "invalid-email"}

    user_id = _get_auth_user_id(email_norm)
    if not user_id:
        log.warning("⚠️ No auth.user found for email=%s", email_norm)
        return {"mode": "missing-auth-user"}

    try:
        # 1) Update versuchen
        upd = (
            supabase.table("profiles")
            .update({"subscription_active": active})
            .eq("id", user_id)
            .execute()
        )
        if upd.data:
            return {"mode": "update", "data": upd.data}

        # 2) Falls kein Datensatz vorhanden → Insert/Upsert
        #    (id ist PK; bei bereits existierendem Datensatz ist Update der übliche Pfad)
        ins = (
            supabase.table("profiles")
            .upsert({"id": user_id, "subscription_active": active})
            .execute()
        )
        return {"mode": "upsert", "data": ins.data}
    except Exception as e:
        log.error("❌ Supabase profiles update error: %s", e, exc_info=True)
        return {"mode": "error", "error": str(e)}

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
        # Bevorzugt: customer_details.email
        email = normalize_email((session.get("customer_details") or {}).get("email"))
        if not email:
            # Fallback via customer_id
            email = get_email_from_customer_id(session.get("customer"))

        if not email:
            log.warning("⚠️ No email resolvable in checkout.session.completed: %s", json.dumps(session))
            return jsonify(ok=True), 200

        try:
            result = set_profile_subscription(email, True)
            log.info("📦 profiles update result (checkout): %s", result)
        except Exception as e:
            log.error("❌ profiles update error (checkout): %s", e, exc_info=True)

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
            result = set_profile_subscription(email, make_active)
            log.info("🔁 profiles status=%s -> subscription_active=%s: %s",
                     status, make_active, result)
        except Exception as e:
            log.error("❌ profiles update error (subscription.%s): %s", status, e, exc_info=True)

    # ========== customer.subscription.deleted ==========
    elif etype == "customer.subscription.deleted":
        sub = event["data"]["object"]
        email = get_email_from_customer_id(sub.get("customer"))
        if email:
            try:
                result = set_profile_subscription(email, False)
                log.info("🔻 Deactivated after cancellation: %s", result)
            except Exception as e:
                log.error("❌ profiles update error (subscription.deleted): %s", e, exc_info=True)

    # ========== invoice.payment_failed ==========
    elif etype == "invoice.payment_failed":
        inv = event["data"]["object"]
        email = get_email_from_customer_id(inv.get("customer"))
        if email:
            try:
                result = set_profile_subscription(email, False)
                log.info("🔻 Deactivated after payment failure: %s", result)
            except Exception as e:
                log.error("❌ profiles update error (payment_failed): %s", e, exc_info=True)

    # ========== invoice.payment_succeeded ==========
    elif etype == "invoice.payment_succeeded":
        inv = event["data"]["object"]
        email = get_email_from_customer_id(inv.get("customer"))
        if email:
            try:
                result = set_profile_subscription(email, True)
                log.info("✅ Activated after payment succeeded: %s", result)
            except Exception as e:
                log.error("❌ profiles update error (payment_succeeded): %s", e, exc_info=True)

    return jsonify(ok=True), 200

# ---------- Serverstart ----------
if __name__ == "__main__":
    # Render setzt PORT; fallback auf 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
