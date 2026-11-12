"""Update bot. Run by GitHub Actions every hour; also runs locally:

    python3 bot/update.py                 # fast refresh (markets, FX, news); macro if older than 20h
    python3 bot/update.py --full          # force a full macro refresh too
    python3 bot/update.py --prev URL      # use the published data.json as the previous state

Writes docs/data/data.json. If the result fails validation the file is NOT
overwritten, so the live site keeps showing the last good data.
"""
import argparse
import json
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import analyze as A  # noqa: E402
import news as N  # noqa: E402
import official as O  # noqa: E402
import sources as S  # noqa: E402
from countries import COUNTRIES, DEFAULTS, EMERGING, EVENTS, GLOBAL_MARKETS, LK_POLICY, WORLD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "data.json"
NOW = time.time()
YEAR = int(time.strftime("%Y", time.gmtime(NOW)))
LAST_ACTUAL = YEAR - 1
HIST_FROM = 1995
MACRO_MAX_AGE = 20 * 3600
NO_DSR = {"XM", "SG"}                    # BIS publishes no debt service ratio for these: asking only raises a false alarm
MACRO_VERSION = 4                        # raise when fetch_macro gains a series, to force one full refresh
ACCUMULATE = {"y10", "cpi_m"}            # monthly series merged with the previous run
PROD_SRC = "World Bank / ILO · growth in output per worker"
Y10_LABEL = {
    "cfets": "China Foreign Exchange Trade System (chinamoney.com.cn) · 10-year government bond yield; history builds up month by month",
    "tesouro": "Tesouro Nacional · fixed-rate bond nearest 10 years to maturity, monthly average",
    "mas": "Monetary Authority of Singapore · 10-year SGS benchmark yield",
    "ecb": "European Central Bank · 10-year yield on AAA-rated euro-area government bonds (daily yield curve, monthly average)",
    "cbsl": "Central Bank of Sri Lanka · Treasury bond auctions, bonds with 7.5–12.5 years to maturity (dated: updated only when CBSL republishes the table)",
}


def ik(d):
    """JSON string keys -> int keys (annual series)."""
    return {int(k): v for k, v in d.items()} if d else {}


def sk(d):
    return {str(k): v for k, v in sorted(d.items())}


def annual_last(periodic):
    by = {}
    for p in sorted(periodic):
        by[int(p[:4])] = periodic[p]
    return by


def annual_mean(periodic):
    by = defaultdict(list)
    for p, v in periodic.items():
        by[int(p[:4])].append(v)
    return {y: round(statistics.mean(v), 2) for y, v in by.items()}


def monthly(periodic, start="2005-01"):
    by = {}
    for p in sorted(periodic):
        m = p[:7]
        if m >= start:
            by[m] = periodic[p]
    return by


def load_prev(url):
    if url:
        try:
            with urllib.request.urlopen(urllib.request.Request(url + f"?t={int(NOW)}", headers={"User-Agent": "econ-bot"}), timeout=30) as r:
                d = json.loads(r.read())
                print("previous state: published site", d.get("generated"))
                return d
        except Exception as e:  # noqa: BLE001
            print("could not read published data:", e)
    if OUT.exists():
        try:
            d = json.loads(OUT.read_text())
            print("previous state: local file", d.get("generated"))
            return d
        except Exception:  # noqa: BLE001
            pass
    return None


# ---------------------------------------------------------------- macro
def fetch_macro():
    print("fetching macro data (World Bank, IMF, BIS, FRED, OECD) ...")
    codes_imf = [c["imf"] for c in COUNTRIES] + [WORLD["imf"]]
    codes_wb = [c["iso3"] for c in COUNTRIES] + [WORLD["iso3"]]
    imf = {}
    for name, ind in [("gdp", "NGDP_RPCH"), ("cpi", "PCPIPCH"), ("unemp", "LUR"), ("gov", "GGXWDG_NGDP"),
                      ("ca", "BCA_NGDPD"), ("gdp_usd", "NGDPD"), ("ppp_share", "PPPSH"), ("gdppc", "NGDPDPC"),
                      ("bal", "GGXCNL_NGDP"), ("pb", "GGXONLB_G01_GDP_PT"), ("rev", "GGR_G01_GDP_PT"), ("exp", "G_X_G01_GDP_PT"), ("pop", "LP")]:
        imf[name] = S.imf(ind, codes_imf)
        print("  imf", name, sum(1 for v in imf[name].values() if v))
    wb = {}
    for name, ind in [("gdp", "NY.GDP.MKTP.KD.ZG"), ("cpi", "FP.CPI.TOTL.ZG"), ("unemp", "SL.UEM.TOTL.ZS"),
                      ("ca", "BN.CAB.XOKA.GD.ZS"), ("res", "FI.RES.TOTL.MO"), ("wbcredit", "FS.AST.PRVT.GD.ZS"),
                      ("prodlvl", "SL.GDP.PCAP.EM.KD")]:
        wb[name] = S.world_bank(ind, codes_wb, HIST_FROM - 12)
        print("  wb", name, sum(1 for v in wb[name].values() if v))
    cli = S.oecd_cli([c["oecd"] for c in COUNTRIES if c["oecd"]] + [WORLD["oecd"], "G7"])
    print("  oecd cli", len(cli))

    eco = {}
    bis_cache = {}
    for c in COUNTRIES:
        k = c["key"]
        s, src, mon = {}, {}, {}

        def pick(name, primary, psrc, fallback=None, fsrc=None):
            d = primary or fallback or {}
            if d:
                s[name] = {y: v for y, v in d.items() if y >= HIST_FROM - 12}
                src[name] = psrc if primary else fsrc

        pick("gdp", imf["gdp"].get(c["imf"]), "IMF WEO · real GDP growth (projections from %d)" % YEAR, wb["gdp"].get(c["iso3"]), "World Bank · real GDP growth")
        pick("cpi", imf["cpi"].get(c["imf"]), "IMF WEO · CPI inflation, annual average", wb["cpi"].get(c["iso3"]), "World Bank · CPI inflation")
        pick("unemp", imf["unemp"].get(c["imf"]), "IMF WEO · unemployment rate", wb["unemp"].get(c["iso3"]), "World Bank / ILO · unemployment")
        pick("gov", imf["gov"].get(c["imf"]), "IMF WEO · general government gross debt % GDP")
        pick("ca", imf["ca"].get(c["imf"]), "IMF WEO · current account % GDP", wb["ca"].get(c["iso3"]), "World Bank · current account % GDP")
        pick("gdp_usd", imf["gdp_usd"].get(c["imf"]), "IMF WEO · nominal GDP, US$ billions")
        pick("ppp_share", imf["ppp_share"].get(c["imf"]), "IMF WEO · share of world GDP at PPP")
        pick("gdppc", imf["gdppc"].get(c["imf"]), "IMF WEO · GDP per person, US$")
        pick("res", wb["res"].get(c["iso3"]), "World Bank · reserves in months of imports")
        pick("bal", imf["bal"].get(c["imf"]), "IMF WEO · government budget balance % GDP")
        pick("pb", imf["pb"].get(c["imf"]), "IMF Fiscal Monitor · primary budget balance % GDP")
        pick("rev", imf["rev"].get(c["imf"]), "IMF Fiscal Monitor · government revenue % GDP")
        pick("exp", imf["exp"].get(c["imf"]), "IMF Fiscal Monitor · government spending % GDP")
        lvl = wb["prodlvl"].get(c["iso3"]) or {}
        prod = {y: round((lvl[y] / lvl[y - 1] - 1) * 100, 2) for y in lvl if y - 1 in lvl and lvl[y - 1]}
        if prod:
            s["prod"] = prod
            src["prod"] = PROD_SRC
        else:  # stand-in when the World Bank series does not arrive: growth in real GDP per person
            g, pop = imf["gdp"].get(c["imf"]) or {}, imf["pop"].get(c["imf"]) or {}
            alt = {y: round(((1 + g[y] / 100) / (pop[y] / pop[y - 1]) - 1) * 100, 2) for y in g if y <= LAST_ACTUAL and y in pop and pop.get(y - 1)}
            if alt:
                s["prod"] = alt
                src["prod"] = "IMF · growth in real GDP per person (stand-in: the World Bank output-per-worker series did not arrive)"

        # BIS: policy rate (monthly), credit and debt service (quarterly)
        if c["bis"]:
            if c["bis"] not in bis_cache:
                bis_cache[c["bis"]] = S.bis("WS_CBPOL", "1.0", f"M.{c['bis']}", "1990")
            pol = bis_cache[c["bis"]]
            if pol:
                s["rate"] = annual_last(pol)
                mon["rate"] = monthly(pol)
                src["rate"] = f"BIS · {c['cb']} policy rate (year end; monthly)"
        if k == "LK":
            pol, tbill = O.cbsl_rates()
            if pol:
                s["rate"] = annual_last(pol)
                mon["rate"] = monthly(pol)
                src["rate"] = "Central Bank of Sri Lanka · policy rate (Overnight Policy Rate; corridor midpoint before Nov 2024), monthly table plus the live policy-rates page"
                if tbill:
                    mon["tbill"] = monthly(tbill)
                    src["tbill"] = "Central Bank of Sri Lanka · 12-month Treasury bill yield"
            ccpi = O.cbsl_inflation()
            if ccpi:
                mon["cpi_m"] = ccpi
                src["cpi_m"] = "Central Bank of Sri Lanka · CCPI inflation, year on year, monthly"
        if k == "EA":
            esi = O.eurostat_esi()
            if esi:
                mon["cli"] = esi
                src["cli"] = "European Commission via Eurostat · Economic Sentiment Indicator (100 = long-run average). Stand-in: the OECD publishes no euro-area leading indicator"
        cb = c.get("credit_bis", c["bis"])
        if cb:
            for name, sec in [("credit", "P"), ("hh", "H"), ("corp", "N")]:
                d = S.bis("WS_TC", "2.0", f"Q.{cb}.{sec}.A.M.770.A", "1990")
                if d:
                    s[name] = annual_last(d)
                    src[name] = "BIS · credit to " + {"P": "private non-financial sector", "H": "households", "N": "non-financial companies"}[sec] + " % GDP"
            d = S.bis("WS_DSR", "1.0", f"Q.{cb}.P", "1999") if cb not in NO_DSR else None
            if d:
                s["dsr"] = annual_mean(d)
                src["dsr"] = "BIS · private-sector debt service ratio (% of income)"
        if "credit" not in s and wb["wbcredit"].get(c["iso3"]):
            s["credit"] = wb["wbcredit"][c["iso3"]]
            src["credit"] = "World Bank · domestic credit to private sector % GDP"
        if c["y10"]:
            d = S.fred(c["y10"])
            if d:
                s["y10"] = annual_mean(d)
                mon["y10"] = monthly(d)
                src["y10"] = f"FRED ({c['y10']}) · 10-year government bond yield"
        fetch = {"cfets": O.china_y10, "tesouro": O.brazil_y10, "mas": O.singapore_y10, "cbsl": O.cbsl_bond10, "ecb": O.ecb_y10}.get(c.get("y10_src"))
        if fetch:
            d = fetch()
            if d:   # a national source, when it answers, replaces the FRED series
                s["y10"] = annual_mean(d)
                mon["y10"] = monthly({m: round(statistics.mean(v for p, v in d.items() if p[:7] == m), 3) for m in {p[:7] for p in d}})
                src["y10"] = Y10_LABEL[c["y10_src"]]
        if c["oecd"] and cli.get(c["oecd"]):
            mon["cli"] = cli[c["oecd"]]
            src["cli"] = "OECD · composite leading indicator (amplitude adjusted, 100 = trend)"
        eco[k] = {"series": s, "monthly": mon, "sources": src}
        print("  ", k, len(s), "annual series,", len(mon), "monthly")

    w = {"series": {}, "monthly": {}, "sources": {}}
    for name in ("gdp", "cpi", "gdp_usd"):
        d = imf[name].get(WORLD["imf"]) or (wb.get(name) or {}).get(WORLD["iso3"])
        if d:
            w["series"][name] = d
    w["sources"] = {"gdp": "IMF WEO · world real GDP growth", "cpi": "IMF WEO · world inflation", "gdp_usd": "IMF WEO · world GDP, US$ billions"}
    for area in (WORLD["oecd"], "G7"):
        if cli.get(area):
            w["monthly"]["cli_" + area] = cli[area]
    w["sources"]["cli"] = "OECD · composite leading indicators for the G20 and G7"
    return eco, w


def merge_macro(new, prev):
    """Keep any previous series a source failed to return this time."""
    if not prev:
        return new
    for part in ("series", "monthly", "sources"):
        for name, v in (prev.get(part) or {}).items():
            if not new[part].get(name):
                new[part][name] = v
            elif part == "monthly" and name in ACCUMULATE:
                new[part][name] = dict(sorted({**v, **new[part][name]}.items()))  # feeds with little history build up over time
                if name == "y10":
                    new["series"]["y10"] = annual_mean(new[part][name])
    return new


# ---------------------------------------------------------------- markets
def equity_stats(q, min_year=250):
    """min_year: trading days needed before a 12-month return is quoted (Colombo trades about 240 days a year)."""
    cl, dates = q["close"], q["dates"]
    p = cl[-1]
    out = {"price": round(p, 2), "date": dates[-1]}
    if len(cl) >= 2:
        out["day_chg"] = round((cl[-1] / cl[-2] - 1) * 100, 2)
    if len(cl) >= min_year:
        out["ret_12m"] = round((p / cl[-252 if len(cl) >= 252 else 0] - 1) * 100, 1)
    if len(cl) >= 200:
        out["above_200d"] = p > sum(cl[-200:]) / 200
    yr = cl[-252:]
    out["drawdown"] = round((p / max(yr) - 1) * 100, 1)
    out["spark"] = {"dates": dates[-260:], "close": [round(x, 2) for x in cl[-260:]]}
    return out


def fetch_markets(prev):
    print("fetching markets ...")
    eq = {}
    prev_eco = (prev or {}).get("economies", {})
    for c in COUNTRIES:
        if c["index"] == "CSE":
            a = S.cse_aspi()
            old = (prev_eco.get(c["key"], {}).get("now", {}).get("equity") or {})
            hist = dict(zip(old.get("spark", {}).get("dates", []), old.get("spark", {}).get("close", [])))
            hist.update(O.cse_history() or {})          # about a year of daily closes from the exchange
            if a:
                hist[time.strftime("%Y-%m-%d", time.gmtime(a["time"]))] = a["price"]
            if hist and (a or len(hist) > 1):
                ds = sorted(hist)[-260:]
                st = equity_stats({"dates": ds, "close": [hist[x] for x in ds]}, min_year=225)
                if a:
                    st["day_chg"] = a["change_pct"]
                eq[c["key"]] = {**st, "note": "Colombo Stock Exchange"}
            elif old:
                eq[c["key"]] = {**old, "stale": True}
            continue
        q = S.yahoo(c["index"])
        if q:
            eq[c["key"]] = equity_stats(q)
        elif prev_eco.get(c["key"], {}).get("now", {}).get("equity"):
            eq[c["key"]] = prev_eco[c["key"]]["now"]["equity"]
            eq[c["key"]]["stale"] = True
    w = S.yahoo(WORLD["index"])
    world_eq = equity_stats(w) if w else (prev or {}).get("world", {}).get("now", {}).get("equity")

    mk = []
    prev_mk = {m["symbol"]: m for m in (prev or {}).get("markets", [])}
    for sym, label, unit in GLOBAL_MARKETS:
        q = S.yahoo(sym, "1y")
        if q:
            st = equity_stats(q)
            st["spark"] = {"dates": st["spark"]["dates"][-90:], "close": st["spark"]["close"][-90:]}
            mk.append({"symbol": sym, "label": label, "unit": unit, **st})
        elif sym in prev_mk:
            mk.append({**prev_mk[sym], "stale": True})
    rates, fxdate = S.fx_latest()
    hist = S.fx_history()
    fx = {}
    for c in COUNTRIES:
        ccy = c["ccy"]
        if ccy == "USD":
            dxy = next((m for m in mk if m["symbol"] == "DX-Y.NYB"), None)
            fx["US"] = {"ccy": "USD", "per_usd": 1.0, "chg_12m": dxy.get("ret_12m") if dxy else None, "note": "vs basket (DXY)"}
            continue
        now_r = rates.get(ccy)
        h = hist.get(ccy) or {}
        chg = None
        if h and now_r:
            old = h[sorted(h)[0]]
            chg = round((old / now_r - 1) * 100, 1)  # + = local currency stronger vs USD
        fx[c["key"]] = {"ccy": ccy, "per_usd": now_r, "chg_12m": chg, "date": fxdate}
    return eq, world_eq, mk, fx


# ---------------------------------------------------------------- news
def fetch_news(prev):
    print("fetching news ...")
    by = {}
    prev_news = (prev or {}).get("news", {}).get("by", {})
    for c in COUNTRIES:
        items = N.fetch(N.query_for(c), key=c["key"], max_items=16)
        by[c["key"]] = items or prev_news.get(c["key"], [])
    world = N.fetch('"global economy" OR "world economy" OR IMF OR "Federal Reserve" OR "oil prices" OR "global markets"', max_items=20, max_age_days=3)
    by["WORLD"] = world or prev_news.get("WORLD", [])
    return by


# ---------------------------------------------------------------- assemble
def build(prev, full):
    prev_ok = prev and prev.get("schema") == 2
    macro_age = NOW - (prev.get("macro_fetched_ts", 0) if prev_ok else 0)
    has_new = prev_ok and prev.get("macro_version") == MACRO_VERSION   # a newer bot fetches series the old file lacks
    if full or not prev_ok or not has_new or macro_age > MACRO_MAX_AGE:
        eco_raw, world_raw = fetch_macro()
        for k in eco_raw:
            pe = prev["economies"].get(k) if prev_ok else None
            eco_raw[k] = merge_macro(eco_raw[k], pe and {"series": pe["series"], "monthly": pe["monthly"], "sources": pe["sources"]})
        world_raw = merge_macro(world_raw, prev_ok and prev.get("world") and {p: prev["world"].get(p) for p in ("series", "monthly", "sources")})
        macro_ts = NOW
    else:
        print(f"macro data is {macro_age / 3600:.1f}h old: reusing it")
        eco_raw = {k: {"series": e["series"], "monthly": e["monthly"], "sources": e["sources"]} for k, e in prev["economies"].items()}
        world_raw = {p: prev["world"][p] for p in ("series", "monthly", "sources")}
        macro_ts = prev["macro_fetched_ts"]

    if any((e["sources"].get("prod") or "") != PROD_SRC for e in eco_raw.values()):
        # the World Bank API times out now and then: one retry for the productivity series on every run until it lands
        lvls = S.world_bank("SL.GDP.PCAP.EM.KD", [c["iso3"] for c in COUNTRIES], HIST_FROM - 12)
        for c in COUNTRIES:
            lvl = lvls.get(c["iso3"]) or {}
            prod = {y: round((lvl[y] / lvl[y - 1] - 1) * 100, 2) for y in lvl if y - 1 in lvl and lvl[y - 1]}
            if prod and c["key"] in eco_raw:
                eco_raw[c["key"]]["series"]["prod"] = prod
                eco_raw[c["key"]]["sources"]["prod"] = PROD_SRC

    eq, world_eq, markets, fx = fetch_markets(prev if prev_ok else None)
    news = fetch_news(prev if prev_ok else None)

    economies = {}
    world_gdp_usd = ik(world_raw["series"].get("gdp_usd", {})).get(YEAR)
    for c in COUNTRIES:
        k = c["key"]
        raw = eco_raw.get(k, {"series": {}, "monthly": {}, "sources": {}})
        s = {n: ik(v) for n, v in raw["series"].items()}
        mon = raw["monthly"]
        notes = []
        if k == "LK" and "rate" not in mon:   # CBSL never reached: fall back to the hand-entered year-end values
            s["rate"] = dict(LK_POLICY)
            mon = {**mon, "rate": {f"{y}-12": v for y, v in LK_POLICY.items()}}
            raw["sources"]["rate"] = "CBSL policy rate: hand-entered backstop, because the CBSL site could not be read"
            notes.append("Sri Lanka's policy rate could not be read from the CBSL website, so hand-entered year-end values are shown. Check Data health.")
        rate_m = mon.get("rate") or {}
        latest_rate = rate_m[max(rate_m)] if rate_m else None
        rate_date = max(rate_m) if rate_m else None
        rate_chg_12m = None
        if rate_m:
            ks = sorted(rate_m)
            target_m = f"{int(ks[-1][:4]) - 1}{ks[-1][4:]}"
            older = [m for m in ks if m <= target_m]
            if older:
                rate_chg_12m = round(rate_m[ks[-1]] - rate_m[older[-1]], 2)
        if k == "SG":
            notes.append("Singapore has no policy interest rate: MAS manages the exchange rate, so rate-based rules are skipped.")
            notes.append("Singapore's government debt is issued to build reserves and is matched by large assets, so the debt score overstates its risk.")
        if c.get("aggregate"):
            notes.append("Euro area is an aggregate of its member countries, so it overlaps Germany and France in world totals.")

        ph_det = A.phase_details(k, s, c["target"], 2000, LAST_ACTUAL)
        ph_hist = {y: d["phase"] for y, d in ph_det.items()}
        ph_now, inputs = A.phase_now(k, s, c["target"], YEAR, latest_rate)
        cli = A.cli_phase(mon.get("cli"))
        if cli:
            cli["label"] = "EC economic sentiment indicator" if k == "EA" else "OECD leading indicator"
        cpi_m = mon.get("cpi_m") or {}
        cpi_latest = {"value": cpi_m[max(cpi_m)], "month": max(cpi_m), "prev": cpi_m.get(sorted(cpi_m)[-2]) if len(cpi_m) > 1 else None} if cpi_m else None
        gov, credit = s.get("gov", {}), s.get("credit", {})
        gy = max((y for y in gov if y <= LAST_ACTUAL), default=None)
        cy = max(credit, default=None)
        y10_m = mon.get("y10") or {}
        y10_now = y10_m[max(y10_m)] if y10_m else None
        if y10_m and (YEAR - int(max(y10_m)[:4])) * 12 + int(time.strftime("%m", time.gmtime(NOW))) - int(max(y10_m)[5:]) > 6:
            y10_now = None   # more than six months old: kept on the chart, but not used in any live signal
        nominal = (s.get("gdp", {}).get(YEAR, 0) + s.get("cpi", {}).get(YEAR, 0)) if s.get("gdp", {}).get(YEAR) is not None and s.get("cpi", {}).get(YEAR) is not None else None
        min_rate = min((v for y, v in s.get("rate", {}).items() if y >= 2008), default=None)
        backed = bool(c.get("asset_backed"))
        gdp_s, cpi_s = s.get("gdp", {}), s.get("cpi", {})
        crisis = A.crisis_year(gdp_s, cpi_s, YEAR, DEFAULTS.get(k))
        r_now = y10_now if y10_now is not None else latest_rate
        r_label = "10-year yield" if y10_now is not None else "Policy rate"
        lt, _, lt_why = A.lt_score(None if backed else (gov.get(gy) if gy else None), credit.get(cy) if cy else None,
                                   gov.get(gy - 10) if gy else None, credit.get(cy - 10) if cy else None,
                                   min_rate, r_now, nominal, k in EMERGING, crisis, YEAR, r_label)
        cpi_now, cpi_prev = cpi_s.get(YEAR), cpi_s.get(YEAR - 1)
        cpi_real = cpi_latest["value"] if cpi_latest else cpi_now   # the latest monthly reading, where a national source gives one
        real = round(latest_rate - cpi_real, 2) if latest_rate is not None and cpi_real is not None else None
        hh_s, dsr_s = s.get("hh", {}), s.get("dsr", {})
        tot = (lambda y: (0 if backed else gov[y]) + credit[y] if y in credit and (backed or y in gov) else None)
        c10 = tot(cy) - tot(cy - 10) if cy and tot(cy) is not None and tot(cy - 10) is not None else None
        c5 = credit[cy] - credit[cy - 5] if cy and cy - 5 in credit else None
        ltc = A.lt_cycle({
            "score": lt, "private": credit.get(cy) if cy else None, "hh": hh_s[max(hh_s)] if hh_s else None,
            "dsr": dsr_s[max(dsr_s)] if dsr_s else None, "total_chg_10y": c10, "private_chg_5y": c5, "min_rate": min_rate,
            "cpi_avg2": (cpi_now + cpi_prev) / 2 if cpi_now is not None and cpi_prev is not None else None,
            "cpi_now": cpi_now, "target": c["target"], "crisis": crisis, "year": YEAR,
            "gdp_last2": [gdp_s.get(LAST_ACTUAL - 1), gdp_s.get(LAST_ACTUAL)], "gov": gov.get(gy) if gy else None,
            "gov_peak": max((v for y, v in gov.items() if crisis and crisis - 1 <= y <= LAST_ACTUAL), default=None)})
        if ltc:
            ltc.update(score=lt, why=lt_why, name=A.LT_STAGES[ltc["stage"]], crisis=crisis,
                       flags=A.lt_evidence(s, LAST_ACTUAL, crisis, EVENTS.get(k, []), backed))
        pb_s = s.get("pb") or s.get("bal") or {}
        rev_s = s.get("rev", {})
        lev = A.levers({
            "pb": pb_s.get(YEAR), "pb_3y": pb_s.get(YEAR - 3), "bal_label": "Primary budget balance" if s.get("pb") else "Budget balance",
            "crisis": crisis, "year": YEAR, "private_chg_5y": c5, "rev": rev_s.get(YEAR), "rev_5y": rev_s.get(YEAR - 5),
            "real_rate": real, "nominal": nominal, "rate": r_now, "rate_label": r_label.lower()})
        rules = A.rules_of_thumb(credit, s.get("prod", {}), LAST_ACTUAL,
                                 "output per worker" if raw["sources"].get("prod") == PROD_SRC else "output per person")
        tone = N.tone_summary(news.get(k, []))
        e = eq.get(k)
        res = s.get("res", {})
        ca = s.get("ca", {})
        dsr = s.get("dsr", {})
        metrics = {
            "phase": ph_now, "cli_phase": cli and cli["phase"], "rate_chg_12m": rate_chg_12m,
            "eq_ret_12m": e and e.get("ret_12m"), "eq_above_200d": e and e.get("above_200d"), "eq_drawdown": e and e.get("drawdown"),
            "news_tone": tone["score"] if tone["n"] >= 5 else None, "real_rate": real, "cpi": cpi_now, "cpi_prev": cpi_prev,
            "target": c["target"], "y10": y10_now, "gov_debt": gov.get(gy) if gy else None, "asset_backed": backed,
            "r_minus_g": round(y10_now - nominal, 2) if y10_now is not None and nominal is not None else None,
            "ca": ca.get(YEAR, ca.get(LAST_ACTUAL)), "reserves_months": res[max(res)] if res else None,
            "fx_chg_12m": (fx.get(k) or {}).get("chg_12m"), "dsr": dsr[max(dsr)] if dsr else None,
        }
        scr = A.screen(metrics)
        now = {"phase": ph_now, "inputs": inputs, "rate": latest_rate, "rate_date": rate_date, "rate_chg_12m": rate_chg_12m,
               "y10": y10_now, "y10_date": max(y10_m) if y10_m else None, "cli": cli, "lt": ltc, "levers": lev, "rules": rules, "nominal": A.r1(nominal, 2), "cpi_latest": cpi_latest,
               "equity": e, "fx": fx.get(k), "news_tone": tone, "real_rate": real, "metrics": metrics,
               "share_nominal": round(s["gdp_usd"][YEAR] / world_gdp_usd * 100, 2) if world_gdp_usd and s.get("gdp_usd", {}).get(YEAR) else None,
               "share_ppp": s.get("ppp_share", {}).get(YEAR)}
        economies[k] = {
            **{f: c[f] for f in ("key", "name", "flag", "ccy", "cb", "index_name", "region", "target")},
            "aggregate": bool(c.get("aggregate")),
            "series": {n: sk({y: v for y, v in d.items() if y >= HIST_FROM - 12}) for n, d in s.items()},
            "monthly": mon, "sources": raw["sources"], "notes": notes,
            "events": sorted(EVENTS.get(k, []) + [g for g in EVENTS["GLOBAL"] if g[0] not in {x[0] for x in EVENTS.get(k, [])}]),
            "phases": sk(ph_hist), "phase_detail": sk(ph_det), "now": now, "screen": scr,
        }
        economies[k]["summary"] = A.summary(c, now, YEAR)

    # world
    ws = {n: ik(v) for n, v in world_raw["series"].items()}
    wcli = A.cli_phase(world_raw["monthly"].get("cli_G20"))
    wtr = A.trend(ws.get("gdp", {}), YEAR)
    counts = defaultdict(int)
    for e in economies.values():
        if not e["aggregate"] and e["now"]["phase"]:
            counts[e["now"]["phase"]] += 1
    contrib = {k: round(e["now"]["share_ppp"] * (ik(e["series"].get("gdp", {})).get(YEAR) or 0) / 100, 2)
               for k, e in economies.items() if e["now"]["share_ppp"] and not e["aggregate"]}
    w_gdp = ws.get("gdp", {}).get(YEAR)
    world = {
        "series": world_raw["series"], "monthly": world_raw["monthly"], "sources": world_raw["sources"],
        "now": {"gdp": w_gdp, "gdp_prev": ws.get("gdp", {}).get(YEAR - 1), "trend": A.r1(wtr, 2), "cpi": ws.get("cpi", {}).get(YEAR),
                "cpi_prev": ws.get("cpi", {}).get(YEAR - 1), "cli": wcli, "cli_g7": A.cli_phase(world_raw["monthly"].get("cli_G7")),
                "equity": world_eq, "phase_counts": dict(counts), "growth_contrib": contrib,
                "gdp_usd": world_gdp_usd},
    }
    lean = max(counts, key=counts.get) if counts else None
    world["summary"] = " ".join(x for x in [
        f"The IMF expects the world economy to grow {w_gdp:.1f}% in {YEAR}" + (f", against a 10-year trend of {wtr:.1f}%." if wtr else ".") if w_gdp is not None else "",
        f"The G20 leading indicator is {wcli['level']:.2f} and in {A.CLI_PHASES[wcli['phase']].lower()} ({wcli['chg3m']:+.2f} over 3 months to {wcli['month']})." if wcli else "",
        f"Of the {sum(counts.values())} economies tracked, the most common phase is {A.PHASES[lean].lower()} ({counts[lean]})." if lean else "",
        f"The {len(contrib)} economies here generate {sum(contrib.values()):.1f} points of world growth between them (PPP weights)." if contrib else "",
    ] if x)

    data = {
        "schema": 2, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW)), "generated_ts": int(NOW),
        "macro_fetched_ts": int(macro_ts), "macro_version": MACRO_VERSION, "year": YEAR, "last_actual": LAST_ACTUAL,
        "economies": economies, "world": world, "markets": markets,
        "news": {"by": news}, "health": S.LOG[-60:],
    }
    changes = A.diff(prev if prev_ok else None, data, int(NOW))
    data["changes"] = (changes + ((prev or {}).get("changes", []) if prev_ok else []))[:200]
    data["changes_this_run"] = len(changes)
    return data


def validate(d):
    errs = []
    eco = d["economies"]
    if len(eco) < 10:
        errs.append("fewer than 10 economies")
    with_gdp = sum(1 for e in eco.values() if e["series"].get("gdp"))
    if with_gdp < 10:
        errs.append(f"only {with_gdp} economies have GDP data")
    with_phase = sum(1 for e in eco.values() if e["now"]["phase"])
    if with_phase < 8:
        errs.append(f"only {with_phase} economies have a current phase")
    if not d["world"]["series"].get("gdp"):
        errs.append("world GDP missing")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--prev", default=None, help="URL of the published data.json")
    a = ap.parse_args()
    prev = load_prev(a.prev)
    data = build(prev, a.full)
    errs = validate(data)
    if errs:
        print("VALIDATION FAILED, keeping the previous data:", errs)
        sys.exit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(OUT)
    ok = sum(1 for h in S.LOG if h["ok"])
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB) · {data['changes_this_run']} changes · {len(S.LOG) - ok} source warnings")
    for h in S.LOG:
        if not h["ok"]:
            print("  warn:", h["source"], h["detail"])


if __name__ == "__main__":
    main()
