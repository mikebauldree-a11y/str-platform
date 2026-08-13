import os, json, uuid, base64, traceback

import requests
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, abort, jsonify
from dotenv import load_dotenv
import stripe
import anthropic
from generate_report import generate_html_report

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-123")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# ── Email config (Resend HTTP API) ────────────────────────────────────────────
# Railway blocks outbound SMTP on all ports, so mail goes over HTTPS.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_URL     = "https://api.resend.com/emails"

# Until caribbeanstr.com is verified in Resend, leave FROM_EMAIL unset and
# this falls back to Resend's sandbox sender, which works immediately but
# can only deliver to your own account address.
FROM_EMAIL  = os.getenv("FROM_EMAIL", "onboarding@resend.dev")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

# Resend is send-only, so reports@caribbeanstr.com cannot receive mail.
# Customer replies are routed to a mailbox that is actually monitored.
REPLY_TO    = os.getenv("REPLY_TO")
BASE_URL    = os.getenv("BASE_URL", "https://caribbeanstr.com").rstrip("/")

BASE_DIR = Path(__file__).parent

# Persistent storage. On Railway set DATA_DIR=/data and attach a volume
# mounted at /data, otherwise these directories live on the container
# filesystem and are wiped on every redeploy — taking paid customers'
# reports and in-flight orders with them.
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR))

PENDING_DIR = DATA_DIR / "pending_deals"
REPORTS_DIR = DATA_DIR / "reports"
SAMPLES_DIR = BASE_DIR / "samples"          # ships with the repo, not user data

for d in [PENDING_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
SAMPLES_DIR.mkdir(exist_ok=True)

print(f"[startup] DATA_DIR={DATA_DIR}  persistent={DATA_DIR != BASE_DIR}")

# ── Load markets data once at startup ────────────────────────────────────────
_markets_path = BASE_DIR / "data" / "markets.json"
with open(_markets_path, "r", encoding="utf-8") as _f:
    MARKETS = json.load(_f)

# ── Load blog posts once at startup ──────────────────────────────────────────
_blog_posts_path = BASE_DIR / "data" / "blog_posts.json"
with open(_blog_posts_path, "r", encoding="utf-8") as _f:
    BLOG_POSTS = json.load(_f)

BRAND_NAME = "Caribbean STR"

# ── Report generation + delivery ──────────────────────────────────────────────
def _resend_send(payload, order_id, label):
    """POST one message to Resend. Returns True on success, never raises."""
    try:
        r = requests.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if r.status_code in (200, 201):
            print(f"[email] {order_id}: {label} sent")
            return True
        print(f"[email] {order_id}: {label} FAILED — HTTP {r.status_code} {r.text[:400]}")
        return False
    except Exception as e:
        print(f"[email] {order_id}: {label} FAILED — {e}")
        traceback.print_exc()
        return False


def _send_report_email(data, order_id, report_html):
    """Email the finished report to the buyer as an attachment.

    Returns True on success. Never raises — a mail failure must not break
    the purchase flow, since the report is already saved and downloadable.
    """
    to_addr = (data.get("email") or "").strip()
    if not to_addr:
        print(f"[email] {order_id}: no email address on file, skipping")
        return False
    if not RESEND_API_KEY:
        print(f"[email] {order_id}: RESEND_API_KEY not set, skipping")
        return False

    name    = (data.get("client_name") or "").strip() or "there"
    address = (data.get("address") or "your property").strip()
    city    = (data.get("city") or "").strip()
    state   = (data.get("state") or "").strip()
    where   = ", ".join(p for p in [city, state] if p)
    prop    = f"{address}, {where}" if where else address
    link    = f"{BASE_URL}/download/{order_id}"

    text_body = f"""Hi {name},

Your short-term rental underwriting report for {prop} is attached.

It covers three revenue scenarios, a 5-year pro forma, risk assessment,
and a Buy/Watch/Pass verdict.

You can also view it online any time:
{link}

Order reference: {order_id}

Questions about anything in the report? Just reply to this email.

— {BRAND_NAME}
{BASE_URL}
"""

    html_body = f"""<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#2a2a28;">
<p>Hi {name},</p>
<p>Your short-term rental underwriting report for <strong>{prop}</strong> is attached.</p>
<p>It covers three revenue scenarios, a 5-year pro forma, risk assessment, and a Buy/Watch/Pass verdict.</p>
<p><a href="{link}" style="display:inline-block;background:#c84b2f;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:4px;">View Your Report Online</a></p>
<p style="color:#7a7870;font-size:13px;">Order reference: {order_id}</p>
<p>Questions about anything in the report? Just reply to this email.</p>
<p style="color:#7a7870;font-size:13px;">— {BRAND_NAME}<br><a href="{BASE_URL}" style="color:#7a7870;">{BASE_URL}</a></p>
</div>"""

    attachment = base64.b64encode(report_html.encode("utf-8")).decode("ascii")

    payload = {
        "from": FROM_EMAIL,
        "to": [to_addr],
        "subject": f"Your STR underwriting report — {address}",
        "text": text_body,
        "html": html_body,
        "attachments": [
            {"filename": f"STR-Report-{order_id}.html", "content": attachment}
        ],
    }
    if REPLY_TO:
        payload["reply_to"] = REPLY_TO

    ok = _resend_send(payload, order_id, f"report to {to_addr}")

    if ok and ADMIN_EMAIL:
        _resend_send(
            {
                "from": FROM_EMAIL,
                "to": [ADMIN_EMAIL],
                "subject": f"New report sold — {address}",
                "text": (f"Order {order_id}\nBuyer: {name} <{to_addr}>\n"
                         f"Property: {prop}\nReport: {link}\n"),
            },
            order_id,
            "admin notice",
        )

    return ok


def _fulfill_order(order_id):
    """Generate the report if needed and email it. Idempotent.

    Safe to call from the webhook, the success page, or check_status —
    whichever happens first does the work; later calls are no-ops.
    """
    if not order_id:
        return False
    json_path   = PENDING_DIR / f"{order_id}.json"
    report_path = REPORTS_DIR / f"{order_id}.html"
    sent_marker = REPORTS_DIR / f"{order_id}.sent"

    if not json_path.exists():
        print(f"[fulfill] {order_id}: no pending deal found")
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if report_path.exists():
        report_html = report_path.read_text(encoding="utf-8")
    else:
        report_html = generate_html_report(data)
        report_path.write_text(report_html, encoding="utf-8")
        print(f"[fulfill] {order_id}: report generated")

    if not sent_marker.exists():
        if _send_report_email(data, order_id, report_html):
            sent_marker.write_text(datetime.utcnow().isoformat(), encoding="utf-8")

    return True


# ── Existing routes ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", brand_name=BRAND_NAME)

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        form_data = request.form.to_dict()
        order_id = str(uuid.uuid4())[:8]
        with open(PENDING_DIR / f"{order_id}.json", "w") as f:
            json.dump(form_data, f)
        checkout_session = stripe.checkout.Session.create(
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='payment',
            client_reference_id=order_id,
            success_url=url_for('success', order_id=order_id, _external=True),
            cancel_url=url_for('index', _external=True),
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        print(f"Checkout Error: {e}")
        return "Error creating checkout session", 500

@app.route("/success")
def success():
    order_id = request.args.get("order_id")
    try:
        _fulfill_order(order_id)
    except Exception as e:
        print(f"Generation Error: {e}")
        traceback.print_exc()
        return "Error generating report", 500
    return render_template("success.html", order_id=order_id, brand_name=BRAND_NAME)

@app.route("/download/<order_id>")
def download(order_id):
    path = REPORTS_DIR / f"{order_id}.html"
    if not path.exists(): abort(404)
    return send_file(path)

@app.route("/check_status/<order_id>")
def check_status(order_id):
    if (REPORTS_DIR / f"{order_id}.html").exists():
        return jsonify({"status": "ready"})
    try:
        if _fulfill_order(order_id):
            return jsonify({"status": "ready"})
    except Exception as e:
        print(f"check_status generation error: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "pending"})


# ── Stripe webhook ────────────────────────────────────────────────────────────
@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Fulfil on payment confirmation, not on the customer returning to the site.

    Without this, a buyer who closes the tab at Stripe's confirmation screen
    has paid and never receives anything.
    """
    payload    = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        print("[webhook] STRIPE_WEBHOOK_SECRET not set, refusing")
        return "Webhook not configured", 500

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        print("[webhook] signature verification failed")
        return "Invalid signature", 400

    if event["type"] == "checkout.session.completed":
        session  = event["data"]["object"]
        order_id = session.get("client_reference_id")
        print(f"[webhook] checkout.session.completed for order {order_id}")
        try:
            _fulfill_order(order_id)
        except Exception as e:
            print(f"[webhook] fulfilment failed for {order_id}: {e}")
            traceback.print_exc()
            # 500 tells Stripe to retry.
            return "Fulfilment error", 500

    return jsonify({"received": True}), 200

# ── Sample report routes ──────────────────────────────────────────────────────
@app.route("/sample-report")
def sample_report_us():
    path = SAMPLES_DIR / "sample_us.html"
    if not path.exists(): abort(404)
    return send_file(path)

@app.route("/sample-report-caribbean")
def sample_report_caribbean():
    path = SAMPLES_DIR / "sample_caribbean.html"
    if not path.exists(): abort(404)
    return send_file(path)

# ── Markets routes ────────────────────────────────────────────────────────────
@app.route("/markets")
def markets():
    return render_template(
        "markets_gallery.html",
        markets=MARKETS,
        brand_name=BRAND_NAME,
        active_page="markets",
    )

@app.route("/markets/<slug>")
def market_detail(slug):
    market = MARKETS.get(slug)
    if not market:
        abort(404)
    return render_template(
        "market_detail.html",
        market=market,
        slug=slug,
        blog_posts=BLOG_POSTS,
        brand_name=BRAND_NAME,
        active_page="markets",
    )

# ── Blog routes ───────────────────────────────────────────────────────────────
def _blog_date_display(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")

@app.route("/blog")
def blog_index():
    posts = []
    for slug, post in BLOG_POSTS.items():
        posts.append({
            "slug": slug,
            "title": post["title"],
            "excerpt": post["excerpt"],
            "category": post["category"],
            "date": post["date"],
            "date_display": _blog_date_display(post["date"]),
        })
    posts.sort(key=lambda p: p["date"], reverse=True)
    return render_template(
        "blog.html",
        posts=posts,
        brand_name=BRAND_NAME,
        active_page="blog",
    )

@app.route("/blog/<slug>")
def blog_post(slug):
    post_data = BLOG_POSTS.get(slug)
    if not post_data:
        abort(404)
    post = dict(post_data)
    post["slug"] = slug
    post["date_display"] = _blog_date_display(post["date"])
    return render_template(
        "blog_post.html",
        post=post,
        brand_name=BRAND_NAME,
        active_page="blog",
    )

# ── Analytics page ────────────────────────────────────────────────────────────
@app.route("/analytics")
def analytics():
    return render_template(
        "analytics.html",
        brand_name=BRAND_NAME,
        active_page="analytics",
    )

# ── Market Analysis API proxy (keeps Anthropic key server-side) ───────────────
@app.route("/api/market-analysis", methods=["POST"])
def market_analysis_api():
    try:
        body        = request.get_json()
        market_name = body.get("market", "")
        bedrooms    = body.get("bedrooms", "2")
        prop_type   = body.get("prop_type", "Villa")
        is_caribbean = body.get("is_caribbean", True)

        if not market_name:
            return jsonify({"error": "market is required"}), 400

        prompt = f"""You are a professional STR underwriter specializing in Caribbean and US coastal vacation rentals.

Generate realistic, investor-grade STR market data for: {market_name}, {bedrooms} bedroom {prop_type}.
{"This is a Caribbean/international market — factor in tourism seasonality, USD pricing, foreign ownership rules, and local tax incentives where applicable." if is_caribbean else "This is a US coastal market — factor in domestic tourism patterns, state regulations, and HOA/rental restrictions."}

Respond ONLY with valid JSON, no markdown, no backticks:
{{
  "market": "Full Market Name",
  "adr": 285,
  "occupancy": 71,
  "monthly_revenue": 6100,
  "annual_revenue": 73200,
  "revpan": 202,
  "roi_score": 78,
  "verdict": "BUY",
  "total_listings": 410,
  "avg_rating": 4.82,
  "peak_season": "December–April",
  "low_season": "September–October",
  "market_trend": "Growing",
  "cap_rate_est": 7.2,
  "cash_on_cash_est": 9.1,
  "regulatory_notes": "One sentence on key STR rules or tax incentives.",
  "currency_note": "USD",
  "seasonal_occupancy": [78,80,72,65,60,55,52,50,42,48,68,82],
  "top_amenities": ["Private Pool","Ocean View","AC","Beach Access","Concierge"],
  "risk_factors": ["Hurricane Season Sep–Oct","Foreign Ownership Restrictions","Currency Risk"],
  "summary": "2 sentences of investor-grade market insight with specific data points.",
  "buy_rationale": "One sentence explaining the verdict."
}}"""

        client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message  = client.messages.create(
            model      = "claude-opus-4-5",
            max_tokens = 1024,
            messages   = [{"role": "user", "content": prompt}]
        )

        raw  = message.content[0].text
        clean = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)
        return jsonify(data)

    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return jsonify({"error": "Failed to parse AI response"}), 500
    except Exception as e:
        print(f"Market analysis error: {e}")
        return jsonify({"error": str(e)}), 500

# ── SEO routes ────────────────────────────────────────────────────────────────
@app.route("/sitemap.xml")
def sitemap():
    urls = [
        ("https://caribbeanstr.com/", "weekly", "1.0"),
        ("https://caribbeanstr.com/markets", "weekly", "0.9"),
        ("https://caribbeanstr.com/analytics", "weekly", "0.9"),
        ("https://caribbeanstr.com/blog", "weekly", "0.8"),
        ("https://caribbeanstr.com/sample-report", "monthly", "0.8"),
        ("https://caribbeanstr.com/sample-report-caribbean", "monthly", "0.8"),
    ]
    for slug in MARKETS:
        urls.append((f"https://caribbeanstr.com/markets/{slug}", "monthly", "0.7"))
    for slug in BLOG_POSTS:
        urls.append((f"https://caribbeanstr.com/blog/{slug}", "monthly", "0.6"))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for loc, freq, priority in urls:
        xml += f'  <url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{priority}</priority></url>\n'
    xml += '</urlset>'
    return xml, 200, {'Content-Type': 'application/xml'}

@app.route("/robots.txt")
def robots():
    txt = "User-agent: *\nAllow: /\nSitemap: https://caribbeanstr.com/sitemap.xml\n"
    return txt, 200, {'Content-Type': 'text/plain'}

if __name__ == "__main__":
    app.run(debug=True)
