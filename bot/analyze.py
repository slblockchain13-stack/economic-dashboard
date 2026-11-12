"""The analysis 'agent': fixed, transparent rules over the fetched data.

Nothing here is a black box: every label the dashboard shows comes from one of
the functions below, and the Method tab explains the same rules in words.
Series are dicts {year(int): value}. Pure functions, unit-tested in tests/.
"""
import statistics

PHASES = {
    "early": "Early expansion", "mid": "Mid expansion", "late": "Late expansion",
    "tight": "Tightening", "slow": "Slowdown", "rec": "Recession",
}
CLI_PHASES = {"expansion": "Expansion", "downturn": "Downturn", "slowdown": "Slowdown", "recovery": "Recovery"}
# Dalio's long-term debt cycle, in order along the curve. Index 0 is unused so that stage numbers read 1-5.
LT_STAGES = [None, "Early: debt affordable", "Bubble building", "Top: policy limits", "Deleveraging", "Normalisation"]
LEVERS = ["Cut spending", "Restructure or default", "Redistribute wealth", "Print money"]
LEVER_LEVELS = ["Not in use", "Light", "Moderate", "Heavy"]

# before these years the central bank had no explicit target: use the 10-year median instead
TARGET_FROM = {"IN": 2016, "LK": 2020}


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def r1(x, n=1):
    return None if x is None else round(x, n)


# ---------- short-term business cycle ----------
def trend(gdp, y):
    v = [gdp[t] for t in range(y - 10, y) if t in gdp]
    return sum(v) / len(v) if len(v) >= 5 else None


def bench(key, target, cpi, y):
    if key == "CN" and y < 2025:
        target = 3.0
    if y < TARGET_FROM.get(key, 0) or target is None:
        v = [cpi[t] for t in range(y - 10, y) if t in cpi]
        return statistics.median(v) if len(v) >= 5 else None
    return target


def phase(gdp, gdp_prev, trend_v, cpi, target, rate_chg, unemp_chg=None):
    """Classify one year. Returns a key of PHASES or None when inputs are missing."""
    if gdp is None or trend_v is None or cpi is None or target is None:
        return None
    gap, infl_gap = gdp - trend_v, cpi - target
    if gdp < 0.5 or gap < -3.5 or (unemp_chg is not None and unemp_chg > 0.8):
        return "rec"
    if rate_chg is not None and rate_chg > 0.25 and infl_gap > 0.5:
        return "tight"
    if gap > 0 and infl_gap > 0.5:
        return "late"
    if gap <= 0 and (rate_chg is None or rate_chg < -0.1):
        return "slow"
    if gap > 0 and infl_gap <= 0.5 and gdp_prev is not None and gdp > gdp_prev:
        return "early"
    return "mid"


def bench_kind(key, target, y):
    return "10-year norm" if (y < TARGET_FROM.get(key, 0) or target is None) else "target"


def phase_details(key, s, target, first, last):
    """{year: {phase and the inputs behind it}} for actual years, using year-end policy-rate changes."""
    out = {}
    gdp, cpi, rate, un = s.get("gdp", {}), s.get("cpi", {}), s.get("rate", {}), s.get("unemp", {})
    for y in range(first, last + 1):
        rc = rate[y] - rate[y - 1] if y in rate and y - 1 in rate else None
        uc = un[y] - un[y - 1] if y in un and y - 1 in un else None
        tr, b = trend(gdp, y), bench(key, target, cpi, y)
        p = phase(gdp.get(y), gdp.get(y - 1), tr, cpi.get(y), b, rc, uc)
        if p:
            out[y] = {"phase": p, "gdp": r1(gdp.get(y), 2), "trend": r1(tr, 2), "cpi": r1(cpi.get(y), 2), "target": r1(b, 2),
                      "kind": bench_kind(key, target, y), "rate_chg": r1(rc, 2), "unemp_chg": r1(uc, 2)}
    return out


def phase_history(key, s, target, first, last):
    """{year: phase} for actual years."""
    return {y: d["phase"] for y, d in phase_details(key, s, target, first, last).items()}


def phase_now(key, s, target, year, latest_rate):
    """Current year: IMF projections for growth and inflation, latest policy rate vs last year end."""
    gdp, cpi, rate = s.get("gdp", {}), s.get("cpi", {}), s.get("rate", {})
    rc = latest_rate - rate[year - 1] if latest_rate is not None and year - 1 in rate else None
    tr = trend(gdp, year)
    b = bench(key, target, cpi, year)
    p = phase(gdp.get(year), gdp.get(year - 1), tr, cpi.get(year), b, rc)
    return p, {"gdp": r1(gdp.get(year), 2), "gdp_prev": r1(gdp.get(year - 1), 2), "trend": r1(tr, 2), "cpi": r1(cpi.get(year), 2),
               "target": b, "kind": bench_kind(key, target, year), "rate_chg": r1(rc, 2)}


def cli_phase(cli_monthly):
    """OECD business-cycle clock from the composite leading indicator. Uses the 3-month change."""
    if not cli_monthly or len(cli_monthly) < 4:
        return None
    ks = sorted(cli_monthly)
    lvl, chg = cli_monthly[ks[-1]], cli_monthly[ks[-1]] - cli_monthly[ks[-4]]
    if lvl >= 100:
        ph = "expansion" if chg > 0 else "downturn"
    else:
        ph = "recovery" if chg > 0 else "slowdown"
    return {"phase": ph, "level": round(lvl, 2), "chg3m": round(chg, 2), "month": ks[-1]}


# ---------- long-term debt cycle ----------
def lt_score(gov, private, gov_10y_ago, private_10y_ago, min_rate_since_2008, y10, nominal_growth,
             emerging=False, default_year=None, year=None, y10_label="10-year yield"):
    """0 = early in the long-term debt cycle, 1 = very late. Missing parts are left out and weights renormalised.
    Emerging economies hit debt limits sooner (IMF rule of thumb: ~60-70% government debt vs ~90%+ for advanced)."""
    parts = []
    if gov is not None:
        sc = clamp((gov - 40) / 50) if emerging else clamp((gov - 60) / 80)
        parts.append((0.25, sc, f"Government debt {gov:.0f}% of GDP ({'emerging' if emerging else 'advanced'}-economy yardstick)"))
    if default_year and year and year - default_year <= 10:
        parts.append((0.5, 1.0, f"Debt crisis in {default_year}, within the last 10 years"))
    if gov is not None and private is not None:
        total = gov + private
        parts.append((0.4, clamp((total - 120) / 210), f"Total non-financial debt {total:.0f}% of GDP"))
        if gov_10y_ago is not None and private_10y_ago is not None:
            chg = total - gov_10y_ago - private_10y_ago
            parts.append((0.2, clamp(chg / 60), f"Debt {'up' if chg >= 0 else 'down'} {abs(chg):.0f} pts of GDP in 10 years"))
    if gov is None and private is not None:
        parts.append((0.4, clamp((private - 100) / 170), f"Private debt {private:.0f}% of GDP"))
        if private_10y_ago is not None:
            chg = private - private_10y_ago
            parts.append((0.2, clamp(chg / 60), f"Private debt {'up' if chg >= 0 else 'down'} {abs(chg):.0f} pts of GDP in 10 years"))
    if min_rate_since_2008 is not None:
        hit = min_rate_since_2008 <= 0.5
        parts.append((0.2, 1.0 if hit else 0.0, "Policy rate has hit the zero bound since 2008" if hit else "Policy rate has not needed the zero bound"))
    if y10 is not None and nominal_growth is not None:
        rg = y10 - nominal_growth
        parts.append((0.2, clamp((rg + 2) / 4), f"{y10_label} {'above' if rg > 0 else 'below'} nominal growth by {abs(rg):.1f} pts"))
    if not parts:
        return None, None, []
    w = sum(p[0] for p in parts)
    score = sum(p[0] * p[1] for p in parts) / w
    stage = 0 if score < 0.3 else 1 if score < 0.5 else 2 if score < 0.7 else 3
    return round(score, 3), stage, [p[2] for p in parts]


def crisis_year(gdp, cpi, year, known=None, window=12):
    """Latest year in the window that looks like an inflationary debt crisis in the data
    (output down 5% or more with inflation of 20% or more), or a known sovereign default."""
    ys = [y for y in range(year - window, year)
          if gdp.get(y) is not None and cpi.get(y) is not None and gdp[y] <= -5 and cpi[y] >= 20]
    if known and 0 <= year - known <= window:
        ys.append(known)
    return max(ys) if ys else None


def lt_cycle(m):
    """Place an economy on Dalio's five-stage long-term debt cycle from data alone.
    m: score (debt pressure 0-1), private, hh, dsr, total_chg_10y, private_chg_5y, min_rate, cpi_avg2, cpi_now,
       target, crisis, year, gdp_last2, gov, gov_peak.
    Returns {"stage": 1-5, "pos": 0-1 along the curve, "rule": why this stage} or None."""
    score = m.get("score")
    if score is None:
        return None
    crisis, gov, peak = m.get("crisis"), m.get("gov"), m.get("gov_peak")
    fall = peak - gov if gov is not None and peak is not None else None
    if crisis:
        g2 = m.get("gdp_last2") or []
        growing = len(g2) == 2 and all(g is not None and g > 1 for g in g2)
        calm = m.get("cpi_now") is not None and m.get("target") is not None and m["cpi_now"] <= m["target"] + 3
        if growing and calm and fall is not None and fall >= 10:
            return {"stage": 5, "pos": round(0.92 + 0.05 * clamp((m["year"] - crisis) / 10), 3),
                    "rule": f"Debt crisis in {crisis}; since then growth has returned for two years, inflation is back near target "
                            f"and government debt is {fall:.0f} pts of GDP below its peak"}
        return {"stage": 4, "pos": round(0.77 + 0.11 * clamp((fall or 0) / 20), 3),
                "rule": f"Debt crisis in {crisis}: debt is still being worked down"
                        + (f" ({fall:.0f} pts of GDP below its peak so far)" if fall and fall > 0 else "")}
    heavy = (m.get("private") is not None and m["private"] >= 150) or (m.get("dsr") is not None and m["dsr"] >= 18) or score >= 0.55
    if heavy and m.get("cpi_avg2") is not None and m["cpi_avg2"] < 1.0:
        return {"stage": 4, "pos": 0.78,
                "rule": f"Heavy debt while inflation averages only {m['cpi_avg2']:.1f}%: prices are too weak to shrink the debt, "
                        "the mark of a deflationary deleveraging"}
    zero = m.get("min_rate") is not None and m["min_rate"] <= 0.5
    c10, c5 = m.get("total_chg_10y"), m.get("private_chg_5y")
    rising = (c10 is not None and c10 >= 15) or (c5 is not None and c5 >= 8)
    strain = (m.get("hh") is not None and m["hh"] >= 90) or (m.get("dsr") is not None and m["dsr"] >= 18)
    why_build = ("debt has grown faster than income" if rising else "household debt or debt service is high") if (rising or strain) else ""
    if score >= 0.5 and zero:
        stage, rule = 3, "Debt pressure is high and interest rates have already been cut to zero once: little room left to ease"
    elif score >= 0.5:
        stage, rule = 2, "Debt pressure is high, but interest rates have never needed the zero bound, so policy still has room"
    elif rising or strain:
        stage, rule = 2, f"Debt pressure is moderate and {why_build}"
    elif score >= 0.35 and zero:
        stage, rule = 3, "Debt is no longer growing faster than income, but rates have already hit zero and the burden is still sizeable"
    else:
        stage, rule = 1, "Debt is modest relative to income and is not growing faster than it"
    pos = {1: 0.04 + 0.24 * clamp(score / 0.35), 2: 0.32 + 0.21 * clamp((score - 0.3) / 0.3), 3: 0.57 + 0.16 * clamp((score - 0.4) / 0.5)}[stage]
    return {"stage": stage, "pos": round(pos, 3), "rule": rule}


def lt_evidence(s, last, crisis, events, asset_backed=False):
    """Dated facts behind the long-term call, read from the series. Returns [[year, text], ...] oldest first."""
    out = []
    rate, gov, credit, gdp, cpi, dsr = (s.get(n, {}) for n in ("rate", "gov", "credit", "gdp", "cpi", "dsr"))
    prev_zero = False
    for y in sorted(y for y in rate if y >= 2008):
        z = rate[y] <= 0.5
        if z and not prev_zero:
            first = not any(e[1].startswith("Policy rate") for e in out)
            out.append([y, f"Policy rate cut to {rate[y]:.2f}%: the zero bound" if first else f"Policy rate back to {rate[y]:.2f}%"])
        prev_zero = z
    if crisis and gdp.get(crisis) is not None and cpi.get(crisis) is not None:
        out.append([crisis, f"Debt crisis: output fell {abs(gdp[crisis]):.1f}% and inflation reached {cpi[crisis]:.0f}%"])
    gy = max((y for y in gov if y <= last), default=None)
    if gy:
        base = 2007 if 2007 in gov else min((y for y in gov if y >= 2000), default=None)
        if base and base < gy:
            d = gov[gy] - gov[base]
            out.append([gy, f"Government debt {gov[gy]:.0f}% of GDP, {'up' if d >= 0 else 'down'} from {gov[base]:.0f}% in {base}"
                        + (" (issued to invest and backed by larger assets)" if asset_backed else "")])
    tot = {y: gov[y] + credit[y] for y in credit if y in gov and y >= 2000}
    if tot and not asset_backed:
        pk, cy = max(tot, key=tot.get), max(tot)
        if pk == cy:
            out.append([cy, f"Total debt at a record {tot[cy]:.0f}% of GDP"])
        elif tot[pk] - tot[cy] >= 5:
            out.append([pk, f"Total debt peaked at {tot[pk]:.0f}% of GDP; now {tot[cy]:.0f}%"])
    if dsr:
        dy = max(dsr)
        if dsr[dy] >= 18:
            out.append([dy, f"Private debt service takes {dsr[dy]:.1f}% of income"])
    out += [[e[0], e[1]] for e in events or []]
    return sorted(out, key=lambda e: e[0])


def levers(m):
    """Dalio's four deleveraging levers, each rated 0-3 from data. None = cannot be measured.
    m: pb, pb_3y (primary balance % GDP now and three years ago), bal_label, crisis, year, private_chg_5y,
       rev, rev_5y (government revenue % GDP), real_rate, nominal, rate, rate_label."""
    out = []
    pb, pb3 = m.get("pb"), m.get("pb_3y")
    lab = m.get("bal_label", "Primary budget balance")
    if pb is None:
        out.append([None, "No budget data"])
    else:
        tight = pb - pb3 if pb3 is not None else 0
        lvl = 3 if pb >= 1.5 else 2 if (pb >= 0 or tight >= 2) else 1 if tight >= 0.75 else 0
        out.append([lvl, f"{lab} {pb:+.1f}% of GDP" + (f", from {pb3:+.1f}% three years earlier" if pb3 is not None else "")])
    crisis, c5 = m.get("crisis"), m.get("private_chg_5y")
    if crisis:
        out.append([3 if m["year"] - crisis <= 5 else 2, f"Debt crisis in {crisis}: debts restructured or written down"])
    elif c5 is not None and c5 <= -15:
        out.append([1, f"No default. Private debt has shrunk {abs(c5):.0f} pts of GDP in 5 years (repayment, write-offs and income growth)"])
    else:
        out.append([0, "No default or broad restructuring in the data"])
    rev, rev5 = m.get("rev"), m.get("rev_5y")
    if rev is None or rev5 is None:
        out.append([None, "No government revenue data"])
    else:
        d = rev - rev5
        lvl = 3 if d >= 3 else 2 if d >= 1.5 else 1 if d >= 0.5 else 0
        out.append([lvl, f"Government revenue {rev:.1f}% of GDP, {'up' if d >= 0 else 'down'} {abs(d):.1f} pts in 5 years (a proxy for taxing more)"])
    real = m.get("real_rate")
    if real is None:
        out.append([None, "No policy interest rate to measure"])
    else:
        lvl = 3 if real <= -2 else 2 if real <= -0.5 else 1 if real < 0.5 else 0
        out.append([lvl, f"Policy rate {'below' if real < 0 else 'above'} inflation by {abs(real):.1f} pts"
                    + (": savers lose, debtors gain" if real < 0 else "")])
    res = [{"name": LEVERS[i], "level": o[0], "label": LEVER_LEVELS[o[0]] if o[0] is not None else "Not measured", "note": o[1]} for i, o in enumerate(out)]
    g, r = m.get("nominal"), m.get("rate")
    verdict = None
    if g is not None and r is not None:
        verdict = (f"Nominal growth ({g:.1f}%) is {'above' if g > r else 'below'} the {m.get('rate_label', 'interest rate')} ({r:.1f}%): "
                   + ("debt is shrinking relative to income, Dalio's condition for a beautiful deleveraging."
                      if g > r else "debt is growing relative to income unless it is paid down or written off."))
    return {"levers": res, "verdict": verdict}


def rules_of_thumb(credit, prod, last, prod_label="output per worker"):
    """Dalio's three rules. credit: private credit % GDP by year; prod: output per worker growth % by year."""
    def chg(n):
        if not credit:
            return None
        y = max(credit)
        return {"year": y, "d": round(credit[y] - credit[y - n], 1)} if y - n in credit else None

    def avg(a, b):
        v = [prod[y] for y in range(a, b + 1) if y in prod] if prod else []
        return round(sum(v) / len(v), 2) if v else None
    c1, c5 = chg(1), chg(5)
    stale = bool(credit) and max(credit) < last - 2
    p5, p15 = avg(last - 4, last), avg(last - 19, last - 5)
    r = [{"q": "Debt growing no faster than income?", "unit": "pt",
          "st": "na" if c1 is None or stale else "ok" if c1["d"] <= 0 else "no",
          "bars": [["Last year", c1 and c1["d"]], ["Last 5 years", c5 and c5["d"]]] if c1 else [],
          "msg": "No recent private credit data" if c1 is None or stale else
                 (f"Yes: private credit fell {abs(c1['d']):.1f} pts of GDP in {c1['year']}" if c1["d"] <= 0
                  else f"No: private credit rose {c1['d']:.1f} pts of GDP in {c1['year']}")},
         {"q": "Incomes growing no faster than productivity?", "unit": "%", "st": "na", "bars": [],
          "msg": "Not measured: no free source carries comparable real wage data for every economy"},
         {"q": "Productivity holding up?", "unit": "%",
          "st": "na" if p5 is None or p15 is None else "ok" if p5 >= p15 else "no",
          "bars": [[f"{last - 4}–{last}", p5], [f"{last - 19}–{last - 5}", p15]],
          "msg": "No data" if p5 is None or p15 is None else
                 (f"Yes: {prod_label} is growing at least as fast as before" if p5 >= p15
                  else f"Slowing: {prod_label} is growing more slowly than before")}]
    return r


# ---------- investment screen ----------
def stance(x):
    return "Favourable" if x >= 1.25 else "Cautious" if x <= -0.75 else "Neutral"


def screen(m):
    """m: flat dict of the latest metrics for one economy. Returns scores, stances, reasons, risks."""
    eq, bd, fx = 0.0, 0.0, 0.0
    why = {"equities": [], "bonds": [], "currency": []}
    ph, cli = m.get("phase"), m.get("cli_phase")
    ph_pts = {"early": 2, "mid": 1, "slow": 0.5, "late": 0, "tight": -1, "rec": -1.5}
    if ph in ph_pts:
        eq += ph_pts[ph]
        why["equities"].append((ph_pts[ph], f"{PHASES[ph]} phase"))
    cli_pts = {"recovery": 1.5, "expansion": 0.5, "downturn": -1, "slowdown": -0.5}
    if cli in cli_pts:
        eq += cli_pts[cli]
        why["equities"].append((cli_pts[cli], f"Leading indicator in {cli}"))
    rc12 = m.get("rate_chg_12m")
    if rc12 is not None:
        if rc12 < -0.25:
            eq += 0.5; why["equities"].append((0.5, f"Central bank cut {abs(rc12):.2f} pts in 12 months"))
        elif rc12 > 0.25:
            eq -= 0.5; why["equities"].append((-0.5, f"Central bank raised {rc12:.2f} pts in 12 months"))
    r12, above200, dd = m.get("eq_ret_12m"), m.get("eq_above_200d"), m.get("eq_drawdown")
    if r12 is not None and above200 is not None:
        if r12 > 0 and above200:
            eq += 0.5; why["equities"].append((0.5, f"Index up {r12:.0f}% in a year and above its 200-day average"))
        elif not above200:
            eq -= 0.5; why["equities"].append((-0.5, "Index below its 200-day average"))
    if dd is not None and dd <= -15 and (cli in ("recovery", "expansion") or ph == "early"):
        eq += 0.5; why["equities"].append((0.5, f"{abs(dd):.0f}% below its 1-year high while the cycle is turning up"))
    tone = m.get("news_tone")
    if tone is not None and abs(tone) >= 0.2:
        eq += 0.5 * tone; why["equities"].append((round(0.5 * tone, 2), f"News tone {'positive' if tone > 0 else 'negative'} this week"))

    real = m.get("real_rate")
    cpi, cpi_prev, tgt = m.get("cpi"), m.get("cpi_prev"), m.get("target")
    if real is not None:
        if real > 1.5:
            bd += 1; why["bonds"].append((1, f"Real policy rate high ({real:.1f}%)"))
        elif real < 0:
            bd -= 1; why["bonds"].append((-1, f"Real policy rate negative ({real:.1f}%)"))
    if cpi is not None and cpi_prev is not None:
        if cpi < cpi_prev - 0.2:
            bd += 0.5; why["bonds"].append((0.5, "Inflation falling"))
        elif tgt is not None and cpi > tgt + 1 and cpi > cpi_prev:
            bd -= 1; why["bonds"].append((-1, "Inflation above target and rising"))
    if ph in ("slow", "rec"):
        bd += 1; why["bonds"].append((1, "Slowing economy usually brings rate cuts"))
    elif ph in ("late", "tight"):
        bd -= 0.5; why["bonds"].append((-0.5, "Late cycle: rates may stay high"))
    y10 = m.get("y10")
    if y10 is not None and cpi is not None and y10 - cpi > 2:
        bd += 0.5; why["bonds"].append((0.5, f"10-year yield {y10 - cpi:.1f} pts above inflation"))
    gov = None if m.get("asset_backed") else m.get("gov_debt")  # debt matched by larger assets is not a risk signal
    if gov is not None and gov > 100 and m.get("r_minus_g") is not None and m["r_minus_g"] > 0:
        bd -= 0.5; why["bonds"].append((-0.5, "Debt above 100% of GDP with yields above growth"))

    ca, res, fxchg = m.get("ca"), m.get("reserves_months"), m.get("fx_chg_12m")
    if ca is not None:
        if ca > 2:
            fx += 1; why["currency"].append((1, f"Current account surplus {ca:.1f}% of GDP"))
        elif ca < -4:
            fx -= 1; why["currency"].append((-1, f"Current account deficit {abs(ca):.1f}% of GDP"))
    if res is not None:
        if res > 6:
            fx += 0.5; why["currency"].append((0.5, f"Reserves cover {res:.0f} months of imports"))
        elif res < 3:
            fx -= 1; why["currency"].append((-1, f"Reserves cover only {res:.1f} months of imports"))
    if real is not None:
        if real > 2:
            fx += 0.5; why["currency"].append((0.5, "High real interest rate supports the currency"))
        elif real < 0:
            fx -= 0.5; why["currency"].append((-0.5, "Negative real rate weighs on the currency"))
    if fxchg is not None:
        if fxchg > 5:
            fx += 0.5; why["currency"].append((0.5, f"Up {fxchg:.0f}% vs USD in 12 months"))
        elif fxchg < -5:
            fx -= 0.5; why["currency"].append((-0.5, f"Down {abs(fxchg):.0f}% vs USD in 12 months"))

    risks = []
    if cpi is not None and tgt is not None and cpi > tgt + 3:
        risks.append(f"Inflation {cpi:.1f}% is far above the {tgt:g}% target")
    if ca is not None and ca < -4:
        risks.append(f"Large current-account deficit ({ca:.1f}% of GDP)")
    if res is not None and res < 3:
        risks.append(f"Thin FX reserves ({res:.1f} months of imports)")
    if m.get("dsr") is not None and m["dsr"] > 18:
        risks.append(f"Private debt service ratio high ({m['dsr']:.1f}% of income)")
    if gov is not None and gov > 100:
        risks.append(f"Government debt {gov:.0f}% of GDP")
    if ph == "rec":
        risks.append("Economy in recession by the cycle rules")
    if cli == "slowdown":
        risks.append("Leading indicator below 100 and falling")
    if tone is not None and tone <= -0.3:
        risks.append("News flow clearly negative this week")

    def top(lst):
        return [t for _, t in sorted(lst, key=lambda x: -abs(x[0]))]

    overall = 0.5 * eq + 0.25 * bd + 0.25 * fx
    return {
        "equities": {"score": round(eq, 2), "stance": stance(eq), "why": top(why["equities"])},
        "bonds": {"score": round(bd, 2), "stance": stance(bd), "why": top(why["bonds"])},
        "currency": {"score": round(fx, 2), "stance": stance(fx), "why": top(why["currency"])},
        "overall": round(overall, 2),
        "score100": int(round(clamp((overall + 2.5) / 5) * 100)),
        "risks": risks,
    }


# ---------- plain-English summary ----------
def fmt(x, n=1, suffix="%"):
    return "n/a" if x is None else f"{x:.{n}f}{suffix}"


def summary(c, now, year):
    ph = now.get("phase")
    x = now.get("inputs", {})
    parts = []
    if ph:
        parts.append(f"{c['name']} reads as **{PHASES[ph].lower()}** by the cycle rules: {year} growth of {fmt(x.get('gdp'))} (IMF) "
                     f"against a 10-year trend of {fmt(x.get('trend'))}, with inflation at {fmt(x.get('cpi'))} against a "
                     f"{fmt(x.get('target'), 1)} benchmark.")
    rate, rc = now.get("rate"), x.get("rate_chg")
    if rate is not None:
        move = "has left rates unchanged" if rc is None or abs(rc) < 0.05 else (f"has cut by {abs(rc):.2f} pts" if rc < 0 else f"has raised by {rc:.2f} pts")
        parts.append(f"The {c['cb']} {move} since the end of {year - 1}; the policy rate is {rate:.2f}%.")
    elif c["key"] == "SG":
        parts.append("Singapore steers its exchange rate instead of an interest rate, so rate rules are skipped.")
    cli = now.get("cli")
    if cli:
        parts.append(f"The OECD leading indicator is {cli['level']:.2f} ({CLI_PHASES[cli['phase']].lower()}, {cli['chg3m']:+.2f} over 3 months to {cli['month']}).")
    lt = now.get("lt")
    if lt:
        parts.append(f"Long-term debt cycle: **{LT_STAGES[lt['stage']].lower()}**. {lt['rule']}.")
    eq = now.get("equity")
    if eq and eq.get("ret_12m") is not None:
        parts.append(f"The {c['index_name']} is {eq['ret_12m']:+.1f}% over 12 months.")
    t = now.get("news_tone")
    if t and t.get("n"):
        lean = "positive" if t["score"] >= 0.2 else "negative" if t["score"] <= -0.2 else "mixed"
        parts.append(f"This week's headlines lean {lean} ({t['pos']} positive, {t['neg']} negative of {t['n']}).")
    return " ".join(parts)


# ---------- change detection ----------
def diff(prev, new, ts):
    """Compare two data snapshots and describe what changed, for the live activity feed."""
    if not prev:
        return []
    out = []
    pe, ne = prev.get("economies", {}), new.get("economies", {})
    for k, n in ne.items():
        p = pe.get(k)
        if not p:
            continue
        name = n["name"]
        pn, nn = p.get("now", {}), n.get("now", {})
        if pn.get("phase") != nn.get("phase") and nn.get("phase"):
            out.append({"ts": ts, "key": k, "kind": "cycle", "text": f"{name}: cycle phase moved from {PHASES.get(pn.get('phase'), 'n/a')} to {PHASES[nn['phase']]}"})
        pc, nc = (pn.get("cli") or {}), (nn.get("cli") or {})
        if nc and pc.get("month") != nc.get("month"):
            out.append({"ts": ts, "key": k, "kind": "cli", "text": f"{name}: OECD leading indicator for {nc['month']} published at {nc['level']:.2f} ({CLI_PHASES[nc['phase']]})"})
        elif nc and pc.get("phase") and pc.get("phase") != nc.get("phase"):
            out.append({"ts": ts, "key": k, "kind": "cli", "text": f"{name}: leading indicator turned from {CLI_PHASES[pc['phase']]} to {CLI_PHASES[nc['phase']]}"})
        if pn.get("rate") is not None and nn.get("rate") is not None and abs(pn["rate"] - nn["rate"]) >= 0.05:
            d = nn["rate"] - pn["rate"]
            out.append({"ts": ts, "key": k, "kind": "rates", "text": f"{name}: {n['cb']} {'cut' if d < 0 else 'raised'} its policy rate to {nn['rate']:.2f}% ({d:+.2f})"})
        pl, nl = (pn.get("lt") or {}).get("stage"), (nn.get("lt") or {}).get("stage")
        if pl and nl and pl != nl:
            out.append({"ts": ts, "key": k, "kind": "debt", "text": f"{name}: long-term debt cycle moved from {LT_STAGES[pl]} to {LT_STAGES[nl]}"})
        ps, ns = (p.get("screen") or {}).get("equities", {}).get("stance"), (n.get("screen") or {}).get("equities", {}).get("stance")
        if ps and ns and ps != ns:
            out.append({"ts": ts, "key": k, "kind": "screen", "text": f"{name}: equity screen changed from {ps} to {ns}"})
        pq, nq = (pn.get("equity") or {}), (nn.get("equity") or {})
        if nq.get("date") and nq.get("date") != pq.get("date") and nq.get("day_chg") is not None and abs(nq["day_chg"]) >= 2:
            out.append({"ts": ts, "key": k, "kind": "markets", "text": f"{name}: {n['index_name']} {'jumped' if nq['day_chg'] > 0 else 'fell'} {abs(nq['day_chg']):.1f}% on {nq['date']}"})
    pm = {m["symbol"]: m for m in prev.get("markets", [])}
    for m in new.get("markets", []):
        o = pm.get(m["symbol"])
        if not o or m.get("date") == o.get("date") or m.get("day_chg") is None:
            continue
        lim = 10 if m["symbol"] == "^VIX" else 2.5
        if abs(m["day_chg"]) >= lim:
            out.append({"ts": ts, "key": "WORLD", "kind": "markets", "text": f"{m['label']} {'up' if m['day_chg'] > 0 else 'down'} {abs(m['day_chg']):.1f}% on {m['date']}"})
    return out
