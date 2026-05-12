import html as html_mod
from datetime import datetime
import math

# ─── Helpers ─────────────────────────────────────────────────────────────────

def safe_float(value, default=0.0):
    try:
        if value is None or str(value).strip() == '': return default
        return float(str(value).replace(',', '').replace('$', '').replace('%', ''))
    except (ValueError, TypeError):
        return default

def usd(n):
    v = float(n or 0)
    return f"${v:,.0f}"

def usd_parens(n):
    v = float(n or 0)
    return f"(${abs(v):,.0f})" if v < 0 else f"${v:,.0f}"

def fmt_pct(n):
    return f"{float(n or 0):.1f}%"

def esc(s):
    return html_mod.escape(str(s or ''))

# ─── Market Configuration ─────────────────────────────────────────────────────

MARKET_CONFIG = {
    'coastal_premium': {
        'label': 'Coastal Premium', 'adr': 380, 'occ': 0.63, 'appr': 0.04,
        'season_occ':  [0.20,0.22,0.42,0.55,0.70,0.88,0.92,0.85,0.55,0.42,0.22,0.20],
        'season_adr':  [0.50,0.52,0.72,0.80,0.92,1.25,1.40,1.22,0.80,0.70,0.52,0.50],
    },
    'coastal_standard': {
        'label': 'Coastal Standard', 'adr': 220, 'occ': 0.58, 'appr': 0.03,
        'season_occ':  [0.20,0.18,0.42,0.52,0.66,0.85,0.90,0.80,0.52,0.42,0.22,0.20],
        'season_adr':  [0.50,0.48,0.72,0.78,0.90,1.20,1.38,1.18,0.78,0.68,0.52,0.50],
    },
    'mountain': {
        'label': 'Mountain', 'adr': 290, 'occ': 0.60, 'appr': 0.04,
        'season_occ':  [0.72,0.68,0.50,0.35,0.30,0.45,0.62,0.58,0.40,0.35,0.45,0.75],
        'season_adr':  [1.30,1.25,0.90,0.70,0.65,0.85,1.10,1.05,0.80,0.72,0.85,1.35],
    },
    'urban': {
        'label': 'Urban', 'adr': 155, 'occ': 0.65, 'appr': 0.03,
        'season_occ':  [0.55,0.52,0.62,0.68,0.70,0.75,0.70,0.68,0.72,0.68,0.60,0.58],
        'season_adr':  [0.88,0.85,0.95,1.00,1.05,1.10,1.05,1.00,1.08,1.05,0.92,0.90],
    },
    'lake': {
        'label': 'Lake', 'adr': 255, 'occ': 0.55, 'appr': 0.03,
        'season_occ':  [0.10,0.12,0.25,0.45,0.65,0.82,0.90,0.85,0.55,0.30,0.15,0.10],
        'season_adr':  [0.55,0.58,0.70,0.82,0.95,1.15,1.30,1.22,0.90,0.72,0.60,0.55],
    },
    'rural': {
        'label': 'Rural / Other', 'adr': 135, 'occ': 0.48, 'appr': 0.02,
        'season_occ':  [0.30,0.28,0.38,0.45,0.50,0.55,0.62,0.58,0.48,0.40,0.32,0.30],
        'season_adr':  [0.80,0.78,0.88,0.92,0.98,1.05,1.15,1.10,0.95,0.88,0.82,0.80],
    },
}

CARIBBEAN_OCC  = [0.65,0.70,0.72,0.55,0.38,0.35,0.50,0.42,0.28,0.30,0.48,0.72]
CARIBBEAN_ADR  = [1.12,1.20,1.22,1.00,0.78,0.72,0.90,0.78,0.60,0.65,0.88,1.18]

BR_MULT = {1:0.55, 2:0.80, 3:1.0, 4:1.30, 5:1.60, 6:1.90}
MONTHS  = ['January','February','March','April','May','June',
           'July','August','September','October','November','December']
DAYS    = [31,28,31,30,31,30,31,31,30,31,30,31]

CARIBBEAN = {'Dominican Republic','Bahamas','Turks & Caicos','Jamaica',
             'Cayman Islands','Barbados','Belize','Costa Rica','Panama','Colombia','Mexico'}
US_TERR   = {'U.S. Virgin Islands','Puerto Rico'}

# ─── Core Financial Engine ────────────────────────────────────────────────────

def calculate(data):
    price        = safe_float(data.get('price'))
    down_pct     = safe_float(data.get('down_payment_pct'), 25) / 100
    down_payment = price * down_pct
    loan         = price - down_payment
    rate         = safe_float(data.get('interest_rate'), 7.0) / 100
    term         = int(safe_float(data.get('loan_term'), 30))
    hoa_annual   = safe_float(data.get('hoa', 0))
    hoa_ins      = str(data.get('hoa_includes_insurance', 'No')).startswith('Yes')
    bedrooms     = max(1, int(safe_float(data.get('bedrooms'), 2)))
    bathrooms    = safe_float(data.get('bathrooms'), 1)
    sqft         = safe_float(data.get('sqft'), 0)
    year_built   = int(safe_float(data.get('year_built'), 2000))
    market_type  = data.get('market_type') or 'coastal_standard'
    country      = data.get('country', 'United States')
    rev_override = safe_float(data.get('annual_revenue', 0))

    is_carib = country in CARIBBEAN
    is_us_terr = country in US_TERR
    is_domestic = not is_carib

    mkt = MARKET_CONFIG.get(market_type, MARKET_CONFIG['coastal_standard'])
    br_mult = BR_MULT.get(bedrooms, 1.60 if bedrooms > 6 else 0.55)
    base_adr = mkt['adr'] * br_mult
    base_occ = mkt['occ']
    appr_rate = 0.05 if is_carib else mkt['appr']

    # Caribbean adjusts base ADR downward (lower sticker, more nights)
    if is_carib:
        base_adr *= 0.70
        base_occ  = 0.52

    # Revenue
    if rev_override > 0:
        gross = rev_override
        nights_base = gross / base_adr if base_adr else 0
        occ = min(nights_base / 365, 0.95)
        adr = base_adr
    else:
        occ = base_occ
        adr = base_adr
        nights_base = 365 * occ
        gross = nights_base * adr

    # Monthly projection
    s_occ = CARIBBEAN_OCC if is_carib else mkt['season_occ']
    s_adr = CARIBBEAN_ADR if is_carib else mkt['season_adr']
    monthly = []
    total_rev_check = 0
    for i, (mo, days) in enumerate(zip(MONTHS, DAYS)):
        mo_occ  = s_occ[i]
        mo_adr  = adr * s_adr[i]
        mo_nights = round(days * mo_occ)
        mo_rev  = mo_nights * mo_adr
        total_rev_check += mo_rev
        if mo_occ >= 0.70:   season = 'Peak'
        elif mo_occ >= 0.45: season = 'Shoulder'
        else:                 season = 'Off'
        monthly.append({'month': mo, 'adr': mo_adr, 'occ': mo_occ,
                         'nights': mo_nights, 'rev': mo_rev, 'season': season})
    # Scale monthly to match gross
    scale = gross / total_rev_check if total_rev_check else 1
    for m in monthly:
        m['rev']  *= scale
        m['adr']  *= scale

    # Scenarios
    adr_up   = adr * 1.18;  occ_up   = min(occ * 1.18, 0.90)
    adr_down = adr * 0.82;  occ_down = occ * 0.72
    gross_up   = 365 * occ_up   * adr_up
    gross_down = 365 * occ_down * adr_down

    # Expenses — self-managed, estimated from property characteristics
    platform_fee = gross * 0.055          # blended Airbnb 3% + VRBO 8%
    avg_stay     = 4
    turnovers    = (365 * occ) / avg_stay
    clean_per    = (55 if is_carib else 90) + (bedrooms - 1) * 20
    cleaning     = turnovers * clean_per

    # Insurance
    if hoa_ins:
        insurance = 0
    else:
        if is_carib: ins_rate = 0.006
        elif market_type in ('coastal_premium','coastal_standard'): ins_rate = 0.012
        else: ins_rate = 0.008
        insurance = price * ins_rate

    # Property tax
    if country == 'Dominican Republic': prop_tax = 0
    elif country in ('Turks & Caicos','Cayman Islands'): prop_tax = 0
    elif country == 'U.S. Virgin Islands': prop_tax = price * 0.0095
    else: prop_tax = price * 0.0085

    # Utilities
    util_map = {1:1800, 2:2400, 3:3000, 4:3600, 5:4500}
    utilities = util_map.get(bedrooms, 3000) * (1.35 if is_carib else 1.0)

    # Maintenance (scales with age)
    age = datetime.now().year - year_built
    maint_rate = 0.004 if age < 5 else (0.007 if age < 15 else 0.010)
    maintenance = price * maint_rate

    furn_reserve = price * 0.002
    internet     = 960 if is_carib else 960
    permit       = 0 if is_carib else 250
    accounting   = 500 if is_domestic or is_us_terr else 600
    misc         = 500

    total_opex = (platform_fee + cleaning + insurance + prop_tax +
                  hoa_annual + utilities + maintenance + furn_reserve +
                  internet + permit + accounting + misc)

    pm_cost = gross * 0.20   # PM savings benchmark

    noi = gross - total_opex

    # Scenario NOI
    opex_ratio = total_opex / gross if gross else 0
    noi_up   = gross_up   * (1 - opex_ratio)
    noi_down = gross_down * (1 - opex_ratio)

    # Debt service
    if rate > 0 and loan > 0 and term > 0:
        m_rate = rate / 12
        n = term * 12
        monthly_pi = loan * (m_rate * (1 + m_rate)**n) / ((1 + m_rate)**n - 1)
    else:
        monthly_pi = 0
    annual_debt = monthly_pi * 12

    # Year-1 amortization
    yr1_interest   = loan * rate if loan > 0 else 0
    yr1_principal  = max(0, annual_debt - yr1_interest)
    total_interest = annual_debt * term - loan if annual_debt > 0 else 0
    ltv = (loan / price * 100) if price else 0

    cf = noi - annual_debt
    cf_up   = noi_up   - annual_debt
    cf_down = noi_down - annual_debt
    coc     = cf / down_payment if down_payment > 0 else 0
    coc_up  = cf_up   / down_payment if down_payment > 0 else 0
    coc_down= cf_down / down_payment if down_payment > 0 else 0
    cap_rate= noi / price if price > 0 else 0
    dscr    = noi / annual_debt if annual_debt > 0 else float('inf')

    # Total return
    bldg_val    = price * (0.85 if is_carib else 0.80)
    depreciation= bldg_val / 27.5
    tax_benefit = depreciation * 0.24
    appr_val    = price * appr_rate
    total_ret   = cf + yr1_principal + appr_val + tax_benefit
    total_ret_pct = total_ret / down_payment if down_payment > 0 else 0

    # 5-Year projection
    projections = []
    v = price; l = loan; cum_cf = 0
    for yr in range(1, 6):
        v *= (1 + appr_rate)
        int_y   = l * rate if rate > 0 else 0
        prin_y  = max(0, annual_debt - int_y)
        l       = max(0, l - prin_y)
        rev_y   = gross * (1.03 ** (yr - 1))
        plat_y  = rev_y * 0.055
        clean_y = cleaning * (1.03 ** (yr - 1))
        opex_y  = (total_opex - platform_fee - cleaning) * (1.03 ** (yr - 1))
        noi_y   = rev_y - plat_y - clean_y - opex_y
        cf_y    = noi_y - annual_debt
        cum_cf += cf_y
        projections.append({
            'year': yr, 'gross': rev_y, 'platform': plat_y, 'cleaning': clean_y,
            'opex': opex_y, 'noi': noi_y, 'debt': annual_debt, 'cf': cf_y,
            'cum_cf': cum_cf, 'value': v, 'loan': l, 'equity': v - l,
            'coc': cf_y / down_payment if down_payment > 0 else 0,
        })

    # Closing costs
    closing_pct  = 0.05 if is_carib else 0.03
    closing_cost = price * closing_pct
    setup_cost   = 2500 if is_carib else 1500
    total_cash   = down_payment + closing_cost + permit + setup_cost

    return {
        'price': price, 'down_payment': down_payment, 'down_pct': down_pct * 100,
        'loan': loan, 'rate': rate * 100, 'term': term, 'monthly_pi': monthly_pi,
        'annual_debt': annual_debt, 'ltv': ltv,
        'yr1_interest': yr1_interest, 'yr1_principal': yr1_principal,
        'total_interest': total_interest, 'closing_cost': closing_cost,
        'setup_cost': setup_cost, 'total_cash': total_cash, 'permit': permit,
        'adr': adr, 'occ': occ, 'nights': nights_base, 'gross': gross,
        'adr_up': adr_up, 'occ_up': occ_up, 'gross_up': gross_up,
        'adr_down': adr_down, 'occ_down': occ_down, 'gross_down': gross_down,
        'platform_fee': platform_fee, 'cleaning': cleaning, 'insurance': insurance,
        'prop_tax': prop_tax, 'hoa_annual': hoa_annual, 'utilities': utilities,
        'maintenance': maintenance, 'furn_reserve': furn_reserve,
        'internet': internet, 'permit_cost': permit, 'accounting': accounting, 'misc': misc,
        'total_opex': total_opex, 'pm_cost': pm_cost,
        'noi': noi, 'noi_up': noi_up, 'noi_down': noi_down,
        'cf': cf, 'cf_up': cf_up, 'cf_down': cf_down,
        'coc': coc, 'coc_up': coc_up, 'coc_down': coc_down,
        'cap_rate': cap_rate, 'dscr': dscr,
        'bldg_val': bldg_val, 'depreciation': depreciation,
        'tax_benefit': tax_benefit, 'appr_rate': appr_rate, 'appr_val': appr_val,
        'yr1_principal': yr1_principal, 'total_ret': total_ret, 'total_ret_pct': total_ret_pct,
        'monthly': monthly, 'projections': projections,
        'is_carib': is_carib, 'is_domestic': is_domestic,
        'market_label': MARKET_CONFIG.get(market_type, MARKET_CONFIG['coastal_standard'])['label'],
        'turnovers': turnovers, 'clean_per': clean_per, 'avg_stay': avg_stay,
    }

# ─── Verdict ─────────────────────────────────────────────────────────────────

def get_verdict(f, data):
    coc = f['coc']
    country = data.get('country', 'United States')
    bedrooms = int(safe_float(data.get('bedrooms'), 2))
    prop_type = data.get('property_type', 'property').lower()
    city = data.get('city', 'this market')
    price = f['price']
    gross = f['gross']
    adr = f['adr']
    occ = f['occ']

    if coc >= 0.08:
        verdict, css, banner = 'Buy', 'buy', 'buy'
        tagline = f"Strong cash-on-cash return of {fmt_pct(coc*100)} with solid fundamentals across all three scenarios."
        deal_v = (f"This {bedrooms}BR {prop_type} in {city} is a compelling STR acquisition at {usd(price)}. "
                  f"A {fmt_pct(coc*100)} cash-on-cash return and {fmt_pct(f['cap_rate']*100)} cap rate place it in the top tier "
                  f"of comparable listings in this segment. The key driver is the combination of strong occupancy fundamentals "
                  f"and manageable operating costs relative to purchase price — a balance that is increasingly difficult to find "
                  f"in mature coastal markets.")
    elif coc >= 0.04:
        verdict, css, banner = 'Conditional Buy', 'buy', 'buy'
        tagline = f"Positive cash flow with {fmt_pct(coc*100)} CoC — workable with disciplined execution and dynamic pricing."
        deal_v = (f"This {bedrooms}BR {prop_type} in {city} represents a workable STR investment at {usd(price)}, with returns "
                  f"that are positive but dependent on above-average execution. The {fmt_pct(coc*100)} cash-on-cash return leaves "
                  f"limited margin for error — outperformance requires disciplined dynamic pricing, Superhost-level reviews, and "
                  f"active shoulder-season demand generation. The deal works; it just does not offer significant cushion against "
                  f"occupancy softness or rising expenses.")
    elif coc >= 0.0:
        verdict, css, banner = 'Watch', 'watch', 'watch'
        tagline = f"Marginally cash-flow positive at {fmt_pct(coc*100)} CoC — proceed only with pricing flexibility or a lower entry point."
        deal_v = (f"This {bedrooms}BR {prop_type} in {city} sits at the margin of investment viability at {usd(price)}. "
                  f"The {fmt_pct(coc*100)} cash-on-cash return provides minimal cushion against occupancy softness or unexpected "
                  f"expenses. The deal is not broken, but it requires a specific combination of conditions — strong execution, "
                  f"cooperative seasonality, and stable operating costs — to remain cash-flow positive year-round. "
                  f"A price reduction of 8–12% would meaningfully improve the return profile.")
    else:
        verdict, css, banner = 'Pass', 'pass', 'pass'
        tagline = f"Negative cash flow of {usd(abs(f['cf']))} annually under current financing — does not pencil at this price."
        deal_v = (f"At {usd(price)}, this {bedrooms}BR {prop_type} in {city} does not generate sufficient STR revenue to support "
                  f"the financing stack. The {fmt_pct(coc*100)} cash-on-cash return means out-of-pocket cash contributions are "
                  f"required annually to cover debt service. Unless purchased all-cash at a significant price reduction, or held "
                  f"primarily as a personal-use asset with incidental rental income, the investment case does not hold under "
                  f"current market conditions and financing rates.")

    rev_v = (f"The base-case ADR of {usd(adr)} and {fmt_pct(occ*100)} occupancy represent a realistic but not conservative "
             f"projection for a {bedrooms}BR {prop_type} in this segment. Achieving the upside scenario ({usd(f['adr_up'])} ADR / "
             f"{fmt_pct(f['occ_up']*100)} occupancy) requires Superhost status on Airbnb, Premier Host on VRBO, professional "
             f"photography, and active dynamic pricing management. The downside scenario models a year of minimal optimization "
             f"or a soft demand environment, which remains a real risk in highly seasonal markets where 60%+ of revenue is "
             f"earned in a 10-week window.")

    country = data.get('country', 'United States')
    mkt_type = data.get('market_type', 'coastal_standard')
    if country == 'Dominican Republic':
        mkt_d = ("Punta Cana handles 65%+ of DR foreign tourist arrivals, and the market added significant new Airbnb supply "
                 "in 2024–2025. Competition is intensifying, but revenue per listing continues to grow year-over-year as the "
                 "destination matures. The CONFOTUR tax incentive program is the primary structural advantage for new buyers — "
                 "15 years of 0% property tax and 0% income tax on certified projects represent a meaningful total-return "
                 "enhancement that is difficult to replicate in any other Caribbean market at this price point.")
    elif country in ('Turks & Caicos',):
        mkt_d = ("Turks & Caicos commands the highest ADR in the Western Hemisphere for resort real estate. Grace Bay Beach "
                 "consistently earns the world's top beach ranking, underpinning premium pricing. The market is highly "
                 "seasonal — revenue concentrates in the November through April dry season — but the absence of property taxes "
                 "and capital gains taxes creates a structurally favorable holding environment. Supply is constrained by island "
                 "geography and strict development controls, which supports long-term value appreciation.")
    elif country == 'Bahamas':
        mkt_d = ("The Bahamas benefits from its 30-minute proximity to Florida, making it the premier choice for US weekend "
                 "luxury rentals. The Out Islands (Exuma, Eleuthera, Harbour Island) command dramatically higher rates than "
                 "Nassau-area condos. Supply is spread across 700+ islands, limiting direct competitive pressure in most "
                 "sub-markets. The primary risk is hurricane exposure June through November, which suppresses occupancy in the "
                 "shoulder season and requires comprehensive insurance coverage.")
    elif mkt_type == 'coastal_premium':
        mkt_d = (f"The {city} coastal premium market benefits from constrained beachfront supply and strong repeat-visitor "
                 "loyalty. Oceanfront and first-row properties command a 40–60% ADR premium over comparable inland units. "
                 "Summer demand is effectively inelastic — quality properties are booked 8–12 weeks in advance through July. "
                 "The primary risk is regulatory — municipalities along the NC coast have increasingly scrutinized STR "
                 "permitting, and HOA restrictions continue to tighten in condo complexes built before 2010.")
    elif mkt_type == 'mountain':
        mkt_d = (f"The {city} mountain market benefits from a dual-season demand profile: winter ski traffic and summer "
                 "outdoor recreation, with a meaningful shoulder in fall foliage. This flattened seasonality curve meaningfully "
                 "reduces cash-flow risk versus pure-coastal markets. Supply growth has been strong since 2020, with new "
                 "construction adding inventory in most sub-markets — differentiation through quality, hot tub access, and "
                 "ski-in/ski-out proximity is increasingly critical to achieving top-quartile ADR.")
    else:
        mkt_d = (f"The {city} STR market serves a drive-to demand base anchored by weekend and vacation travelers from "
                 f"regional population centers. Seasonality is pronounced, with the top 3 months typically generating 45–55% "
                 f"of annual revenue. Active Airbnb supply has grown materially since 2020, increasing competitive pressure "
                 f"on properties that are not actively managed and priced with dynamic tools. Top-performing properties "
                 f"maintain occupancy 8–10 percentage points above market average through Superhost status and professional "
                 f"photography alone.")

    return verdict, css, banner, tagline, deal_v, rev_v, mkt_d

# ─── Risk Items ───────────────────────────────────────────────────────────────

def get_risks(data, f):
    country = data.get('country', 'United States')
    mkt_type = data.get('market_type', 'coastal_standard')
    year_built = int(safe_float(data.get('year_built'), 2000))
    age = datetime.now().year - year_built
    occ = f['occ']
    coc = f['coc']
    hoa = f['hoa_annual']
    is_carib = f['is_carib']

    risks = []

    # Weather
    if is_carib or country in ('U.S. Virgin Islands', 'Puerto Rico'):
        risks.append(('red', 'Hurricane / tropical storm', 'Peak hurricane season Jun–Nov overlaps with shoulder/off-season. Verify wind and flood coverage; budget for a 6-week revenue gap in a direct-hit scenario.'))
    elif mkt_type in ('coastal_premium', 'coastal_standard'):
        risks.append(('amber', 'Hurricane / weather exposure', 'Coastal properties face elevated storm risk. Confirm flood zone designation and verify insurance covers named storms. NC coast has seen direct hits from Florence (2018) and Dorian (2019).'))
    else:
        risks.append(('green', 'Weather risk', 'Inland/mountain location carries limited hurricane exposure. Standard homeowner and liability coverage applies.'))

    # Seasonality
    peak_months = sum(1 for m in f['monthly'] if m['season'] == 'Peak')
    if peak_months <= 3:
        risks.append(('red', 'Seasonality / cash flow gaps', f'Revenue heavily concentrated in {peak_months} peak months. Build a 4–5 month operating reserve before first guest. Off-season months may not cover fixed costs.'))
    elif peak_months <= 5:
        risks.append(('amber', 'Seasonality / cash flow gaps', f'Moderate seasonality — {peak_months} strong months with meaningful shoulder revenue. Maintain a 2–3 month cash reserve for slower periods.'))
    else:
        risks.append(('green', 'Seasonality / cash flow', 'Relatively flat seasonality limits cash-flow volatility. Year-round demand provides stable income across all months.'))

    # STR regulation
    if country == 'Dominican Republic':
        risks.append(('green', 'STR regulation', 'DR has no national STR licensing framework. Community-level HOA rules apply. Verify bylaws permit short-term rentals before closing.'))
    elif country in ('Turks & Caicos', 'Cayman Islands'):
        risks.append(('green', 'STR regulation', 'TCI/Cayman have minimal STR-specific regulations. Licensing requirements are straightforward; the market is STR-friendly at the government level.'))
    elif mkt_type in ('coastal_premium', 'coastal_standard'):
        risks.append(('amber', 'STR regulation', 'NC state law (§160D-1207) prevents outright municipal STR bans but local registration and zoning rules still apply. HOA CC&Rs are the primary risk — verify STRs are explicitly permitted before closing.'))
    else:
        risks.append(('amber', 'STR regulation', 'Local ordinances vary. Verify zoning permits STR use, obtain any required permits, and monitor for regulatory changes. HOA governing documents require review before offer.'))

    # Foreign ownership / legal
    if is_carib:
        if country == 'Dominican Republic':
            risks.append(('amber', 'Foreign ownership / legal', 'DR allows 100% foreign ownership but title defects are common. Title insurance from a reputable DR company is essential. Use a bilingual local attorney — not the developer\'s attorney.'))
        elif country in ('Turks & Caicos', 'Cayman Islands', 'Bahamas'):
            risks.append(('amber', 'Foreign ownership / legal', 'Foreign ownership is permitted with straightforward registration. Engage local counsel familiar with the International Persons Landholding Act or equivalent. Title process is reliable but slower than US.'))
        else:
            risks.append(('amber', 'Foreign ownership / title', 'Foreign ownership allowed but title research standards vary. Title insurance and independent legal representation are non-negotiable.'))
    else:
        risks.append(('green', 'Legal / ownership', 'Domestic purchase within standard US legal framework. Standard title insurance and closing process applies. 1031 exchange eligible if sold for investment purposes.'))

    # Building age
    if age > 25:
        risks.append(('red', f'Building age / CapEx', f'Built {year_built} ({age} years old). Elevated near-term capital expenditure risk: HVAC, plumbing, electrical, and roof replacement possible within 5-year hold. Budget 1.5% of purchase price annually.'))
    elif age > 10:
        risks.append(('amber', f'Building age / maintenance', f'Built {year_built} ({age} years old). Moderate deferred maintenance risk. HVAC systems typically require replacement at 15–20 years. Budget 0.8–1.0% of purchase price annually.'))
    else:
        risks.append(('green', f'Building age / maintenance', f'Built {year_built} ({age} years old). Low near-term capital expenditure risk. Standard maintenance reserve of 0.5% of purchase price per year is appropriate.'))

    # HOA
    if hoa > 10000:
        risks.append(('red', 'HOA / fees', f'{usd(hoa)}/yr HOA consumes {fmt_pct(hoa/f["gross"]*100)} of gross revenue. Review financials carefully — special assessments are common in older coastal buildings. Confirm STRs are permitted in CC&Rs.'))
    elif hoa > 4000:
        risks.append(('amber', 'HOA / fees', f'{usd(hoa)}/yr HOA. Request the last 2 years of board meeting minutes and reserve fund study. Verify STRs are explicitly permitted in the governing documents.'))
    elif hoa > 0:
        risks.append(('green', 'HOA / fees', f'{usd(hoa)}/yr HOA is manageable. Confirm STR activity is permitted in community bylaws and review for any minimum-stay requirements.'))

    # Interest rate / exit
    risks.append(('green', 'Interest rate risk', f'Fixed-rate mortgage at {fmt_pct(f["rate"])} eliminates rate re-pricing exposure. Loan locks in debt service for the full {f["term"]}-year term.'))

    return risks[:8]  # cap at 8

# ─── Tax & Legal Flags ────────────────────────────────────────────────────────

def get_tax_flags(data, f):
    country = data.get('country', 'United States')
    price = f['price']
    bldg = f['bldg_val']
    depr = f['depreciation']
    is_carib = f['is_carib']

    if country == 'Dominican Republic':
        return (
            f"<strong>Occupancy / VAT:</strong> DR charges 18% ITBIS (VAT) on rental income. Major platforms may collect automatically — verify with a local accountant before first booking.<br><br>"
            f"<strong>Property tax (IPI):</strong> 1% annually on assessed value above ~RD$9.9M (~$170K USD). CONFOTUR-certified projects are exempt for 15 years — verify certification status with the developer before closing.<br><br>"
            f"<strong>Income tax:</strong> DR taxes rental income at 27%. US owners must also report on Schedule E and may claim Foreign Tax Credits to avoid double taxation. Consult a CPA experienced in US-foreign property.<br><br>"
            f"<strong>FBAR / Form 8938:</strong> Required if aggregate foreign financial accounts exceed $10,000 at any point in the year. File annually with your US tax return.<br><br>"
            f"<strong>Depreciation:</strong> Building value ~{usd(bldg)} / 27.5 years = ~{usd(depr)}/yr for US tax purposes (40-year schedule may apply to foreign property — confirm with CPA).<br><br>"
            f"<strong>Recommended team:</strong> (1) Bilingual DR real estate attorney for title/closing; (2) DR-licensed accountant for IPI and ITBIS; (3) US CPA for Schedule E, FBAR, and Foreign Tax Credits; (4) Title insurance company."
        )
    elif country in ('Turks & Caicos',):
        return (
            f"<strong>Property tax:</strong> None — TCI has no annual property tax. This is a structural advantage that meaningfully improves long-term total return versus comparable US markets.<br><br>"
            f"<strong>Capital gains tax:</strong> None in TCI. Proceeds on sale are tax-free locally.<br><br>"
            f"<strong>Stamp duty:</strong> 10% on purchase price for non-belongers. Factor into acquisition cost modeling.<br><br>"
            f"<strong>US income tax:</strong> All rental income must be reported on Schedule E. Foreign Tax Credits available where applicable. FBAR/Form 8938 required if foreign accounts exceed thresholds.<br><br>"
            f"<strong>Depreciation:</strong> Building value ~{usd(bldg)} / 27.5 years = ~{usd(depr)}/yr (40-year schedule may apply — confirm with CPA).<br><br>"
            f"<strong>Recommended team:</strong> (1) TCI-licensed real estate attorney; (2) US CPA familiar with foreign property; (3) Title insurance company."
        )
    elif country == 'U.S. Virgin Islands':
        return (
            f"<strong>USVI tax incentives:</strong> The USVI Economic Development Authority (EDA) offers substantial income tax reductions (up to 90%) for qualifying businesses. Consult a USVI attorney to evaluate eligibility.<br><br>"
            f"<strong>1031 exchange:</strong> USVI properties are US territory and fully eligible as replacement or relinquished property in a 1031 exchange — a significant advantage over foreign Caribbean alternatives.<br><br>"
            f"<strong>Property tax:</strong> Approximately 0.95% of assessed value annually — lower than most US coastal markets.<br><br>"
            f"<strong>Depreciation:</strong> Standard US treatment applies. Building value ~{usd(bldg)} / 27.5 years = ~{usd(depr)}/yr deduction.<br><br>"
            f"<strong>14-day rule:</strong> Personal use exceeding 14 days or 10% of rental days may limit deduction eligibility. Track carefully.<br><br>"
            f"<strong>Recommended team:</strong> (1) USVI real estate attorney for title and closing; (2) CPA familiar with USVI EDA incentives; (3) 1031 Qualified Intermediary if exchanging."
        )
    else:
        return (
            f"<strong>Occupancy tax:</strong> NC state sales tax (6.75%) plus local county occupancy tax (varies 3–8%). Major platforms (Airbnb, VRBO) collect and remit automatically in NC — confirm coverage for your county before listing.<br><br>"
            f"<strong>Property tax:</strong> Estimated {usd(f['prop_tax'])}/yr based on assessed value. Verify with county tax assessor — purchase price often triggers reassessment within 1–2 years.<br><br>"
            f"<strong>Income tax:</strong> Report on Schedule E (if personal use &lt;15 days/year) or Schedule C (pure investment). Consult a CPA to determine optimal treatment.<br><br>"
            f"<strong>Depreciation:</strong> Building value ~{usd(bldg)} / 27.5 years = ~{usd(depr)}/yr federal deduction. NC conforms to federal depreciation rules.<br><br>"
            f"<strong>14-day rule:</strong> Personal use exceeding 14 days or 10% of rented days converts property to mixed-use and limits expense deductions. Track personal use rigorously.<br><br>"
            f"<strong>1031 exchange:</strong> Fully eligible as US investment property. Consult a Qualified Intermediary before listing for sale.<br><br>"
            f"<strong>Recommended team:</strong> (1) STR-experienced local real estate attorney for HOA/title review; (2) CPA familiar with STR Schedule E; (3) Fee-only fiduciary financial planner (NAPFA)."
        )

# ─── Regulatory ───────────────────────────────────────────────────────────────

def get_regulatory(data, f):
    country = data.get('country', 'United States')
    bedrooms = int(safe_float(data.get('bedrooms'), 2))

    if country == 'Dominican Republic':
        rows = [('Permit Required','No'),('Permit Cost','$0/year'),
                ('Night Limit','None'),('Primary Residence Required','No'),
                ('Max Guests (est.)',str(bedrooms * 2 + 2)),
                ('Regulation Level','Minimal — no national STR licensing'),
                ('Tax Collection','Verify ITBIS auto-collection with each platform')]
        checklist = [('CONFOTUR Certification','Verify developer approval before closing'),
                     ('Title Insurance','Obtain from reputable DR title company'),
                     ('Legal Review','Engage bilingual DR real estate attorney'),
                     ('HOA Rules Review','Confirm STRs permitted in community bylaws'),
                     ('Insurance','Property + liability + hurricane/flood coverage'),
                     ('US Tax Compliance','Set up FBAR/FATCA with US CPA')]
    elif country in ('Turks & Caicos',):
        rows = [('Permit Required','Business license required'),('Permit Cost','~$500/year'),
                ('Night Limit','None'),('Primary Residence Required','No'),
                ('Max Guests (est.)',str(bedrooms * 2 + 2)),
                ('Regulation Level','Light — STR-friendly jurisdiction'),
                ('Tax Collection','No occupancy tax; VAT may apply — verify')]
        checklist = [('Business License','Obtain TCI business/hotel license'),
                     ('Title Insurance','Required for non-belongers'),
                     ('Legal Review','Engage TCI-licensed real estate attorney'),
                     ('HOA Review','Confirm STRs permitted in community docs'),
                     ('Insurance','Property + liability + hurricane coverage'),
                     ('US Tax Compliance','FBAR/Foreign Tax Credits via US CPA')]
    else:
        rows = [('Permit Required','Yes — local registration'),
                ('Permit Cost','~$250/year (varies by municipality)'),
                ('Night Limit','Check local ordinance'),
                ('Primary Residence Required','No'),
                ('Max Guests (est.)',str(bedrooms * 2 + 2)),
                ('Local Contact','Required — must respond within 1 hour'),
                ('Regulation Level','Research specific municipality'),
                ('Tax Collection','Airbnb/VRBO auto-collect in NC — verify county')]
        checklist = [('STR Registration','Apply with local planning department'),
                     ('Safety Inspection','Schedule before first guest'),
                     ('Emergency Info','Post in unit per local requirements'),
                     ('Local Contact','Designate 24/7 emergency contact'),
                     ('HOA Review','Verify STRs permitted in CC&Rs'),
                     ('Liability Insurance','Consider supplemental STR liability coverage')]
    return rows, checklist

# ─── Next Steps ───────────────────────────────────────────────────────────────

def get_next_steps(data, f):
    country = data.get('country', 'United States')
    hoa = f['hoa_annual']
    is_carib = f['is_carib']
    year_built = int(safe_float(data.get('year_built'), 2000))
    reserve = max(8000, f['total_opex'] * 0.30)
    coc = f['coc']

    steps = []

    if hoa > 0:
        steps.append("Review HOA CC&Rs and the last 2 years of board meeting minutes to confirm STRs are explicitly permitted — not just tolerated. Request the reserve fund study and check for any pending special assessments.")
    if is_carib:
        steps.append(f"Engage a licensed, independent {country} real estate attorney (not the developer's attorney) for title search, CONFOTUR verification, and closing. Title insurance is non-negotiable.")
    steps.append(f"Validate revenue projections by pulling active comparable listings on AirDNA or Rabbu for this specific property type and sub-market. Identify the top-performing 3–5 comps and analyze their pricing strategy.")
    if not is_carib:
        steps.append("Schedule a full property inspection with specific attention to HVAC age and condition, moisture intrusion, electrical panel, and roof. For coastal properties, include a wind mitigation inspection for insurance rating.")
    if coc < 0.05:
        steps.append(f"Use the current financing environment as a negotiating lever — request a price reduction of 8–12% or seller concessions to improve the return profile to Conditional Buy threshold.")
    steps.append(f"Engage a CPA experienced in STR tax treatment before closing — not after. Depreciation strategy, entity structure (LLC vs. personal), and the 14-day rule election all have meaningful tax implications.")
    steps.append(f"Build a {usd(reserve)} liquid operating reserve before accepting the first guest booking — equivalent to approximately 3 months of total operating costs and debt service.")
    steps.append("Set up dual listings on Airbnb and VRBO from day one. Commission professional photography before first listing — properties with professional photos earn 15–25% more per night on average.")

    return steps[:8]

# ─── HTML Generator ──────────────────────────────────────────────────────────

def generate_html_report(data):
    f  = calculate(data)
    v, css, banner, tagline, deal_v, rev_v, mkt_d = get_verdict(f, data)
    risks   = get_risks(data, f)
    tax_txt = get_tax_flags(data, f)
    reg_rows, reg_checklist = get_regulatory(data, f)
    steps   = get_next_steps(data, f)

    client_name = esc(data.get('client_name', 'Investor'))
    address     = esc(data.get('address', 'Investment Property'))
    city        = esc(data.get('city', ''))
    state       = esc(data.get('state', ''))
    country     = esc(data.get('country', 'United States'))
    zip_code    = esc(data.get('zip', ''))
    community   = esc(data.get('community', ''))
    prop_type   = esc(data.get('property_type', 'Property'))
    bedrooms    = esc(data.get('bedrooms', ''))
    bathrooms   = esc(data.get('bathrooms', ''))
    sqft_raw    = safe_float(data.get('sqft', 0))
    sqft_str    = f"{sqft_raw:,.0f} SF" if sqft_raw else ''
    year_built  = esc(data.get('year_built', ''))
    condition   = esc(data.get('condition', ''))
    parking     = esc(data.get('parking', ''))
    beach       = esc(data.get('beach_access', 'N/A'))
    access      = esc(data.get('building_access', ''))
    features    = esc(data.get('special_features', ''))
    mkt_label   = esc(f['market_label'])

    report_date = datetime.now().strftime('%m/%d/%Y')
    report_num  = datetime.now().strftime('%Y-%m-%d') + '-' + address[:4].replace(' ','').upper()

    # Location string
    loc_parts = [p for p in [city, state, zip_code] if p]
    location  = ', '.join(loc_parts) + (f' · {country}' if country not in ('United States',) else '')
    meta_parts = [p for p in [community, f"{bedrooms}BR/{bathrooms}BA", sqft_str, prop_type, f"ASK: {usd(f['price'])}"] if p]
    meta_str  = ' · '.join(meta_parts)

    # Amenities
    amenity_map = {
        'amenity_outdoor_pool':  ('🏊','Outdoor Pool','Seasonal community access'),
        'amenity_indoor_pool':   ('🏊‍♂️','Indoor Pool','Year-round access'),
        'amenity_hot_tub':       ('🛁','Hot Tub / Spa','Community access'),
        'amenity_fitness':       ('💪','Fitness Center','Full gymnasium'),
        'amenity_tennis':        ('🎾','Tennis / Pickleball','Court access'),
        'amenity_basketball':    ('🏀','Basketball Court','Outdoor court'),
        'amenity_beach_access':  ('🏖️','Beach Access','Private walkways'),
        'amenity_playground':    ('🛝','Playground','Family-friendly'),
        'amenity_boat_dock':     ('🚤','Boat Dock','Water access'),
        'amenity_grill':         ('🔥','Grill / Fire Pit','Outdoor cooking area'),
    }
    amenities = [(icon, name, detail) for key,(icon,name,detail) in amenity_map.items() if data.get(key)]
    other_am  = [a.strip() for a in str(data.get('other_amenities','')).split(',') if a.strip()]
    for a in other_am:
        amenities.append(('✦', a, ''))

    amenity_html = ''
    if amenities:
        boxes = ''.join(f'<div class="amenity-box"><div class="amenity-icon">{icon}</div><div class="amenity-name">{esc(name)}</div><div class="amenity-detail">{esc(detail)}</div></div>' for icon,name,detail in amenities)
        am_names = ', '.join(n for _,n,_ in amenities)
        amenity_html = f'''
<div class="section-title">Community amenities — competitive advantage</div>
<div class="amenity-grid">{boxes}</div>
<div class="analysis-block"><p>The property features {esc(am_names)} — amenities that support premium nightly rates, reduce vacancy, and improve guest satisfaction scores critical to Superhost/Premier Host status.</p></div>'''

    # Monthly projection rows
    monthly_rows = ''
    for m in f['monthly']:
        is_peak = m['season'] == 'Peak'
        is_off  = m['season'] == 'Off'
        bg  = "background:rgba(42,122,75,0.04)" if is_peak else ''
        rev_style = 'color:var(--green)' if is_peak else ('color:var(--accent)' if is_off else '')
        sea_style = 'color:var(--green)' if is_peak else ('color:var(--accent)' if is_off else 'color:var(--amber)')
        bold = '<strong>' if is_peak else ''
        endb = '</strong>' if is_peak else ''
        monthly_rows += (
            f'<tr style="{bg}"><td>{bold}{esc(m["month"])}{endb}</td>'
            f'<td>{usd(m["adr"])}</td><td>{m["occ"]*100:.0f}%</td>'
            f'<td>{m["nights"]}</td>'
            f'<td style="{rev_style}">{bold}{usd(m["rev"])}{endb}</td>'
            f'<td style="{sea_style}">{m["season"]}</td></tr>\n'
        )

    # Risk grid
    risk_html = ''.join(
        f'<div class="risk-cell"><div class="risk-header"><div class="risk-dot {color}"></div><div class="risk-name">{esc(name)}</div></div><div class="risk-note">{esc(note)}</div></div>\n'
        for color, name, note in risks
    )

    # Regulatory rows
    reg_html = ''.join(
        f'<div class="detail-row"><span class="detail-label">{esc(lbl)}</span><span class="detail-value">{esc(val)}</span></div>'
        for lbl, val in reg_rows
    )
    checklist_html = ''.join(
        f'<tr><td>{esc(req)}</td><td>{esc(action)}</td></tr>'
        for req, action in reg_checklist
    )

    # 5-year rows
    proj_html = ''
    for p in f['projections']:
        proj_html += (
            f"<tr><td>Gross Revenue</td><td>{usd(p['gross'])}</td></tr>"  if p['year']==1 else ''
        )
    proj_rows = ''
    for p in f['projections']:
        proj_rows += (
            f"<td>{usd(p['gross'])}</td>"
        )

    # Full 5-year table rows
    def yr_row(label, vals, cls=''):
        cells = ''.join(f'<td>{v}</td>' for v in vals)
        return f'<tr class="{cls}"><td>{label}</td>{cells}</tr>\n'

    yrs = f['projections']
    proforma_rows = (
        yr_row('Gross Revenue',        [usd(p['gross'])    for p in yrs]) +
        yr_row('Platform Fees',        [f"({usd(p['platform'])})" for p in yrs]) +
        yr_row('Cleaning',             [f"({usd(p['cleaning'])})" for p in yrs]) +
        yr_row('Net Rental Revenue',   [usd(p['gross']-p['platform']-p['cleaning']) for p in yrs], 'row-total') +
        yr_row('Operating Expenses',   [f"({usd(p['opex'])})" for p in yrs]) +
        yr_row('NOI',                  [usd(p['noi'])      for p in yrs], 'row-total') +
        yr_row('Debt Service',         [f"({usd(p['debt'])})" for p in yrs]) +
        yr_row('Pre-Tax Cash Flow',    [usd(p['cf'])       for p in yrs], 'row-total') +
        yr_row('Cumulative Cash Flow', [usd(p['cum_cf'])   for p in yrs]) +
        yr_row('Property Value',       [usd(p['value'])    for p in yrs]) +
        yr_row('Loan Balance',         [usd(p['loan'])     for p in yrs]) +
        yr_row('Total Equity',         [usd(p['equity'])   for p in yrs], 'row-total') +
        yr_row('Cash-on-Cash Return',  [fmt_pct(p['coc']*100) for p in yrs])
    )

    # Steps
    steps_html = ''.join(
        f'<li><span class="step-num">{str(i+1).zfill(2)}</span><span class="step-text">{esc(s)}</span></li>'
        for i, s in enumerate(steps)
    )

    # Expense table
    gross = f['gross']
    def exp_row(label, amt, note):
        pct_of_gross = amt / gross * 100 if gross else 0
        return (f'<tr><td>{label}</td><td>{usd(amt)}</td>'
                f'<td>{usd(amt/12)}</td>'
                f'<td>{fmt_pct(pct_of_gross)}</td>'
                f'<td>{note}</td></tr>\n')

    turnovers_approx = round(f['turnovers'])
    ins_note = 'Included in HOA' if f['hoa_annual'] > 0 and safe_float(data.get('hoa_includes_insurance','No').replace('Yes','1').replace('No','0')) else ('Coastal wind + liability' if not f['is_carib'] else 'Property + liability; hurricane coverage')
    expense_rows = (
        exp_row('HOA / community fees', f['hoa_annual'], 'Pool, grounds, insurance (if included)' if f['hoa_annual'] else 'No HOA') +
        exp_row('Property tax', f['prop_tax'], 'CONFOTUR exempt (15 yrs)' if data.get('country')=='Dominican Republic' else 'Est. assessed value × local rate') +
        exp_row('Utilities (electric, water)', f['utilities'], 'A/C dominant cost' if f['is_carib'] else 'HVAC, water, guest usage') +
        exp_row('Internet / WiFi', f['internet'], 'High-speed required for guest satisfaction') +
        exp_row('Repairs & maintenance', f['maintenance'], f'Age-based rate; {data.get("year_built","")}-vintage property') +
        exp_row('Furnishing reserve', f['furn_reserve'], 'Annual refresh set-aside') +
        exp_row('Insurance', f['insurance'], ins_note) +
        exp_row('STR permit & license', f['permit_cost'], 'Annual registration' if not f['is_carib'] else 'Not required') +
        exp_row('Accounting / tax prep', f['accounting'], 'STR-specific CPA' + (' + FBAR/FATCA' if f['is_carib'] else '')) +
        exp_row('Miscellaneous / contingency', f['misc'], 'Unforeseen guest issues, supplies') +
        exp_row('Platform booking fees', f['platform_fee'], f'Blended ~5.5% of gross (Airbnb 3% + VRBO 8%)') +
        exp_row('Cleaning & turnover', f['cleaning'], f'~{usd(f["clean_per"])}/clean × {turnovers_approx} turnovers/yr')
    )
    opex_pct = f['total_opex'] / gross * 100 if gross else 0
    debt_pct  = f['annual_debt'] / gross * 100 if gross else 0
    allin_pct = (f['total_opex'] + f['annual_debt']) / gross * 100 if gross else 0

    # Market analysis city/country label
    mkt_analysis_label = f"{city}, {country}" if city else country

    dscr_str = f"{f['dscr']:.2f}x" if f['dscr'] != float('inf') and f['annual_debt'] > 0 else 'N/A (all-cash)'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>STR Deal Analysis — {address}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:#1a1a18;--paper:#ffffff;--accent:#c84b2f;
    --muted:#7a7870;--light:#f5f2eb;--border:rgba(26,26,24,0.15);
    --green:#2a7a4b;--amber:#b8942a;
    --serif:'DM Serif Display',Georgia,serif;
    --mono:'DM Mono',monospace;--sans:'DM Sans',sans-serif;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:var(--sans);font-weight:300;font-size:13px;line-height:1.65;
        color:var(--ink);background:white;max-width:820px;margin:0 auto;padding:3rem 2.5rem}}
  .report-header{{display:flex;justify-content:space-between;align-items:flex-start;
    padding-bottom:1.5rem;border-bottom:2px solid var(--ink);margin-bottom:2rem}}
  .brand{{font-family:var(--mono);font-size:11px;letter-spacing:.14em;color:var(--muted)}}
  .report-id{{font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right}}
  .report-id span{{display:block}}
  .title-block{{margin-bottom:2rem}}
  .property-name{{font-family:var(--serif);font-size:32px;line-height:1.1;margin-bottom:.5rem}}
  .property-meta{{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.06em}}
  .verdict-banner{{padding:1rem 1.25rem;margin-bottom:2rem;display:flex;align-items:center;justify-content:space-between}}
  .verdict-banner.buy{{border-left:4px solid var(--green);background:rgba(42,122,75,0.06)}}
  .verdict-banner.pass{{border-left:4px solid var(--accent);background:rgba(200,75,47,0.06)}}
  .verdict-banner.watch{{border-left:4px solid var(--amber);background:rgba(184,148,42,0.06)}}
  .verdict-label{{font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:var(--muted)}}
  .verdict-text{{font-family:var(--serif);font-size:22px}}
  .verdict-text.buy{{color:var(--green)}}.verdict-text.pass{{color:var(--accent)}}.verdict-text.watch{{color:var(--amber)}}
  .section-title{{font-family:var(--mono);font-size:10px;letter-spacing:.14em;color:var(--muted);
    text-transform:uppercase;border-bottom:.5px solid var(--border);padding-bottom:.5rem;
    margin-bottom:1rem;margin-top:2.5rem}}
  .metrics-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);margin-bottom:.5rem}}
  .metric-box{{background:white;padding:1rem}}
  .metric-label{{font-family:var(--mono);font-size:9px;letter-spacing:.1em;color:var(--muted);margin-bottom:4px}}
  .metric-val{{font-family:var(--serif);font-size:26px;line-height:1}}
  .metric-val.green{{color:var(--green)}}.metric-val.red{{color:var(--accent)}}.metric-val.amber{{color:var(--amber)}}
  .metric-sub{{font-size:11px;color:var(--muted);margin-top:2px}}
  table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:.5rem}}
  th{{font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--muted);
      text-align:left;padding:.5rem .75rem;border-bottom:1px solid var(--border);background:var(--light)}}
  td{{padding:.6rem .75rem;border-bottom:.5px solid var(--border)}}
  tr:last-child td{{border-bottom:none}}
  .scenario-upside td{{color:var(--green)}}.scenario-downside td{{color:var(--accent)}}
  .row-label{{font-weight:500;color:var(--muted)}}.row-total{{font-weight:500;background:var(--light)}}
  .analysis-block{{margin-bottom:1.5rem}}
  .analysis-block h3{{font-family:var(--sans);font-weight:500;font-size:14px;margin-bottom:.5rem}}
  .analysis-block p{{color:var(--muted);line-height:1.75}}
  .risk-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border)}}
  .risk-cell{{background:white;padding:.875rem 1rem}}
  .risk-header{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
  .risk-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
  .risk-dot.green{{background:var(--green)}}.risk-dot.amber{{background:var(--amber)}}.risk-dot.red{{background:var(--accent)}}
  .risk-name{{font-weight:500;font-size:12px}}.risk-note{{font-size:11px;color:var(--muted);padding-left:16px}}
  .steps-list{{list-style:none}}
  .steps-list li{{display:flex;gap:1rem;padding:.75rem 0;border-bottom:.5px solid var(--border)}}
  .steps-list li:last-child{{border-bottom:none}}
  .step-num{{font-family:var(--mono);font-size:11px;color:var(--accent);flex-shrink:0;width:24px}}
  .step-text{{font-size:13px;line-height:1.6}}
  .amenity-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;background:var(--border);margin-bottom:1rem}}
  .amenity-box{{background:white;padding:.75rem 1rem}}
  .amenity-icon{{font-size:18px;margin-bottom:4px}}
  .amenity-name{{font-weight:500;font-size:12px}}.amenity-detail{{font-size:11px;color:var(--muted)}}
  .detail-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0}}
  .detail-row{{display:flex;justify-content:space-between;padding:.45rem .75rem;border-bottom:.5px solid var(--border)}}
  .detail-label{{font-size:12px;color:var(--muted)}}.detail-value{{font-size:12px;font-weight:500;text-align:right}}
  .highlight-box{{background:var(--light);padding:1rem 1.25rem;margin:1rem 0;border-left:3px solid var(--accent)}}
  .highlight-box .hl-label{{font-family:var(--mono);font-size:9px;letter-spacing:.1em;color:var(--accent);margin-bottom:4px}}
  .highlight-box .hl-text{{font-size:13px;line-height:1.65}}
  .return-stack{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:1px;background:var(--border);margin:1rem 0}}
  .return-item{{background:white;padding:.875rem 1rem;text-align:center}}
  .return-label{{font-family:var(--mono);font-size:9px;letter-spacing:.1em;color:var(--muted);margin-bottom:4px}}
  .return-val{{font-family:var(--serif);font-size:20px}}.return-sub{{font-size:10px;color:var(--muted);margin-top:2px}}
  .report-footer{{margin-top:3rem;padding-top:1rem;border-top:.5px solid var(--border);
    display:flex;justify-content:space-between;
    font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.06em;align-items:center}}
  .home-link{{font-family:var(--mono);font-size:10px;color:var(--accent);text-decoration:none;letter-spacing:.06em}}
  .home-link:hover{{text-decoration:underline}}
  .disclaimer{{margin-top:1rem;font-size:10px;color:var(--muted);line-height:1.6}}
  @media print{{
    body{{padding:1.5rem}}
    .verdict-banner,.metrics-grid,.amenity-grid,.return-stack,.risk-grid,.row-total,th{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  }}
</style>
</head>
<body>

<div class="report-header">
  <div>
    <div class="brand">Caribbean STR</div>
    <div style="font-family:var(--mono);font-size:10px;color:var(--muted);margin-top:4px;">Professional STR Underwriting</div>
  </div>
  <div class="report-id">
    <span>REPORT #{esc(report_num)}</span>
    <span>{report_date}</span>
    <span>PREPARED FOR: {client_name}</span>
  </div>
</div>

<div class="title-block">
  <div class="property-name">{address}</div>
  <div class="property-meta">{esc(location)} · {esc(meta_str)}</div>
</div>

<div class="verdict-banner {banner}">
  <div>
    <div class="verdict-label">ANALYST VERDICT</div>
    <div class="verdict-text {css}">{v}</div>
  </div>
  <div style="font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right;max-width:320px;line-height:1.5;">
    {esc(tagline)}
  </div>
</div>

<div class="section-title">Key metrics — base case</div>
<div class="metrics-grid">
  <div class="metric-box"><div class="metric-label">GROSS REVENUE</div><div class="metric-val">{usd(f['gross'])}</div><div class="metric-sub">{round(f['nights'])} nights · {fmt_pct(f['occ']*100)} occ.</div></div>
  <div class="metric-box"><div class="metric-label">TOTAL EXPENSES</div><div class="metric-val red">{usd(f['total_opex']+f['annual_debt'])}</div><div class="metric-sub">incl. all ops + debt service</div></div>
  <div class="metric-box"><div class="metric-label">NET CASH FLOW</div><div class="metric-val {'green' if f['cf']>=0 else 'red'}">{usd(f['cf'])}</div><div class="metric-sub">after all costs</div></div>
  <div class="metric-box"><div class="metric-label">TOTAL RETURN</div><div class="metric-val {'green' if f['total_ret_pct']>=0 else 'red'}">{fmt_pct(f['total_ret_pct']*100)}</div><div class="metric-sub">cash + equity + appreciation</div></div>
</div>
<div class="metrics-grid" style="margin-top:0">
  <div class="metric-box"><div class="metric-label">CASH-ON-CASH</div><div class="metric-val {'green' if f['coc']>=0.05 else 'amber' if f['coc']>=0 else 'red'}">{fmt_pct(f['coc']*100)}</div><div class="metric-sub">pre-tax, year 1</div></div>
  <div class="metric-box"><div class="metric-label">CAP RATE</div><div class="metric-val">{fmt_pct(f['cap_rate']*100)}</div><div class="metric-sub">NOI / purchase price</div></div>
  <div class="metric-box"><div class="metric-label">DSCR</div><div class="metric-val {'amber' if f['dscr']<1.25 else ''}">{dscr_str}</div><div class="metric-sub">NOI / debt service</div></div>
  <div class="metric-box"><div class="metric-label">PM SAVINGS</div><div class="metric-val green">{usd(f['pm_cost'])}</div><div class="metric-sub">vs. 20% managed</div></div>
</div>

<div class="section-title">Property overview</div>
<div class="detail-grid">
  <div class="detail-row"><span class="detail-label">Property Type</span><span class="detail-value">{prop_type}</span></div>
  <div class="detail-row"><span class="detail-label">Community</span><span class="detail-value">{community if community else '—'}</span></div>
  <div class="detail-row"><span class="detail-label">Bedrooms / Baths</span><span class="detail-value">{bedrooms} BR / {bathrooms} BA</span></div>
  <div class="detail-row"><span class="detail-label">Square Footage</span><span class="detail-value">{sqft_str if sqft_str else '—'}</span></div>
  <div class="detail-row"><span class="detail-label">Year Built</span><span class="detail-value">{year_built} ({datetime.now().year - int(year_built) if year_built else '—'} yrs old)</span></div>
  <div class="detail-row"><span class="detail-label">Condition</span><span class="detail-value">{condition if condition else '—'}</span></div>
  <div class="detail-row"><span class="detail-label">Access</span><span class="detail-value">{access if access else '—'}</span></div>
  <div class="detail-row"><span class="detail-label">Parking</span><span class="detail-value">{parking if parking else '—'}</span></div>
  <div class="detail-row"><span class="detail-label">Beach / Water Access</span><span class="detail-value">{beach}</span></div>
  <div class="detail-row"><span class="detail-label">Special Features</span><span class="detail-value">{features if features else '—'}</span></div>
  <div class="detail-row"><span class="detail-label">Market Type</span><span class="detail-value">{mkt_label}</span></div>
  <div class="detail-row"><span class="detail-label">HOA</span><span class="detail-value">{usd(f['hoa_annual'])}/yr {'(incl. ins.)' if data.get('hoa_includes_insurance','').startswith('Yes') else ''}</span></div>
</div>

{amenity_html}

<div class="section-title">Financing structure</div>
<div class="metrics-grid">
  <div class="metric-box"><div class="metric-label">PURCHASE PRICE</div><div class="metric-val">{usd(f['price'])}</div><div class="metric-sub">{esc(country)} acquisition</div></div>
  <div class="metric-box"><div class="metric-label">DOWN PAYMENT</div><div class="metric-val">{usd(f['down_payment'])}</div><div class="metric-sub">{fmt_pct(f['down_pct'])} — {fmt_pct(f['ltv'])} LTV</div></div>
  <div class="metric-box"><div class="metric-label">LOAN TERMS</div><div class="metric-val">{fmt_pct(f['rate'])}</div><div class="metric-sub">{f['term']}-year fixed</div></div>
  <div class="metric-box"><div class="metric-label">MONTHLY P&amp;I</div><div class="metric-val">{usd(f['monthly_pi'])}</div><div class="metric-sub">{usd(f['annual_debt'])} annual</div></div>
</div>
<table>
<thead><tr><th>Acquisition Cost</th><th>Amount</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>Down Payment</td><td>{usd(f['down_payment'])}</td><td>{fmt_pct(f['down_pct'])} of purchase price</td></tr>
<tr><td>Estimated Closing Costs</td><td>{usd(f['closing_cost'])}</td><td>{'~5% of purchase (international)' if f['is_carib'] else '~3% of purchase'}</td></tr>
<tr><td>STR Permit Fee</td><td>{usd(f['permit'])}</td><td>{'Annual registration' if f['permit']>0 else 'Not required in this market'}</td></tr>
<tr><td>Initial Supplies &amp; Setup</td><td>{usd(f['setup_cost'])}</td><td>Smart lock, supplies, professional photography</td></tr>
<tr class="row-total"><td>Total Cash to Close</td><td>{usd(f['total_cash'])}</td><td></td></tr>
</tbody></table>
<table style="margin-top:1rem">
<thead><tr><th>Amortization Detail</th><th>Value</th></tr></thead>
<tbody>
<tr><td>Year 1 Interest Paid</td><td>{usd(f['yr1_interest'])}</td></tr>
<tr><td>Year 1 Principal Paid</td><td>{usd(f['yr1_principal'])}</td></tr>
<tr><td>Total Interest Over Loan Life</td><td>{usd(f['total_interest'])}</td></tr>
<tr><td>Loan-to-Value (LTV)</td><td>{fmt_pct(f['ltv'])}</td></tr>
</tbody></table>

<div class="section-title">Scenario analysis</div>
<table>
<thead><tr><th>Scenario</th><th>Occupancy</th><th>Blended ADR</th><th>Gross Revenue</th><th>NOI</th><th>Net Cash Flow</th><th>CoC Return</th></tr></thead>
<tbody>
<tr class="scenario-upside"><td class="row-label">Upside</td><td>{fmt_pct(f['occ_up']*100)}</td><td>{usd(f['adr_up'])}</td><td>{usd(f['gross_up'])}</td><td>{usd(f['noi_up'])}</td><td>{usd(f['cf_up'])}</td><td>{fmt_pct(f['coc_up']*100)}</td></tr>
<tr><td class="row-label">Base</td><td>{fmt_pct(f['occ']*100)}</td><td>{usd(f['adr'])}</td><td>{usd(f['gross'])}</td><td>{usd(f['noi'])}</td><td>{usd(f['cf'])}</td><td>{fmt_pct(f['coc']*100)}</td></tr>
<tr class="scenario-downside"><td class="row-label">Downside</td><td>{fmt_pct(f['occ_down']*100)}</td><td>{usd(f['adr_down'])}</td><td>{usd(f['gross_down'])}</td><td>{usd(f['noi_down'])}</td><td>{usd(f['cf_down'])}</td><td>{fmt_pct(f['coc_down']*100)}</td></tr>
</tbody></table>
<div class="analysis-block" style="margin-top:.75rem"><p><strong>Base case</strong> assumes moderate dynamic pricing and seasonal optimization across Airbnb + VRBO. <strong>Upside</strong> reflects Superhost/Premier Host status and aggressive peak-season pricing. <strong>Downside</strong> models minimal optimization and a soft shoulder-season demand environment.</p></div>

<div class="section-title">Monthly revenue projection — base case</div>
<table>
<thead><tr><th>Month</th><th>Est. ADR</th><th>Occupancy</th><th>Nights</th><th>Revenue</th><th>Season</th></tr></thead>
<tbody>
{monthly_rows}
</tbody></table>
<div class="highlight-box" style="margin-top:.75rem">
  <div class="hl-label">NOTE ON GROSS VS. NET REVENUE</div>
  <div class="hl-text">The monthly totals above represent gross booking revenue. Platform fees (~{usd(f['platform_fee'])}) and cleaning costs (~{usd(f['cleaning'])}) are deducted to arrive at the {usd(f['gross'])} net revenue figure used throughout this report.</div>
</div>

<div class="section-title">Expense breakdown — annual</div>
<table>
<thead><tr><th>Expense</th><th>Annual</th><th>Monthly</th><th>% of Gross</th><th>Notes</th></tr></thead>
<tbody>
{expense_rows}
<tr class="row-total"><td>Total Operating Expenses</td><td>{usd(f['total_opex'])}</td><td>{usd(f['total_opex']/12)}</td><td>{fmt_pct(opex_pct)}</td><td></td></tr>
<tr><td>Debt service (P&amp;I)</td><td>{usd(f['annual_debt'])}</td><td>{usd(f['monthly_pi'])}</td><td>{fmt_pct(debt_pct)}</td><td>{usd(f['loan'])} @ {fmt_pct(f['rate'])} / {f['term']}-year fixed</td></tr>
<tr class="row-total"><td><strong>Total All-In Cost</strong></td><td><strong>{usd(f['total_opex']+f['annual_debt'])}</strong></td><td><strong>{usd((f['total_opex']+f['annual_debt'])/12)}</strong></td><td><strong>{fmt_pct(allin_pct)}</strong></td><td></td></tr>
</tbody></table>

<div class="section-title">Total return on investment — year 1</div>
<div class="return-stack">
  <div class="return-item"><div class="return-label">CASH FLOW</div><div class="return-val {'green' if f['cf']>=0 else 'red'}">{usd(f['cf'])}</div><div class="return-sub">{fmt_pct(f['cf']/f['down_payment']*100 if f['down_payment'] else 0)} of equity</div></div>
  <div class="return-item"><div class="return-label">PRINCIPAL PAYDOWN</div><div class="return-val">{usd(f['yr1_principal'])}</div><div class="return-sub">{fmt_pct(f['yr1_principal']/f['down_payment']*100 if f['down_payment'] else 0)} of equity</div></div>
  <div class="return-item"><div class="return-label">APPRECIATION ({fmt_pct(f['appr_rate']*100)})</div><div class="return-val green">{usd(f['appr_val'])}</div><div class="return-sub">{fmt_pct(f['appr_val']/f['down_payment']*100 if f['down_payment'] else 0)} of equity</div></div>
  <div class="return-item"><div class="return-label">TAX BENEFITS</div><div class="return-val">{usd(f['tax_benefit'])}</div><div class="return-sub">{fmt_pct(f['tax_benefit']/f['down_payment']*100 if f['down_payment'] else 0)} of equity</div></div>
</div>
<table>
<thead><tr><th>Return Component</th><th>Annual Value</th><th>% of {usd(f['down_payment'])} Equity</th></tr></thead>
<tbody>
<tr><td>Pre-Tax Cash Flow</td><td>{usd(f['cf'])}</td><td>{fmt_pct(f['cf']/f['down_payment']*100 if f['down_payment'] else 0)}</td></tr>
<tr><td>Mortgage Principal Paydown</td><td>{usd(f['yr1_principal'])}</td><td>{fmt_pct(f['yr1_principal']/f['down_payment']*100 if f['down_payment'] else 0)}</td></tr>
<tr><td>Estimated Appreciation ({fmt_pct(f['appr_rate']*100)}/yr)</td><td>{usd(f['appr_val'])}</td><td>{fmt_pct(f['appr_val']/f['down_payment']*100 if f['down_payment'] else 0)}</td></tr>
<tr><td>Tax Benefits (depreciation shield)</td><td>{usd(f['tax_benefit'])}</td><td>{fmt_pct(f['tax_benefit']/f['down_payment']*100 if f['down_payment'] else 0)}</td></tr>
<tr class="row-total"><td><strong>Total Return on Equity</strong></td><td><strong>{usd(f['total_ret'])}</strong></td><td><strong>{fmt_pct(f['total_ret_pct']*100)}</strong></td></tr>
</tbody></table>
<div class="analysis-block" style="margin-top:1rem"><p>While Year 1 cash-on-cash is {fmt_pct(f['coc']*100)}, the total return profile is {fmt_pct(f['total_ret_pct']*100)} when accounting for equity building via principal paydown, market appreciation, and a depreciation tax shield ({usd(f['bldg_val'])} building value / 27.5 years = ~{usd(f['depreciation'])}/yr deduction at a 24% bracket). The {fmt_pct(f['down_pct'])}% down payment de-risks the investment by providing a meaningful equity cushion from day one.</p></div>

<div class="section-title">Market analysis — {esc(mkt_analysis_label)}</div>
<div class="analysis-block"><h3>Deal verdict</h3><p>{esc(deal_v)}</p></div>
<div class="analysis-block"><h3>Revenue assumptions</h3><p>{esc(rev_v)}</p></div>
<div class="analysis-block"><h3>Market dynamics</h3><p>{esc(mkt_d)}</p></div>

<div class="section-title">Self-management strategy</div>
<div class="analysis-block"><h3>Platform approach</h3><p>Dual-list on Airbnb (3% host fee) and VRBO (8% host fee). {'Consider Booking.com for European travelers, a significant segment of Caribbean visitors.' if f['is_carib'] else 'Airbnb dominates domestic leisure; VRBO captures longer-stay family groups. Both platforms are necessary to reach 60%+ occupancy.'} Self-management saves {usd(f['pm_cost'])}/yr versus a 20% property manager — a savings that substantially improves cash-on-cash return.</p></div>
<div class="analysis-block"><h3>Operational requirements</h3><p>{'Local cleaning team (' + usd(f["clean_per"]) + '/turn), smart lock, WhatsApp-based guest communication for international travelers, airport transfer coordination, professional photography, bilingual listings.' if f['is_carib'] else 'Local cleaning team (' + usd(f["clean_per"]) + '/turn recommended), smart lock, noise monitoring device (Minut or NoiseAware), dynamic pricing tool (PriceLabs or Wheelhouse), professional photography, and guest automation software (Hospitable or Hostfully).'}</p></div>
<div class="analysis-block"><h3>Revenue optimization tactics</h3><p>Dynamic pricing with weekly updates, {'3-night minimums during peak winter season, bilingual listings (English/Spanish), curated local experience guides, and Superhost targeting via rapid response rate.' if f['is_carib'] else '3-night minimums during peak summer weekends, 7-night minimums during holiday weeks, seasonal pricing uplift of 40–60% in June–August, and Superhost targeting via response rate and review management.'}</p></div>

<div class="section-title">Risk assessment</div>
<div class="risk-grid">
{risk_html}
</div>

<div class="section-title">Tax &amp; legal flags</div>
<div class="analysis-block"><p>{tax_txt}</p></div>

<div class="section-title">Regulatory environment</div>
<div class="detail-grid">
{reg_html}
</div>
<table style="margin-top:1rem">
<thead><tr><th>Requirement</th><th>Action Needed</th></tr></thead>
<tbody>
{checklist_html}
</tbody></table>

<div class="section-title">5-year pro forma projection</div>
<table>
<thead><tr><th>Metric</th><th>Year 1</th><th>Year 2</th><th>Year 3</th><th>Year 4</th><th>Year 5</th></tr></thead>
<tbody>
{proforma_rows}
</tbody></table>

<div class="section-title">Recommended next steps</div>
<ul class="steps-list">
{steps_html}
</ul>

<div class="report-footer">
  <span>CONFIDENTIAL — Caribbean STR · caribbeanstr.com</span>
  <a href="https://caribbeanstr.com/" class="home-link">← Analyze Another Property</a>
</div>
<div class="disclaimer">This report is for informational purposes only and does not constitute financial, legal, or investment advice. All projections are estimates based on market data and stated assumptions — actual results will vary. Engage a licensed CPA and real estate attorney before any purchase. Revenue figures are pre-tax estimates; consult a tax professional regarding your specific situation.</div>
</body>
</html>"""
    return html
