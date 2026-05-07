#!/usr/bin/env python3
"""
STR Underwriter — Self-Service Web Platform
=============================================
Flask app: Form intake → Stripe payment → Auto-generate report → Email delivery.

Usage:
    python3 app.py                                          # dev mode
    gunicorn app:app --bind 0.0.0.0:8000 --workers 2       # production
"""

import os, json, uuid, smtplib, math
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from flask import (Flask, render_template, request, redirect,
                   jsonify, url_for, send_file)
from dotenv import load_dotenv
import stripe

load_dotenv()
app = Flask(__name__)
from markets import markets_bp
app.register_blueprint(markets_bp, url_prefix="/markets")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

# ── Config ───────────────────────────────────────────────────────────────────
stripe.api_key        = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUB_KEY        = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID       = os.getenv("STRIPE_PRICE_ID")

SMTP_HOST   = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER   = os.getenv("SMTP_USER")
SMTP_PASS   = os.getenv("SMTP_PASS")
FROM_EMAIL  = os.getenv("FROM_EMAIL", SMTP_USER or "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
BASE_URL    = os.getenv("BASE_URL", "http://localhost:5000")
BRAND_NAME  = os.getenv("BRAND_NAME", "Caribbean STR")
BRAND_URL   = os.getenv("BRAND_URL", "caribbeanstr.com")

REPORTS_DIR = Path("generated_reports"); REPORTS_DIR.mkdir(exist_ok=True)
PENDING_DIR = Path("pending_orders");    PENDING_DIR.mkdir(exist_ok=True)

# ── Import report engine ────────────────────────────────────────────────────
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "generate_report", str(Path(__file__).parent / "generate_report.py"))
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

# ── Revenue defaults by market tier × bedrooms ──────────────────────────────
REVENUE_DEFAULTS = {
    "coastal_premium":  {1:{"pa":325,"oa":120,"po":0.85,"oo":0.20,"g":35000},2:{"pa":425,"oa":145,"po":0.90,"oo":0.20,"g":45000},3:{"pa":550,"oa":185,"po":0.90,"oo":0.22,"g":62000},4:{"pa":700,"oa":225,"po":0.88,"oo":0.18,"g":80000},5:{"pa":850,"oa":275,"po":0.85,"oo":0.15,"g":100000}},
    "coastal_standard": {1:{"pa":250,"oa":100,"po":0.80,"oo":0.18,"g":28000},2:{"pa":350,"oa":125,"po":0.85,"oo":0.18,"g":38000},3:{"pa":450,"oa":160,"po":0.85,"oo":0.20,"g":52000},4:{"pa":575,"oa":195,"po":0.82,"oo":0.16,"g":68000},5:{"pa":700,"oa":235,"po":0.80,"oo":0.15,"g":85000}},
    "mountain":         {1:{"pa":225,"oa":125,"po":0.80,"oo":0.30,"g":32000},2:{"pa":325,"oa":165,"po":0.82,"oo":0.32,"g":45000},3:{"pa":425,"oa":200,"po":0.80,"oo":0.30,"g":58000},4:{"pa":550,"oa":250,"po":0.78,"oo":0.28,"g":72000},5:{"pa":700,"oa":300,"po":0.75,"oo":0.25,"g":88000}},
    "urban":            {1:{"pa":175,"oa":120,"po":0.75,"oo":0.55,"g":38000},2:{"pa":250,"oa":165,"po":0.78,"oo":0.55,"g":52000},3:{"pa":350,"oa":225,"po":0.75,"oo":0.50,"g":65000},4:{"pa":450,"oa":300,"po":0.72,"oo":0.48,"g":80000},5:{"pa":550,"oa":375,"po":0.70,"oo":0.45,"g":95000}},
    "lake":             {1:{"pa":225,"oa":110,"po":0.82,"oo":0.22,"g":30000},2:{"pa":325,"oa":140,"po":0.85,"oo":0.22,"g":42000},3:{"pa":425,"oa":175,"po":0.82,"oo":0.20,"g":55000},4:{"pa":550,"oa":215,"po":0.80,"oo":0.18,"g":70000},5:{"pa":675,"oa":260,"po":0.78,"oo":0.15,"g":85000}},
    "rural":            {1:{"pa":150,"oa":85, "po":0.70,"oo":0.25,"g":22000},2:{"pa":225,"oa":110,"po":0.72,"oo":0.25,"g":30000},3:{"pa":300,"oa":140,"po":0.70,"oo":0.22,"g":40000},4:{"pa":400,"oa":175,"po":0.68,"oo":0.20,"g":52000},5:{"pa":500,"oa":210,"po":0.65,"oo":0.18,"g":65000}},
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _monthly_projections(beds, tier):
    d = REVENUE_DEFAULTS.get(tier, REVENUE_DEFAULTS["coastal_standard"]).get(
        min(beds, 5), REVENUE_DEFAULTS["coastal_standard"][2])
    pa, oa = d["pa"], d["oa"]
    po, oo = d["po"], d["oo"]
    sa, so = round((pa+oa)/2), round((po+oo)/2, 2)
    return [
        {"month":"January",  "adr":oa,              "occupancy":oo,                     "season":"off"},
        {"month":"February", "adr":round(oa*1.02),   "occupancy":round(oo*0.9,2),        "season":"off"},
        {"month":"March",    "adr":round(sa*0.82),   "occupancy":round(so*0.80,2),       "season":"shoulder"},
        {"month":"April",    "adr":round(sa*0.93),   "occupancy":round(so*1.0,2),        "season":"shoulder"},
        {"month":"May",      "adr":round(sa*1.12),   "occupancy":min(round(so*1.20,2),0.95),"season":"shoulder"},
        {"month":"June",     "adr":round(pa*0.94),   "occupancy":round(po*0.94,2),       "season":"peak"},
        {"month":"July",     "adr":pa,               "occupancy":po,                     "season":"peak"},
        {"month":"August",   "adr":round(pa*0.89),   "occupancy":round(po*0.89,2),       "season":"peak"},
        {"month":"September","adr":round(sa*1.03),   "occupancy":so,                     "season":"shoulder"},
        {"month":"October",  "adr":round(sa*0.86),   "occupancy":round(so*0.80,2),       "season":"shoulder"},
        {"month":"November", "adr":round(oa*1.10),   "occupancy":round(oo*1.10,2),       "season":"off"},
        {"month":"December", "adr":round(oa*1.07),   "occupancy":oo,                     "season":"off"},
    ]

AMENITY_MAP = {
    "outdoor_pool": {"icon":"🏊","name":"Outdoor Pool","detail":"Seasonal community access"},
    "indoor_pool":  {"icon":"🏊‍♂️","name":"Heated Indoor Pool","detail":"Year-round access"},
    "hot_tub":      {"icon":"🛁","name":"Hot Tub / Spa","detail":"Community access"},
    "gym":          {"icon":"💪","name":"Fitness Center","detail":"Full gymnasium"},
    "tennis":       {"icon":"🎾","name":"Tennis / Pickleball","detail":"Dedicated courts"},
    "basketball":   {"icon":"🏀","name":"Basketball Court","detail":"Full court"},
    "beach_access": {"icon":"🏖️","name":"Beach Access","detail":"Community walkways"},
    "playground":   {"icon":"🛝","name":"Playground","detail":"Children's play area"},
    "boat_dock":    {"icon":"🚤","name":"Boat Dock","detail":"Water access"},
    "grill_area":   {"icon":"🔥","name":"Grill / Fire Pit","detail":"Outdoor cooking area"},
}


def build_deal_json(form):
    """Convert a Flask form submission into a complete deal_data dict."""
    beds     = int(form.get("bedrooms", 2))
    baths    = int(form.get("bathrooms", 2))
    price    = int(form.get("purchase_price", 300000))
    down_pct = float(form.get("down_payment_pct", 25)) / 100
    rate     = float(form.get("interest_rate", 7)) / 100
    term     = int(form.get("loan_term", 30))
    hoa      = int(form.get("hoa_annual", 0))
    hoa_ins  = form.get("hoa_includes_insurance") == "yes"
    tier     = form.get("market_type", "coastal_standard")
    city     = form.get("city", "")
    state    = form.get("state", "")
    country  = form.get("country", "US")
    address  = form.get("address", "")
    community = form.get("community", "")

    # ── Location formatting for international support ───────────────────
    COUNTRY_NAMES = {
        "US": "United States", "USVI": "U.S. Virgin Islands",
        "PR": "Puerto Rico", "DO": "Dominican Republic",
        "BS": "Bahamas", "TC": "Turks & Caicos",
        "JM": "Jamaica", "KY": "Cayman Islands",
        "BB": "Barbados", "MX": "Mexico",
        "BZ": "Belize", "CR": "Costa Rica",
        "PA": "Panama", "CO": "Colombia",
    }
    country_name = COUNTRY_NAMES.get(country, country)
    is_us = country in ("US", "USVI", "PR")
    if is_us:
        area_name = f"{city}, {state}"
    else:
        area_name = f"{city}, {country_name}"
    year_built = int(form.get("year_built", 2005))

    d = REVENUE_DEFAULTS.get(tier, REVENUE_DEFAULTS["coastal_standard"]).get(
        min(beds, 5), REVENUE_DEFAULTS["coastal_standard"][2])
    base_gross = d["g"]
    custom = form.get("custom_gross_revenue", "").strip().replace(",","").replace("$","")
    if custom:
        try: base_gross = int(custom)
        except ValueError: pass

    # Amenities
    amenities = []
    for key in form.getlist("amenities"):
        if key in AMENITY_MAP:
            amenities.append(AMENITY_MAP[key])
    for a in (form.get("custom_amenities","") or "").split(","):
        a = a.strip()
        if a:
            amenities.append({"icon":"✨","name":a,"detail":""})

    amenity_narrative = ""
    if amenities:
        names = ", ".join(x["name"] for x in amenities[:6])
        amenity_narrative = (f"The property features {names} — amenities that "
                             f"position it as a premium rental, supporting higher "
                             f"nightly rates and repeat bookings.")

    # Expenses
    prop_tax = round(price * 0.0085)
    expenses = []
    if hoa > 0:
        nm = "HOA dues (incl. insurance)" if hoa_ins else "HOA dues"
        nt = ("Covers insurance, exterior maintenance, and amenities"
              if hoa_ins else "Monthly association dues")
        expenses.append({"name": nm, "annual": hoa, "notes": nt})
    if not hoa_ins:
        ins = round(price * 0.008) + 1200
        expenses.append({"name":"Insurance (hazard + flood)","annual":ins,
                         "notes":"Homeowner's + flood policy"})
    expenses += [
        {"name":"Property tax",             "annual":prop_tax, "notes":f"Est. ~{prop_tax/price*100:.2f}%"},
        {"name":"Utilities (electric, water)","annual":round(1200+beds*600),"notes":"HVAC, water, guest usage"},
        {"name":"Internet / WiFi",          "annual":960,      "notes":"High-speed required"},
        {"name":"Repairs & maintenance",    "annual":round(1000+beds*250),"notes":"Appliance, HVAC, fixes"},
        {"name":"Furnishing reserve",       "annual":round(500+beds*125),"notes":"Annual refresh set-aside"},
        {"name":"STR permit & license",     "annual":100,      "notes":"Annual registration"},
        {"name":"Accounting / tax prep",    "annual":500,      "notes":"STR-specific CPA"},
        {"name":"Miscellaneous",            "annual":500,      "notes":"Contingency"},
    ]

    # Risks
    age = 2026 - year_built
    risks = [
        {"name":"Seasonality / cash flow gaps","severity":"red",
         "note":"Off-season revenue may fall below monthly costs. Build a 3–4 month reserve."},
    ]
    if community:
        risks.append({"name":"HOA rule changes","severity":"amber",
         "note":f"{community} HOA could restrict STRs. Review CC&Rs before closing."})
    risks += [
        {"name":"Weather / natural disaster","severity":"amber",
         "note":"Verify insurance coverage and budget for rising premiums."},
        {"name":"STR regulation","severity":"green",
         "note":"Research current local STR regulations and monitor for changes."},
        {"name":"Building age / maintenance",
         "severity":"amber" if age > 15 else "green",
         "note":f"Built {year_built} ({age} yrs). {'Major systems may need replacement.' if age>15 else 'Lower near-term risk.'}"},
        {"name":"Interest rate risk","severity":"green",
         "note":"Fixed-rate mortgage eliminates rate exposure."},
        {"name":"Legal / ownership","severity":"green",
         "note":"Review governing docs for rental restrictions before closing."},
    ]

    features = []
    for k, v in [("has_balcony","Balcony"),("has_washer_dryer","In-Unit W/D"),
                  ("has_wet_bar","Wet Bar")]:
        if form.get(k) == "yes": features.append(v)
    custom_feat = form.get("special_features","").strip()
    if custom_feat:
        features += [f.strip() for f in custom_feat.split(",") if f.strip()]

    order_id = uuid.uuid4().hex[:8].upper()
    today = datetime.now()

    deal = {
        "meta": {
            "report_number": f"{today.strftime('%Y-%m-%d')}-{order_id}",
            "date": today.strftime("%m/%d/%Y"),
            "prepared_for": form.get("customer_name","Client"),
            "brand_name": BRAND_NAME,
            "brand_tagline": "Professional STR Underwriting",
            "brand_url": BRAND_URL,
        },
        "property": {
            "address": address, "city": city, "state": state,
            "zip": form.get("zip",""), "country": country, "country_name": country_name,
            "community": community, "type": form.get("property_type","Condominium"),
            "bedrooms": beds, "bathrooms": baths, "sqft": int(form.get("sqft",1000)),
            "year_built": year_built, "condition": form.get("condition","Furnished, Turn-Key"),
            "access": form.get("access","Standard"),
            "parking": form.get("parking","Assigned"),
            "beach_access": form.get("beach_access","N/A"),
            "special_features": ", ".join(features),
            "hvac": form.get("hvac","Central Air"),
            "flooring": form.get("flooring","Mixed"),
        },
        "amenities": amenities,
        "amenity_narrative": amenity_narrative,
        "financing": {
            "purchase_price": price, "down_payment_pct": down_pct,
            "interest_rate": rate, "loan_term_years": term,
            "closing_cost_pct": 0.03, "permit_fee": 100, "initial_setup": 1500,
        },
        "revenue": {
            "monthly_projections": _monthly_projections(beds, tier),
            "platform_fee_pct": 0.055,
            "cleaning_cost_per_turn": 80 + beds * 15,
            "avg_stay_nights": 4,
        },
        "scenarios": {
            "conservative": {"occupancy":round(d["po"]*0.65,2),"blended_adr":round(d["pa"]*0.55),"gross_revenue":round(base_gross*0.80),"label":"Downside"},
            "base":         {"occupancy":round((d["po"]+d["oo"])/2,2),"blended_adr":round((d["pa"]+d["oa"])/2),"gross_revenue":base_gross,"label":"Base"},
            "optimistic":   {"occupancy":round(d["po"]*0.85,2),"blended_adr":round(d["pa"]*0.75),"gross_revenue":round(base_gross*1.20),"label":"Upside"},
        },
        "expenses": expenses,
        "appreciation_rate": 0.03, "expense_inflation_rate": 0.03,
        "revenue_growth_rate": 0.03, "building_value_pct": 0.80,
        "depreciation_years": 27.5, "marginal_tax_rate": 0.22,
        "projection_years": 5,
        "market": {
            "area_name": area_name,
            "median_home_value": round(price * 1.5),
            "sources": [{"name":"Market Estimate","listings":None,
                         "adr":round((d["pa"]+d["oa"])/2),
                         "occupancy":round((d["po"]+d["oo"])/2,2),
                         "annual_rev":base_gross,"rev_growth":None,"revpar":None}],
            "deal_narrative": f"This {beds}BR {form.get('property_type','property').lower()} in {area_name} is evaluated as an STR investment at ${price:,}. Self-managed via Airbnb and VRBO.",
            "revenue_narrative": f"Base case: ${base_gross:,} annual gross revenue for {beds}BR units in {area_name}.",
            "dynamics_narrative": f"The {area_name} STR market serves vacation and business travelers. Dual-platform listing maximizes exposure.",
        },
        "management": {
            "platform_narrative": f"Dual-list on Airbnb (3% host fee) and VRBO (8% host fee). Self-management saves ~${round(base_gross*0.20):,}/yr vs. a property manager.",
            "ops_narrative": "Local cleaning team, smart lock, noise monitoring, dynamic pricing tool, guest automation, professional photography.",
            "optimization_narrative": "Dynamic pricing, seasonal minimum stays, professional photos, Superhost/Premier Host targeting.",
            "pm_fee_pct": 0.20,
        },
        "risks": risks,
        "tax": {
            "occupancy_tax_narrative": "Check local occupancy tax. Major platforms typically collect and remit automatically.",
            "property_tax_narrative": f"Est. ${prop_tax:,}/yr. Verify with county tax assessor.",
            "income_tax_narrative": "Report on Schedule E or C. Consult a CPA.",
            "depreciation_narrative": f"Building (~80% of ${price:,} = ${round(price*0.80):,}) / 27.5 yrs = ~${round(price*0.80/27.5):,}/yr.",
            "fourteen_day_rule": "Personal use >14 days or >10% of rental days may limit deductions.",
            "interest_deduction_note": "Mortgage interest is deductible against rental income.",
        },
        "regulatory": {
            "permit_required": True, "permit_cost": 100,
            "processing_time": "Varies", "night_limit": "Check local",
            "primary_residence_required": False,
            "occupancy_limit": f"2/bedroom + 2", "max_guests_this_unit": beds*2+2,
            "local_contact_required": True, "local_contact_response": "within 1 hour",
            "safety_requirements": "Post exit routes; fire/smoke detectors required",
            "parking_requirement": "Verify local requirements",
            "regulation_level": "Research local ordinances",
            "tax_collection": "Check if platforms auto-collect",
            "checklist": [
                {"requirement":"STR Registration","action":"Apply with local planning dept"},
                {"requirement":"Safety Inspection","action":"Schedule before first guest"},
                {"requirement":"Emergency Info","action":"Post in unit"},
                {"requirement":"Local Contact","action":"Designate 24/7 contact"},
                {"requirement":"HOA Review","action":"Verify STRs permitted"},
                {"requirement":"Liability Insurance","action":"Consider supplemental coverage"},
            ],
        },
        "comps": [],
        "next_steps": [
            "Review HOA CC&Rs to confirm STRs are permitted.",
            "Schedule a property inspection (HVAC, appliances, deferred maintenance).",
            "Get rental projections from local STR operators for validation.",
            "Register for an STR permit and complete safety inspections.",
            "Set up dual Airbnb + VRBO listings with professional photography.",
            f"Build a ${round(base_gross*0.25):,} liquid reserve for off-season gaps.",
            "Engage an STR-specialized CPA for depreciation and tax strategy.",
        ],
        "disclaimer": ("This report is for informational purposes only and does not "
                        "constitute investment, legal, or tax advice. Actual results "
                        "may vary. Consult qualified professionals before investing."),
    }
    return deal, order_id


def generate_report_files(deal_data, order_id):
    html = engine.generate_report(deal_data)
    html_path = REPORTS_DIR / f"{order_id}.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = None
    try:
        from weasyprint import HTML as WP
        pdf_path = REPORTS_DIR / f"{order_id}.pdf"
        WP(string=html).write_pdf(str(pdf_path))
    except ImportError:
        pass
    return html_path, pdf_path


def send_report_email(email, name, order_id, address, html_path, pdf_path):
    if not SMTP_USER or not SMTP_PASS:
        print(f"[WARN] SMTP not configured — skipping email for {order_id}")
        return False
    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg["Subject"] = f"Your STR Underwriting Report — {address}"
    body = (f"Hi {name},\n\n"
            f"Your STR Underwriting Report for {address} is ready!\n\n"
            f"Download: {BASE_URL}/download/{order_id}\n\n"
            f"Thank you for choosing {BRAND_NAME}!\n")
    msg.attach(MIMEText(body, "plain"))
    ap = pdf_path if pdf_path and pdf_path.exists() else html_path
    ext = "pdf" if pdf_path and pdf_path.exists() else "html"
    with open(ap, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f"attachment; filename=STR Report - {address}.{ext}")
        msg.attach(part)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
        return True
    except Exception as e:
        print(f"[ERROR] Email failed: {e}"); return False


def notify_admin(order_id, email, name, address, price):
    if not ADMIN_EMAIL or not SMTP_USER: return
    try:
        msg = MIMEText(
            f"New STR report order!\n\nOrder: {order_id}\n"
            f"Customer: {name} ({email})\nProperty: {address}\n"
            f"Price: ${price:,}\nTime: {datetime.now():%Y-%m-%d %H:%M}\n")
        msg["From"] = FROM_EMAIL
        msg["To"]   = ADMIN_EMAIL
        msg["Subject"] = f"[{BRAND_NAME}] New Report: {address}"
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)
    except Exception as e:
        print(f"[WARN] Admin notify failed: {e}")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
                           stripe_key=STRIPE_PUB_KEY,
                           brand_name=BRAND_NAME)


@app.route("/markets/aruba")
def market_aruba():
    return render_template("aruba.html")


@app.route("/sample-report")
def sample_report():
    return send_file("static/sample-report.html")


@app.route("/sample-report-caribbean")
def sample_report_caribbean():
    return send_file("static/sample-report-caribbean.html")


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout():
    try:
        deal_data, order_id = build_deal_json(request.form)
        # Persist order data for post-payment generation
        (PENDING_DIR / f"{order_id}.json").write_text(
            json.dumps({"deal_data": deal_data,
                         "customer_email": request.form.get("email"),
                         "customer_name": request.form.get("customer_name","Client"),
                         "address": request.form.get("address"),
                         "created_at": datetime.now().isoformat()},
                        indent=2), encoding="utf-8")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="payment",
            customer_email=request.form.get("email"),
            metadata={"order_id": order_id},
            success_url=f"{BASE_URL}/success?order_id={order_id}",
            cancel_url=f"{BASE_URL}/?cancelled=true",
        )
        return redirect(session.url, code=303)
    except Exception as e:
        print(f"[ERROR] Checkout failed: {e}")
        return redirect(url_for("index", error="payment_failed"))


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    try:
        event = stripe.Webhook.construct_event(
            request.get_data(as_text=True),
            request.headers.get("Stripe-Signature"),
            STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "Bad request", 400

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        order_id = sess.get("metadata", {}).get("order_id")
        if order_id:
            pp = PENDING_DIR / f"{order_id}.json"
            if pp.exists():
                pending = json.loads(pp.read_text(encoding="utf-8"))
                html_path, pdf_path = generate_report_files(
                    pending["deal_data"], order_id)
                send_report_email(
                    pending.get("customer_email") or sess.get("customer_email",""),
                    pending.get("customer_name","Client"),
                    order_id, pending.get("address","Property"),
                    html_path, pdf_path)
                notify_admin(order_id,
                             pending.get("customer_email",""),
                             pending.get("customer_name",""),
                             pending.get("address",""),
                             pending["deal_data"]["financing"]["purchase_price"])
                pending["status"] = "completed"
                pp.write_text(json.dumps(pending, indent=2), encoding="utf-8")

    return jsonify(status="ok"), 200


@app.route("/success")
def success():
    order_id = request.args.get("order_id", "")
    address = "your property"
    pp = PENDING_DIR / f"{order_id}.json"
    if pp.exists():
        pending = json.loads(pp.read_text(encoding="utf-8"))
        address = pending.get("address", address)
        # Synchronous fallback if webhook hasn't fired yet
        rp = REPORTS_DIR / f"{order_id}.html"
        if not rp.exists():
            generate_report_files(pending["deal_data"], order_id)
    return render_template("success.html",
                           order_id=order_id, address=address,
                           brand_name=BRAND_NAME)


@app.route("/download/<order_id>")
def download_report(order_id):
    # Prefer PDF, fall back to HTML
    for ext in ("pdf", "html"):
        p = REPORTS_DIR / f"{order_id}.{ext}"
        if p.exists():
            return send_file(p, as_attachment=True,
                             download_name=f"STR Report - {order_id}.{ext}")
    return "Report not found", 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
