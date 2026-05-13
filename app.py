import os, json, uuid
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, send_file, abort, jsonify
from dotenv import load_dotenv
import stripe
from generate_report import generate_html_report

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-key-123")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")

BASE_DIR = Path(__file__).parent
PENDING_DIR = BASE_DIR / "pending_deals"
REPORTS_DIR = BASE_DIR / "reports"
SAMPLES_DIR = BASE_DIR / "samples"
for d in [PENDING_DIR, REPORTS_DIR, SAMPLES_DIR]: d.mkdir(exist_ok=True)

# ── Load markets data once at startup ────────────────────────────────────────
_markets_path = BASE_DIR / "data" / "markets.json"
with open(_markets_path, "r", encoding="utf-8") as _f:
    MARKETS = json.load(_f)

BRAND_NAME = "Caribbean STR"


# ── Existing routes (unchanged) ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", brand_name=BRAND_NAME)

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        form_data = request.form.to_dict()
        order_id = str(uuid.uuid4())[:8]

        # Save input data immediately
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
    json_path = PENDING_DIR / f"{order_id}.json"
    report_path = REPORTS_DIR / f"{order_id}.html"

    if json_path.exists() and not report_path.exists():
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            html_out = generate_html_report(data)
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(html_out)
        except Exception as e:
            print(f"Generation Error: {e}")
            return "Error generating report", 500

    return render_template("success.html", order_id=order_id, brand_name=BRAND_NAME)

@app.route("/download/<order_id>")
def download(order_id):
    path = REPORTS_DIR / f"{order_id}.html"
    if not path.exists(): abort(404)
    return send_file(path)

@app.route("/check_status/<order_id>")
def check_status(order_id):
    report_path = REPORTS_DIR / f"{order_id}.html"
    if report_path.exists():
        return jsonify({"status": "ready"})
    # Report not yet on disk — try to generate it now (handles race where
    # success page loads before generation has finished)
    json_path = PENDING_DIR / f"{order_id}.json"
    if json_path.exists():
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            html_out = generate_html_report(data)
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(html_out)
            return jsonify({"status": "ready"})
        except Exception as e:
            print(f"check_status generation error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "pending"})


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
        brand_name=BRAND_NAME,
        active_page="markets",
    )


# ── SEO routes ────────────────────────────────────────────────────────────────

@app.route("/sitemap.xml")
def sitemap():
    urls = [
        ("https://caribbeanstr.com/", "weekly", "1.0"),
        ("https://caribbeanstr.com/markets", "weekly", "0.9"),
        ("https://caribbeanstr.com/sample-report", "monthly", "0.8"),
        ("https://caribbeanstr.com/sample-report-caribbean", "monthly", "0.8"),
    ]
    for slug in MARKETS:
        urls.append((f"https://caribbeanstr.com/markets/{slug}", "monthly", "0.7"))

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