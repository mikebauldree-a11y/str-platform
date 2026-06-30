import os, json, uuid

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

BASE_DIR = Path(__file__).parent
PENDING_DIR = BASE_DIR / "pending_deals"
REPORTS_DIR = BASE_DIR / "reports"
SAMPLES_DIR = BASE_DIR / "samples"
for d in [PENDING_DIR, REPORTS_DIR, SAMPLES_DIR]: d.mkdir(exist_ok=True)

# ── Load markets data once at startup ────────────────────────────────────────
_markets_path = BASE_DIR / "data" / "markets.json"
with open(_markets_path, "r", encoding="utf-8") as _f:
    MARKETS = json.load(_f)

# ── Load blog posts once at startup ──────────────────────────────────────────
_blog_posts_path = BASE_DIR / "data" / "blog_posts.json"
with open(_blog_posts_path, "r", encoding="utf-8") as _f:
    BLOG_POSTS = json.load(_f)

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
