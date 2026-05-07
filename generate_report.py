#!/usr/bin/env python3
"""
STR Underwriter — Report Generation Engine
============================================
Reads a deal_data.json file and produces a fully styled HTML underwriting report.

Usage:
    python generate_report.py deal_data.json              # writes report.html
    python generate_report.py deal_data.json my_report     # writes my_report.html
"""

import json, sys, math, html as html_mod
from pathlib import Path

# ── helpers ──────────────────────────────────────────────────────────────────

def usd(n, decimals=0):
    """Format a number as USD currency."""
    if n is None:
        return "N/A"
    neg = n < 0
    n = abs(n)
    if decimals == 0:
        s = f"{n:,.0f}"
    else:
        s = f"{n:,.{decimals}f}"
    return f"-${s}" if neg else f"${s}"

def pct(n, decimals=1):
    """Format a decimal as percentage string."""
    if n is None:
        return "N/A"
    return f"{n * 100:,.{decimals}f}%"

def pct_raw(n, decimals=1):
    """Format an already-percentage number."""
    if n is None:
        return "N/A"
    return f"{n:,.{decimals}f}%"

def na(v):
    return "N/A" if v is None else str(v)

def h(text):
    """HTML-escape text."""
    return html_mod.escape(str(text))

# ── financial calculations ───────────────────────────────────────────────────

def calc_monthly_payment(principal, annual_rate, years):
    r = annual_rate / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r)**n) / ((1 + r)**n - 1)

def calc_year1_interest(principal, annual_rate):
    r = annual_rate / 12
    balance = principal
    total_interest = 0
    for _ in range(12):
        interest = balance * r
        payment = calc_monthly_payment(principal, annual_rate, 30)
        principal_paid = payment - interest
        total_interest += interest
        balance -= principal_paid
    return total_interest

def calc_year1_principal(principal, annual_rate):
    payment_annual = calc_monthly_payment(principal, annual_rate, 30) * 12
    interest = calc_year1_interest(principal, annual_rate)
    return payment_annual - interest

def calc_loan_balance(principal, annual_rate, years_elapsed):
    r = annual_rate / 12
    n_total = 30 * 12
    n_paid = years_elapsed * 12
    pmt = calc_monthly_payment(principal, annual_rate, 30)
    balance = principal
    for _ in range(n_paid):
        interest = balance * r
        balance -= (pmt - interest)
    return max(balance, 0)

def total_interest_over_life(principal, annual_rate, years):
    pmt = calc_monthly_payment(principal, annual_rate, years)
    return pmt * years * 12 - principal

def verdict_engine(coc, dscr, noi, total_return):
    """
    Classify the deal:
      BUY           → CoC ≥ 6% AND DSCR ≥ 1.25
      CONDITIONAL BUY → (CoC ≥ 0% OR total_return ≥ 6%) AND DSCR ≥ 0.9
      WATCH         → CoC ≥ -3% AND DSCR ≥ 0.5
      PASS          → everything else
    """
    if coc >= 0.06 and dscr >= 1.25:
        return ("Buy", "buy", "green")
    if (coc >= 0 or total_return >= 0.06) and dscr >= 0.9:
        return ("Conditional Buy", "buy", "green")
    if coc >= -0.03 and dscr >= 0.5:
        return ("Watch", "watch", "amber")
    return ("Pass", "pass", "red")


# ── main engine ──────────────────────────────────────────────────────────────

def generate_report(data):
    m = data["meta"]
    p = data["property"]
    f = data["financing"]
    rev = data["revenue"]
    scen = data["scenarios"]
    mkt = data["market"]
    mgmt = data["management"]
    tax = data["tax"]
    reg = data["regulatory"]

    # ── derived financials ───────────────────────────────────────────────
    purchase = f["purchase_price"]
    down_pct = f["down_payment_pct"]
    down = purchase * down_pct
    loan = purchase - down
    rate = f["interest_rate"]
    term = f["loan_term_years"]
    monthly_pi = calc_monthly_payment(loan, rate, term)
    annual_debt = monthly_pi * 12
    closing = purchase * f["closing_cost_pct"]
    total_cash = down + closing + f["permit_fee"] + f["initial_setup"]
    yr1_interest = calc_year1_interest(loan, rate)
    yr1_principal = calc_year1_principal(loan, rate)
    total_interest_life = total_interest_over_life(loan, rate, term)

    # monthly revenue
    monthly_rows = []
    total_nights = 0
    total_gross = 0
    for mp in rev["monthly_projections"]:
        days = 30  # approximate
        if mp["month"] in ("January","March","May","July","August","October","December"):
            days = 31
        elif mp["month"] == "February":
            days = 28
        nights = round(days * mp["occupancy"])
        rev_amt = round(mp["adr"] * nights)
        monthly_rows.append({**mp, "nights": nights, "revenue": rev_amt})
        total_nights += nights
        total_gross += rev_amt

    # base case
    base_gross = scen["base"]["gross_revenue"]
    platform_fees = round(base_gross * rev["platform_fee_pct"])
    turnovers = round(total_nights / rev["avg_stay_nights"])
    cleaning_total = turnovers * rev["cleaning_cost_per_turn"]
    supplies = next((e["annual"] for e in data["expenses"] if "Supplies" in e["name"] or "supplies" in e["name"]), 1200)

    fixed_expenses = sum(e["annual"] for e in data["expenses"])
    total_opex = fixed_expenses + platform_fees + cleaning_total
    noi = base_gross - total_opex
    cash_flow = noi - annual_debt

    coc = cash_flow / total_cash
    cap_rate = noi / purchase
    dscr = noi / annual_debt if annual_debt > 0 else 999

    # appreciation & tax
    appreciation = purchase * data["appreciation_rate"]
    building_value = purchase * data["building_value_pct"]
    annual_depreciation = building_value / data["depreciation_years"]
    tax_benefit = annual_depreciation * data["marginal_tax_rate"]
    total_return_val = cash_flow + yr1_principal + appreciation + tax_benefit
    total_return_pct = total_return_val / total_cash

    pm_savings = base_gross * mgmt["pm_fee_pct"]

    # verdict
    verdict_text, verdict_class, verdict_color = verdict_engine(coc, dscr, noi, total_return_pct)
    verdict_summary = mkt["deal_narrative"].split(". ")[-1] if mkt["deal_narrative"] else ""

    # scenario rows
    def calc_scenario(s):
        g = s["gross_revenue"]
        pf = round(g * rev["platform_fee_pct"])
        occ_nights = round(365 * s["occupancy"])
        turns = round(occ_nights / rev["avg_stay_nights"])
        cl = turns * rev["cleaning_cost_per_turn"]
        n = g - fixed_expenses - pf - cl
        cf = n - annual_debt
        c = cf / total_cash
        return {"noi": n, "cash_flow": cf, "coc": c}

    scenarios_calc = {}
    for key in ["conservative", "base", "optimistic"]:
        sc = scen[key]
        scenarios_calc[key] = {**sc, **calc_scenario(sc)}

    # pro forma
    pro_forma = []
    for yr in range(1, data["projection_years"] + 1):
        gr_factor = (1 + data["revenue_growth_rate"]) ** (yr - 1)
        exp_factor = (1 + data["expense_inflation_rate"]) ** (yr - 1)
        yr_gross = round(base_gross * gr_factor)
        yr_pf = round(yr_gross * rev["platform_fee_pct"])
        yr_clean = round(cleaning_total * exp_factor)
        yr_net_rev = yr_gross - yr_pf - yr_clean
        yr_opex = round(fixed_expenses * exp_factor)
        yr_noi = yr_net_rev - yr_opex
        yr_cf = yr_noi - annual_debt
        yr_value = round(purchase * (1 + data["appreciation_rate"]) ** yr)
        yr_balance = round(calc_loan_balance(loan, rate, yr))
        yr_equity = yr_value - yr_balance
        yr_coc = yr_cf / total_cash
        yr_total_roi = (yr_cf + (calc_monthly_payment(loan, rate, term) * 12 - calc_year1_interest(loan, rate)) + yr_value - purchase * (1 + data["appreciation_rate"]) ** (yr - 1) * data["appreciation_rate"] + tax_benefit) / total_cash
        pro_forma.append({
            "year": yr, "gross": yr_gross, "pf": yr_pf, "clean": yr_clean,
            "net_rev": yr_net_rev, "opex": yr_opex, "noi": yr_noi,
            "debt": annual_debt, "cf": yr_cf,
            "value": yr_value, "balance": yr_balance, "equity": yr_equity,
            "coc": yr_coc
        })
    cumulative_cf = 0
    for pf_row in pro_forma:
        cumulative_cf += pf_row["cf"]
        pf_row["cum_cf"] = cumulative_cf

    # ── color helpers ────────────────────────────────────────────────────
    def val_color(v, thresholds=(0, 0.03)):
        if v >= thresholds[1]: return "green"
        if v >= thresholds[0]: return "amber"
        return "red"

    def cf_color(v):
        if v > 1000: return "green"
        if v >= 0: return "amber"
        return "red"

    # ── HTML generation ──────────────────────────────────────────────────
    parts = []
    a = parts.append

    a(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>STR Deal Analysis — {h(p['address'])}, {h(p['city'])} {h(p.get('country_name', p['state']))}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #1a1a18; --paper: #ffffff; --accent: #c84b2f;
    --muted: #7a7870; --light: #f5f2eb;
    --border: rgba(26,26,24,0.15);
    --green: #2a7a4b; --amber: #b8942a;
    --serif: 'DM Serif Display', Georgia, serif;
    --mono: 'DM Mono', monospace;
    --sans: 'DM Sans', sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--sans); font-weight: 300; font-size: 13px;
    line-height: 1.65; color: var(--ink); background: white;
    max-width: 820px; margin: 0 auto; padding: 3rem 2.5rem;
  }}
  .report-header {{
    display: flex; justify-content: space-between; align-items: flex-start;
    padding-bottom: 1.5rem; border-bottom: 2px solid var(--ink); margin-bottom: 2rem;
  }}
  .brand {{ font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em; color: var(--muted); }}
  .report-id {{ font-family: var(--mono); font-size: 11px; color: var(--muted); text-align: right; }}
  .report-id span {{ display: block; }}
  .title-block {{ margin-bottom: 2rem; }}
  .property-name {{ font-family: var(--serif); font-size: 36px; line-height: 1.1; margin-bottom: 0.5rem; }}
  .property-meta {{ font-family: var(--mono); font-size: 11px; color: var(--muted); letter-spacing: 0.06em; }}
  .verdict-banner {{
    padding: 1rem 1.25rem; margin-bottom: 2rem;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .verdict-banner.buy {{ border-left: 4px solid var(--green); background: rgba(42,122,75,0.06); }}
  .verdict-banner.pass {{ border-left: 4px solid var(--accent); background: rgba(200,75,47,0.06); }}
  .verdict-banner.watch {{ border-left: 4px solid var(--amber); background: rgba(184,148,42,0.06); }}
  .verdict-label {{ font-family: var(--mono); font-size: 10px; letter-spacing: 0.12em; color: var(--muted); }}
  .verdict-text {{ font-family: var(--serif); font-size: 22px; }}
  .verdict-text.buy {{ color: var(--green); }}
  .verdict-text.pass {{ color: var(--accent); }}
  .verdict-text.watch {{ color: var(--amber); }}
  .section-title {{
    font-family: var(--mono); font-size: 10px; letter-spacing: 0.14em;
    color: var(--muted); text-transform: uppercase;
    border-bottom: 0.5px solid var(--border); padding-bottom: 0.5rem;
    margin-bottom: 1rem; margin-top: 2.5rem;
  }}
  .metrics-grid {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 1px; background: var(--border); margin-bottom: 0.5rem; }}
  .metric-box {{ background: white; padding: 1rem; }}
  .metric-label {{ font-family: var(--mono); font-size: 9px; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 4px; }}
  .metric-val {{ font-family: var(--serif); font-size: 26px; line-height: 1; }}
  .metric-val.green {{ color: var(--green); }}
  .metric-val.red {{ color: var(--accent); }}
  .metric-val.amber {{ color: var(--amber); }}
  .metric-sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 0.5rem; }}
  th {{ font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em; color: var(--muted);
       text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); background: var(--light); }}
  td {{ padding: 0.6rem 0.75rem; border-bottom: 0.5px solid var(--border); }}
  tr:last-child td {{ border-bottom: none; }}
  .scenario-upside td {{ color: var(--green); }}
  .scenario-downside td {{ color: var(--accent); }}
  .row-label {{ font-weight: 500; color: var(--muted); }}
  .row-total {{ font-weight: 500; background: var(--light); }}
  .analysis-block {{ margin-bottom: 1.5rem; }}
  .analysis-block h3 {{ font-family: var(--sans); font-weight: 500; font-size: 14px; margin-bottom: 0.5rem; }}
  .analysis-block p {{ color: var(--muted); line-height: 1.75; }}
  .risk-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border); }}
  .risk-cell {{ background: white; padding: 0.875rem 1rem; }}
  .risk-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
  .risk-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .risk-dot.green {{ background: var(--green); }}
  .risk-dot.amber {{ background: var(--amber); }}
  .risk-dot.red {{ background: var(--accent); }}
  .risk-name {{ font-weight: 500; font-size: 12px; }}
  .risk-note {{ font-size: 11px; color: var(--muted); padding-left: 16px; }}
  .steps-list {{ list-style: none; }}
  .steps-list li {{ display: flex; gap: 1rem; padding: 0.75rem 0; border-bottom: 0.5px solid var(--border); }}
  .steps-list li:last-child {{ border-bottom: none; }}
  .step-num {{ font-family: var(--mono); font-size: 11px; color: var(--accent); flex-shrink: 0; width: 24px; }}
  .step-text {{ font-size: 13px; line-height: 1.6; }}
  .amenity-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: var(--border); margin-bottom: 1rem; }}
  .amenity-box {{ background: white; padding: 0.75rem 1rem; }}
  .amenity-icon {{ font-size: 18px; margin-bottom: 4px; }}
  .amenity-name {{ font-weight: 500; font-size: 12px; }}
  .amenity-detail {{ font-size: 11px; color: var(--muted); }}
  .detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; }}
  .detail-row {{ display: flex; justify-content: space-between; padding: 0.45rem 0.75rem; border-bottom: 0.5px solid var(--border); }}
  .detail-label {{ font-size: 12px; color: var(--muted); }}
  .detail-value {{ font-size: 12px; font-weight: 500; text-align: right; }}
  .highlight-box {{
    background: var(--light); padding: 1rem 1.25rem; margin: 1rem 0;
    border-left: 3px solid var(--accent);
  }}
  .highlight-box .hl-label {{ font-family: var(--mono); font-size: 9px; letter-spacing: 0.1em; color: var(--accent); margin-bottom: 4px; }}
  .highlight-box .hl-text {{ font-size: 13px; line-height: 1.65; }}
  .return-stack {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 1px; background: var(--border); margin: 1rem 0; }}
  .return-item {{ background: white; padding: 0.875rem 1rem; text-align: center; }}
  .return-label {{ font-family: var(--mono); font-size: 9px; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 4px; }}
  .return-val {{ font-family: var(--serif); font-size: 20px; }}
  .return-sub {{ font-size: 10px; color: var(--muted); margin-top: 2px; }}
  .report-footer {{
    margin-top: 3rem; padding-top: 1rem; border-top: 0.5px solid var(--border);
    display: flex; justify-content: space-between;
    font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.06em;
  }}
  .disclaimer {{ margin-top: 1rem; font-size: 10px; color: var(--muted); line-height: 1.6; }}
  @media print {{
    body {{ padding: 1.5rem; }}
    .verdict-banner, .metrics-grid, .amenity-grid, .return-stack, .risk-grid, .row-total, th {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
""")

    # ── HEADER ───────────────────────────────────────────────────────────
    a(f"""<div class="report-header">
  <div>
    <div class="brand">{h(m['brand_name'])}</div>
    <div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:4px;">{h(m['brand_tagline'])}</div>
  </div>
  <div class="report-id">
    <span>REPORT #{h(m['report_number'])}</span>
    <span>{h(m['date'])}</span>
    <span>PREPARED FOR: {h(m['prepared_for'])}</span>
  </div>
</div>""")

    # ── TITLE ────────────────────────────────────────────────────────────
    a(f"""<div class="title-block">
  <div class="property-name">{h(p['address'])}</div>
  <div class="property-meta">{h(p['city'])}, {h(p['state'])}{(' ' + h(p['zip'])) if p.get('zip') else ''}{(' · ' + h(p.get('country_name',''))) if p.get('country_name') and p.get('country','US') not in ('US','') else ''} · {h(p['community'])} · {p['bedrooms']}BR/{p['bathrooms']}BA · {p['sqft']:,} SF · {h(p['type'])} · ASK: {usd(purchase)}</div>
</div>""")

    # ── VERDICT ──────────────────────────────────────────────────────────
    a(f"""<div class="verdict-banner {verdict_class}">
  <div>
    <div class="verdict-label">ANALYST VERDICT</div>
    <div class="verdict-text {verdict_class}">{h(verdict_text)}</div>
  </div>
  <div style="font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right;max-width:320px;line-height:1.5;">
    {h(verdict_summary)}
  </div>
</div>""")

    # ── KEY METRICS ──────────────────────────────────────────────────────
    a(f"""<div class="section-title">Key metrics — base case</div>
<div class="metrics-grid">
  <div class="metric-box"><div class="metric-label">GROSS REVENUE</div><div class="metric-val">{usd(base_gross)}</div><div class="metric-sub">{total_nights} nights · {pct(scen['base']['occupancy'])} occ.</div></div>
  <div class="metric-box"><div class="metric-label">TOTAL EXPENSES</div><div class="metric-val red">{usd(total_opex + annual_debt)}</div><div class="metric-sub">incl. all ops + debt service</div></div>
  <div class="metric-box"><div class="metric-label">NET CASH FLOW</div><div class="metric-val {cf_color(cash_flow)}">{usd(cash_flow)}</div><div class="metric-sub">after all costs</div></div>
  <div class="metric-box"><div class="metric-label">TOTAL RETURN</div><div class="metric-val {val_color(total_return_pct)}">{pct(total_return_pct)}</div><div class="metric-sub">cash + equity + appreciation</div></div>
</div>
<div class="metrics-grid" style="margin-top:0;">
  <div class="metric-box"><div class="metric-label">CASH-ON-CASH</div><div class="metric-val {val_color(coc)}">{pct(coc)}</div><div class="metric-sub">pre-tax, year 1</div></div>
  <div class="metric-box"><div class="metric-label">CAP RATE</div><div class="metric-val">{pct(cap_rate)}</div><div class="metric-sub">NOI / purchase price</div></div>
  <div class="metric-box"><div class="metric-label">DSCR</div><div class="metric-val {val_color(dscr - 1, (0, 0.25))}">{dscr:.2f}x</div><div class="metric-sub">NOI / debt service</div></div>
  <div class="metric-box"><div class="metric-label">PM SAVINGS</div><div class="metric-val green">{usd(pm_savings)}</div><div class="metric-sub">vs. {pct(mgmt['pm_fee_pct'],0)} managed</div></div>
</div>""")

    # ── PROPERTY OVERVIEW ────────────────────────────────────────────────
    a('<div class="section-title">Property overview</div>')
    a('<div class="detail-grid">')
    prop_details = [
        ("Property Type", p["type"]),
        ("Community", p["community"]),
        ("Bedrooms / Baths", f"{p['bedrooms']} BR / {p['bathrooms']} BA"),
        ("Square Footage", f"{p['sqft']:,} SF"),
        ("Year Built", f"{p['year_built']} ({2026 - p['year_built']} years)"),
        ("Condition", p["condition"]),
        ("Access", p["access"]),
        ("Parking", p["parking"]),
        ("Beach Access", p["beach_access"]),
        ("Special Features", p["special_features"]),
        ("HVAC", p["hvac"]),
        ("Flooring", p["flooring"]),
    ]
    for label, val in prop_details:
        a(f'  <div class="detail-row"><span class="detail-label">{h(label)}</span><span class="detail-value">{h(val)}</span></div>')
    a('</div>')

    # ── AMENITIES ────────────────────────────────────────────────────────
    if data.get("amenities"):
        a('<div class="section-title">Community amenities — competitive advantage</div>')
        a('<div class="amenity-grid">')
        for am in data["amenities"]:
            a(f"""  <div class="amenity-box">
    <div class="amenity-icon">{am['icon']}</div>
    <div class="amenity-name">{h(am['name'])}</div>
    <div class="amenity-detail">{h(am['detail'])}</div>
  </div>""")
        a('</div>')
        if data.get("amenity_narrative"):
            a(f'<div class="analysis-block"><p>{h(data["amenity_narrative"])}</p></div>')

    # ── FINANCING ────────────────────────────────────────────────────────
    a(f"""<div class="section-title">Financing structure</div>
<div class="metrics-grid">
  <div class="metric-box"><div class="metric-label">PURCHASE PRICE</div><div class="metric-val">{usd(purchase/1000)}K</div><div class="metric-sub">below {usd(mkt['median_home_value']/1000)}K market median</div></div>
  <div class="metric-box"><div class="metric-label">DOWN PAYMENT</div><div class="metric-val">{usd(down/1000)}K</div><div class="metric-sub">{pct(down_pct, 0)} — conservative LTV</div></div>
  <div class="metric-box"><div class="metric-label">LOAN TERMS</div><div class="metric-val">{pct(rate, 1)}</div><div class="metric-sub">{term}-year fixed</div></div>
  <div class="metric-box"><div class="metric-label">MONTHLY P&amp;I</div><div class="metric-val">{usd(monthly_pi)}</div><div class="metric-sub">{usd(annual_debt)} annual</div></div>
</div>""")

    # acquisition cost table
    a("""<table>
<thead><tr><th>Acquisition Cost</th><th>Amount</th><th>Notes</th></tr></thead>
<tbody>""")
    a(f'<tr><td>Down Payment</td><td>{usd(down)}</td><td>{pct(down_pct,0)} of purchase price</td></tr>')
    a(f'<tr><td>Estimated Closing Costs</td><td>{usd(closing)}</td><td>~{pct(f["closing_cost_pct"],0)} of purchase</td></tr>')
    a(f'<tr><td>STR Permit Fee</td><td>{usd(f["permit_fee"])}</td><td>Annual town registration</td></tr>')
    a(f'<tr><td>Initial Supplies & Setup</td><td>{usd(f["initial_setup"])}</td><td>Smart lock, supplies, photos</td></tr>')
    a(f'<tr class="row-total"><td>Total Cash to Close</td><td>{usd(total_cash)}</td><td></td></tr>')
    a('</tbody></table>')

    # amort table
    a("""<table style="margin-top:1rem;">
<thead><tr><th>Amortization Detail</th><th>Value</th></tr></thead>
<tbody>""")
    a(f'<tr><td>Year 1 Interest Paid</td><td>{usd(yr1_interest)}</td></tr>')
    a(f'<tr><td>Year 1 Principal Paid</td><td>{usd(yr1_principal)}</td></tr>')
    a(f'<tr><td>Total Interest Over Loan Life</td><td>{usd(total_interest_life)}</td></tr>')
    a(f'<tr><td>Loan-to-Value (LTV)</td><td>{pct(1 - down_pct, 0)}</td></tr>')
    a('</tbody></table>')

    # ── SCENARIO ANALYSIS ────────────────────────────────────────────────
    a("""<div class="section-title">Scenario analysis</div>
<table>
<thead><tr><th>Scenario</th><th>Occupancy</th><th>Blended ADR</th><th>Gross Revenue</th><th>NOI</th><th>Net Cash Flow</th><th>CoC Return</th></tr></thead>
<tbody>""")
    for key, css in [("optimistic", "scenario-upside"), ("base", ""), ("conservative", "scenario-downside")]:
        sc = scenarios_calc[key]
        a(f'<tr class="{css}"><td class="row-label">{h(sc["label"])}</td><td>{pct(sc["occupancy"])}</td><td>{usd(sc["blended_adr"])}</td><td>{usd(sc["gross_revenue"])}</td><td>{usd(sc["noi"])}</td><td>{usd(sc["cash_flow"])}</td><td>{pct(sc["coc"])}</td></tr>')
    a('</tbody></table>')
    a(f'<div class="analysis-block" style="margin-top:0.75rem;"><p><strong>Base case</strong> assumes moderate dynamic pricing and seasonal optimization across Airbnb + VRBO. <strong>Upside</strong> reflects Superhost/Premier status and aggressive peak-season pricing. <strong>Downside</strong> models minimal optimization and soft shoulder-season performance.</p></div>')

    # ── MONTHLY REVENUE ──────────────────────────────────────────────────
    a("""<div class="section-title">Monthly revenue projection — base case</div>
<table>
<thead><tr><th>Month</th><th>Est. ADR</th><th>Occupancy</th><th>Nights</th><th>Revenue</th><th>Season</th></tr></thead>
<tbody>""")
    season_colors = {"peak": "var(--green)", "shoulder": "var(--amber)", "off": "var(--accent)"}
    season_labels = {"peak": "Peak", "shoulder": "Shoulder", "off": "Off"}
    for mr in monthly_rows:
        row_bg = ' style="background:rgba(42,122,75,0.04)"' if mr["season"] == "peak" else ""
        bold_o = "<strong>" if mr["season"] == "peak" else ""
        bold_c = "</strong>" if mr["season"] == "peak" else ""
        rev_style = f' style="color:var(--green)"' if mr["season"] == "peak" else ""
        a(f'<tr{row_bg}><td>{bold_o}{h(mr["month"])}{bold_c}</td><td>{usd(mr["adr"])}</td><td>{pct(mr["occupancy"],0)}</td><td>{mr["nights"]}</td><td{rev_style}>{bold_o}{usd(mr["revenue"])}{bold_c}</td><td style="color:{season_colors[mr["season"]]}">{season_labels[mr["season"]]}</td></tr>')
    a(f'<tr class="row-total"><td><strong>Annual Total</strong></td><td></td><td></td><td><strong>{total_nights}</strong></td><td><strong>{usd(total_gross)}</strong></td><td></td></tr>')
    a('</tbody></table>')

    peak_rev = sum(mr["revenue"] for mr in monthly_rows if mr["season"] == "peak")
    peak_pct_val = peak_rev / total_gross * 100 if total_gross > 0 else 0
    a(f"""<div class="highlight-box">
  <div class="hl-label">NOTE ON GROSS VS. NET REVENUE</div>
  <div class="hl-text">The {usd(total_gross)} figure represents gross booking revenue before platform fees (~{usd(platform_fees)}) and cleaning/supplies costs (~{usd(cleaning_total)}). After these deductions, net rental revenue is approximately <strong>{usd(base_gross)}</strong> — the base case used throughout this report. June–August alone generate {peak_pct_val:.0f}% of total annual revenue.</div>
</div>""")

    # ── EXPENSE BREAKDOWN ────────────────────────────────────────────────
    a("""<div class="section-title">Expense breakdown — annual</div>
<table>
<thead><tr><th>Expense</th><th>Annual</th><th>Monthly</th><th>% of Gross</th><th>Notes</th></tr></thead>
<tbody>""")
    for e in data["expenses"]:
        ann = e["annual"]
        mon = ann / 12
        pct_g = ann / base_gross * 100
        a(f'<tr><td>{h(e["name"])}</td><td>{usd(ann)}</td><td>{usd(mon)}</td><td>{pct_g:.1f}%</td><td>{h(e["notes"])}</td></tr>')
    # platform fees
    pf_pct_g = platform_fees / base_gross * 100
    a(f'<tr><td>Platform booking fees</td><td>{usd(platform_fees)}</td><td>{usd(platform_fees/12)}</td><td>{pf_pct_g:.1f}%</td><td>Blended ~{pct(rev["platform_fee_pct"],1)} of gross (Airbnb 3% + VRBO 8%)</td></tr>')
    cl_pct_g = cleaning_total / base_gross * 100
    a(f'<tr><td>Cleaning &amp; turnover</td><td>{usd(cleaning_total)}</td><td>{usd(cleaning_total/12)}</td><td>{cl_pct_g:.1f}%</td><td>~{usd(rev["cleaning_cost_per_turn"])}/clean x {turnovers} turnovers/yr</td></tr>')
    opex_pct = total_opex / base_gross * 100
    a(f'<tr class="row-total"><td>Total Operating Expenses</td><td>{usd(total_opex)}</td><td>{usd(total_opex/12)}</td><td>{opex_pct:.1f}%</td><td></td></tr>')
    debt_pct = annual_debt / base_gross * 100
    a(f'<tr><td>Debt service (P&amp;I)</td><td>{usd(annual_debt)}</td><td>{usd(monthly_pi)}</td><td>{debt_pct:.1f}%</td><td>{usd(loan)} @ {pct(rate,1)} / {term}-year fixed</td></tr>')
    allin = total_opex + annual_debt
    allin_pct = allin / base_gross * 100
    a(f'<tr class="row-total"><td><strong>Total All-In Cost</strong></td><td><strong>{usd(allin)}</strong></td><td><strong>{usd(allin/12)}</strong></td><td><strong>{allin_pct:.1f}%</strong></td><td></td></tr>')
    a('</tbody></table>')

    # insurance note
    hoa_item = next((e for e in data["expenses"] if "HOA" in e["name"] or "hoa" in e["name"]), None)
    if hoa_item and "insurance" in hoa_item["name"].lower():
        a(f"""<div class="highlight-box">
  <div class="hl-label">INSURANCE NOTE</div>
  <div class="hl-text">Flood and wind/hazard insurance are <strong>included in the HOA dues</strong> — not a separate line item. This is a meaningful cost advantage. The {usd(hoa_item['annual'])}/yr HOA is high but covers insurance that would otherwise cost $2,000–$4,000 separately for a coastal property.</div>
</div>""")

    # ── TOTAL RETURN ─────────────────────────────────────────────────────
    a(f"""<div class="section-title">Total return on investment — year 1</div>
<div class="return-stack">
  <div class="return-item"><div class="return-label">CASH FLOW</div><div class="return-val {cf_color(cash_flow)}">{usd(cash_flow)}</div><div class="return-sub">{pct(cash_flow/total_cash)} of equity</div></div>
  <div class="return-item"><div class="return-label">PRINCIPAL PAYDOWN</div><div class="return-val">{usd(yr1_principal)}</div><div class="return-sub">{pct(yr1_principal/total_cash)} of equity</div></div>
  <div class="return-item"><div class="return-label">APPRECIATION ({pct(data['appreciation_rate'],0)})</div><div class="return-val green">{usd(appreciation)}</div><div class="return-sub">{pct(appreciation/total_cash)} of equity</div></div>
  <div class="return-item"><div class="return-label">TAX BENEFITS</div><div class="return-val">{usd(tax_benefit)}</div><div class="return-sub">{pct(tax_benefit/total_cash)} of equity</div></div>
</div>""")

    a(f"""<table>
<thead><tr><th>Return Component</th><th>Annual Value</th><th>% of {usd(total_cash)} Equity</th></tr></thead>
<tbody>
<tr><td>Pre-Tax Cash Flow</td><td>{usd(cash_flow)}</td><td>{pct(cash_flow/total_cash)}</td></tr>
<tr><td>Mortgage Principal Paydown</td><td>{usd(yr1_principal)}</td><td>{pct(yr1_principal/total_cash)}</td></tr>
<tr><td>Estimated Appreciation ({pct(data['appreciation_rate'],0)}/yr)</td><td>{usd(appreciation)}</td><td>{pct(appreciation/total_cash)}</td></tr>
<tr><td>Tax Benefits (depreciation shield)</td><td>{usd(tax_benefit)}</td><td>{pct(tax_benefit/total_cash)}</td></tr>
<tr class="row-total"><td><strong>Total Return on Equity</strong></td><td><strong>{usd(total_return_val)}</strong></td><td><strong>{pct(total_return_pct)}</strong></td></tr>
</tbody></table>""")

    a(f'<div class="analysis-block" style="margin-top:1rem;"><p>While Year 1 cash-on-cash is {pct(coc)}, the total return profile is compelling at {pct(total_return_pct)} when accounting for equity building via principal paydown, market appreciation, and depreciation tax shield ({usd(building_value)} building value / {data["depreciation_years"]} years = {usd(annual_depreciation)}/yr deduction). The {pct(down_pct,0)} down payment significantly de-risks the investment by keeping debt service manageable and providing substantial equity cushion from day one.</p></div>')

    # ── MARKET ANALYSIS ──────────────────────────────────────────────────
    a(f'<div class="section-title">Market analysis — {h(mkt["area_name"])}</div>')
    a(f'<div class="analysis-block"><h3>Deal verdict</h3><p>{h(mkt["deal_narrative"])}</p></div>')
    a(f'<div class="analysis-block"><h3>Revenue assumptions</h3><p>{h(mkt["revenue_narrative"])}</p></div>')
    a(f'<div class="analysis-block"><h3>Market dynamics</h3><p>{h(mkt["dynamics_narrative"])}</p></div>')

    a("""<table>
<thead><tr><th>Market Metric</th>""")
    for src in mkt["sources"]:
        a(f'<th>{h(src["name"])}</th>')
    a('</tr></thead><tbody>')
    metrics_list = [
        ("Active Listings", "listings", lambda v: f"{v:,}" if v else "N/A"),
        ("Average Daily Rate", "adr", lambda v: usd(v) if v else "N/A"),
        ("Occupancy Rate", "occupancy", lambda v: pct(v) if v else "N/A"),
        ("Annual Revenue (avg)", "annual_rev", lambda v: usd(v) if v else "N/A"),
        ("Revenue Growth YoY", "rev_growth", lambda v: v if v else "N/A"),
        ("RevPAR", "revpar", lambda v: usd(v) if v else "N/A"),
    ]
    for label, key, fmt in metrics_list:
        a(f'<tr><td>{label}</td>')
        for src in mkt["sources"]:
            a(f'<td>{fmt(src.get(key))}</td>')
        a('</tr>')
    a('</tbody></table>')

    # ── SELF-MANAGEMENT ──────────────────────────────────────────────────
    a('<div class="section-title">Self-management strategy</div>')
    a(f'<div class="analysis-block"><h3>Platform approach</h3><p>{h(mgmt["platform_narrative"])}</p></div>')
    a(f'<div class="analysis-block"><h3>Operational requirements</h3><p>{h(mgmt["ops_narrative"])}</p></div>')
    a(f'<div class="analysis-block"><h3>Revenue optimization tactics</h3><p>{h(mgmt["optimization_narrative"])}</p></div>')

    # ── RISK ASSESSMENT ──────────────────────────────────────────────────
    a('<div class="section-title">Risk assessment</div>')
    a('<div class="risk-grid">')
    for risk in data["risks"]:
        a(f"""<div class="risk-cell">
    <div class="risk-header"><div class="risk-dot {risk['severity']}"></div><div class="risk-name">{h(risk['name'])}</div></div>
    <div class="risk-note">{h(risk['note'])}</div>
  </div>""")
    a('</div>')

    # ── TAX & LEGAL ──────────────────────────────────────────────────────
    a('<div class="section-title">Tax &amp; legal flags</div>')
    a(f"""<div class="analysis-block"><p>
<strong>Occupancy tax:</strong> {h(tax['occupancy_tax_narrative'])}<br><br>
<strong>Property tax:</strong> {h(tax['property_tax_narrative'])}<br><br>
<strong>Income tax:</strong> {h(tax['income_tax_narrative'])}<br><br>
<strong>Depreciation:</strong> {h(tax['depreciation_narrative'])}<br><br>
<strong>14-day rule:</strong> {h(tax['fourteen_day_rule'])}<br><br>
<strong>Mortgage interest:</strong> {h(tax['interest_deduction_note'])}
</p></div>""")

    # ── REGULATORY ───────────────────────────────────────────────────────
    a('<div class="section-title">Regulatory environment</div>')
    a('<div class="detail-grid">')
    reg_details = [
        ("Permit Required", "Yes" if reg["permit_required"] else "No"),
        ("Permit Cost", usd(reg["permit_cost"]) + "/year"),
        ("Processing Time", reg["processing_time"]),
        ("Night Limit", reg["night_limit"]),
        ("Primary Residence Required", "No" if not reg["primary_residence_required"] else "Yes"),
        ("Max Guests (this unit)", str(reg["max_guests_this_unit"])),
        ("Local Contact", f"Required — responds {reg['local_contact_response']}"),
        ("Regulation Level", reg["regulation_level"]),
        ("Tax Collection", reg["tax_collection"]),
    ]
    for label, val in reg_details:
        a(f'  <div class="detail-row"><span class="detail-label">{h(label)}</span><span class="detail-value">{h(val)}</span></div>')
    a('</div>')

    if reg.get("checklist"):
        a("""<table style="margin-top:1rem;">
<thead><tr><th>Requirement</th><th>Action Needed</th></tr></thead>
<tbody>""")
        for item in reg["checklist"]:
            a(f'<tr><td>{h(item["requirement"])}</td><td>{h(item["action"])}</td></tr>')
        a('</tbody></table>')

    # ── 5-YEAR PRO FORMA ─────────────────────────────────────────────────
    a(f"""<div class="section-title">{data['projection_years']}-year pro forma projection</div>
<table>
<thead><tr><th>Metric</th>""")
    for pf_row in pro_forma:
        a(f'<th>Year {pf_row["year"]}</th>')
    a('</tr></thead><tbody>')

    pf_metrics = [
        ("Gross Revenue", "gross", usd),
        ("Platform Fees", "pf", lambda v: f"({usd(v)})"),
        ("Cleaning", "clean", lambda v: f"({usd(v)})"),
        ("Net Rental Revenue", "net_rev", usd),
        ("Operating Expenses", "opex", lambda v: f"({usd(v)})"),
        ("NOI", "noi", usd),
        ("Debt Service", "debt", lambda v: f"({usd(v)})"),
        ("Pre-Tax Cash Flow", "cf", usd),
        ("Cumulative Cash Flow", "cum_cf", usd),
        ("Property Value", "value", usd),
        ("Loan Balance", "balance", usd),
        ("Total Equity", "equity", usd),
        ("Cash-on-Cash Return", "coc", lambda v: pct(v)),
    ]
    for label, key, fmt in pf_metrics:
        is_total = key in ("net_rev", "noi", "cf", "equity")
        cls = ' class="row-total"' if is_total else ""
        a(f'<tr{cls}><td>{label}</td>')
        for pf_row in pro_forma:
            a(f'<td>{fmt(pf_row[key])}</td>')
        a('</tr>')
    a('</tbody></table>')

    # ── COMPS ────────────────────────────────────────────────────────────
    if data.get("comps"):
        a("""<div class="section-title">Comparable benchmarks</div>
<table>
<thead><tr><th>Property</th><th>Type</th><th>ADR</th><th>Occupancy</th><th>Annual Rev</th><th>Notes</th></tr></thead>
<tbody>""")
        for comp in data["comps"]:
            a(f'<tr><td>{h(comp["address"])}</td><td>{h(comp["type"])}</td><td>{h(comp["adr"])}</td><td>{h(comp["occupancy"])}</td><td>{h(comp["annual_rev"])}</td><td>{h(comp["notes"])}</td></tr>')
        a('</tbody></table>')

    # ── NEXT STEPS ───────────────────────────────────────────────────────
    if data.get("next_steps"):
        a('<div class="section-title">Recommended next steps</div>')
        a('<ul class="steps-list">')
        for i, step in enumerate(data["next_steps"], 1):
            a(f'<li><span class="step-num">{i:02d}</span><span class="step-text">{h(step)}</span></li>')
        a('</ul>')

    # ── FOOTER ───────────────────────────────────────────────────────────
    a(f"""<div class="report-footer">
  <span>CONFIDENTIAL — {h(m['brand_name'])}</span>
  <span>{h(m['brand_url'])}</span>
</div>
<div class="disclaimer">{h(data.get('disclaimer', ''))}</div>
</body></html>""")

    return "\n".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_report.py <deal_data.json> [output_name]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_name = sys.argv[2] if len(sys.argv) > 2 else "report"
    output_path = Path(f"{output_name}.html")

    with open(input_path) as f:
        data = json.load(f)

    html = generate_report(data)
    output_path.write_text(html, encoding="utf-8")
    print(f"Report generated: {output_path} ({len(html):,} bytes)")
    print(f"Verdict: {json.loads(open(input_path).read())['meta']['report_number']}")
