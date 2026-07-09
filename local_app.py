"""
local_app.py — Run the Caribbean STR report engine on your own MacBook,
for properties YOU are personally underwriting (no Stripe checkout, no
payment, no data leaving your machine).

This reuses the exact same form (templates/index.html) and the exact
same report engine (generate_report.py -> generate_html_report) that
powers the live "Start Analysis" button on caribbeanstr.com — it just
skips the Stripe checkout step and renders the report immediately.

Run it:
    pip3 install flask python-dotenv
    python3 local_app.py

Then open:
    http://127.0.0.1:5050

Every report you generate is also saved to local_reports/ so you can
revisit past analyses.
"""

import re
import uuid
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, Response

from generate_report import generate_html_report

app = Flask(__name__)
app.secret_key = "local-dev-only"

BASE_DIR = Path(__file__).parent
LOCAL_REPORTS_DIR = BASE_DIR / "local_reports"
LOCAL_REPORTS_DIR.mkdir(exist_ok=True)

BRAND_NAME = "Caribbean STR"


def _safe_slug(text, fallback="property"):
    text = (text or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:40] or fallback


@app.route("/")
def index():
    # Same form the paid site uses — posts to /analyze below.
    return render_template("index.html", brand_name=BRAND_NAME)


@app.route("/analyze", methods=["POST"])
def analyze():
    form_data = request.form.to_dict()

    # Generate the report with the identical engine used in production.
    html_out = generate_html_report(form_data)

    # Save a local copy for your records.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _safe_slug(form_data.get("address") or form_data.get("client_name"))
    order_id = f"{stamp}-{slug}-{uuid.uuid4().hex[:6]}"
    report_path = LOCAL_REPORTS_DIR / f"{order_id}.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    return Response(html_out, mimetype="text/html")


@app.route("/reports")
def list_reports():
    files = sorted(LOCAL_REPORTS_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = "".join(
        f'<li style="margin-bottom:6px;"><a href="/reports/{f.name}">{f.name}</a></li>' for f in files
    )
    return f"""
    <html><body style="font-family: sans-serif; max-width: 700px; margin: 40px auto;">
    <h2>Local reports</h2>
    <p><a href="/">&larr; New analysis</a></p>
    <ul>{items or '<li>No reports yet.</li>'}</ul>
    </body></html>
    """


@app.route("/reports/<name>")
def view_report(name):
    path = LOCAL_REPORTS_DIR / name
    if not path.exists() or path.parent != LOCAL_REPORTS_DIR:
        return "Not found", 404
    return Response(path.read_text(encoding="utf-8"), mimetype="text/html")


if __name__ == "__main__":
    print("\nCaribbean STR — local analysis tool")
    print("Open http://127.0.0.1:5050 in your browser\n")
    app.run(debug=True, port=5050)
