"""Gap-filling bots: figures that the big international feeds do not carry, read from the
national authority that publishes them.

  Sri Lanka   policy rate (monthly since 2003), 12-month T-bill, ~10-year Treasury bond auction yield,
              monthly CCPI inflation            Central Bank of Sri Lanka (cbsl.gov.lk)
  Sri Lanka   All Share index history            Colombo Stock Exchange (cse.lk)
  China       10-year government bond yield      China Foreign Exchange Trade System (chinamoney.com.cn)
  Brazil      ~10-year fixed-rate bond yield     Tesouro Nacional (tesourotransparente.gov.br)
  Singapore   10-year SGS benchmark yield        Monetary Authority of Singapore (eservices.mas.gov.sg)
  Euro area   economic sentiment indicator       European Commission via Eurostat
  Euro area   10-year government bond yield      European Central Bank yield curve (AAA-rated issuers)

Every function has a pure parser (unit-tested with samples) and a thin fetcher. A parser returns
only values inside a sane range; anything else is dropped and logged, so a changed page layout
shows up as a warning under "Data health" and the last good value stays on the dashboard.
Standard library only.
"""
import csv
import datetime
import html
import http.cookiejar
import io
import json
import re
import statistics
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

from sources import _log, get

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
CBSL = "https://www.cbsl.gov.lk"
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
MON3 = {m[:3]: i for m, i in MONTHS.items()}


def get_bytes(url, timeout=60, tries=2):
    err = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            err = e
    _log(url.split("/")[2], False, f"{err} · {url[:90]}")
    return None


def sane(d, lo, hi, name):
    """Keep only values inside [lo, hi]. A source that suddenly returns nonsense must not reach the page."""
    ok = {k: v for k, v in d.items() if v is not None and lo <= v <= hi}
    if len(ok) < len(d):
        _log(name, False, f"dropped {len(d) - len(ok)} value(s) outside {lo}–{hi}")
    return ok


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------- minimal .xlsx reader (an .xlsx file is a zip of XML sheets) ----------
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def xlsx_rows(data, sheet=1):
    """[{column letter: cell text}] for one sheet, in row order."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(_NS + "t")))
    rows = []
    for r in ET.fromstring(z.read(f"xl/worksheets/sheet{sheet}.xml")).iter(_NS + "row"):
        row = {}
        for c in r.findall(_NS + "c"):
            v = c.find(_NS + "v")
            if v is None or v.text is None:
                continue
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            row[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
        rows.append(row)
    return rows


def excel_date(serial):
    return datetime.date(1899, 12, 30) + datetime.timedelta(days=float(serial))


def _find_link(page_html, pattern):
    m = re.search(r'href="([^"]+)"[^>]*>\s*' + pattern, page_html or "", re.I)
    if not m:
        return None
    return m.group(1) if m.group(1).startswith("http") else CBSL + m.group(1)


# ---------- Central Bank of Sri Lanka ----------
def parse_cbsl_rates(rows):
    """Table 4.04 'Interest Rates - Monthly'. Column B year, C month, D Overnight Policy Rate (from Nov 2024),
    E/F standing deposit/lending facility rates, I 12-month Treasury bill yield.
    Before the OPR existed the policy rate is the middle of the E–F corridor."""
    policy, tbill, year = {}, {}, None
    for r in rows:
        y = num(r.get("B"))
        if y and 1990 <= y <= 2100 and float(y).is_integer():
            year = int(y)
        mth = MONTHS.get(str(r.get("C", "")).strip().lower())
        if not year or not mth:
            continue
        key = f"{year}-{mth:02d}"
        opr, lo, hi = num(r.get("D")), num(r.get("E")), num(r.get("F"))
        if opr is not None:
            policy[key] = opr
        elif lo is not None and hi is not None:
            policy[key] = round((lo + hi) / 2, 3)
        tb = num(r.get("I"))
        if tb is not None:
            tbill[key] = round(tb, 2)
    return sane(policy, 0.5, 40, "CBSL policy rate"), sane(tbill, 0.5, 45, "CBSL T-bill")


def parse_cbsl_corridor(page_html):
    """The live 'Policy Rates' page lists the standing deposit and lending facility rates, which sit a fixed
    margin either side of the Overnight Policy Rate. Returns the middle of the two, or None."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<head.*?</head>|<script.*?</script>", "", page_html or "", flags=re.S)))
    t = re.sub(r"\s+", " ", t)
    lo = re.search(r"Standing Deposit Facility Rate \(SDFR\)\s*([0-9]{1,2}(?:\.[0-9]+)?)\b", t)
    hi = re.search(r"Standing Lending Facility Rate \(SLFR\)\s*([0-9]{1,2}(?:\.[0-9]+)?)\b", t)
    if not lo or not hi:
        return None
    a, b = float(lo.group(1)), float(hi.group(1))
    if not (0.5 <= a < b <= 40 and b - a <= 3):
        return None
    return round((a + b) / 2, 3)


def cbsl_rates(today=None):
    """({'YYYY-MM': policy rate}, {'YYYY-MM': 12-month T-bill yield}) or (None, None)."""
    page = get(CBSL + "/en/statistics/statistical-tables/monetary-sector", ua=UA, tries=2)
    link = _find_link(page, r"Interest Rates - Monthly")
    data = get_bytes(link) if link else None
    if not data:
        _log("CBSL", False, "monthly interest-rate table not found")
        return None, None
    try:
        policy, tbill = parse_cbsl_rates(xlsx_rows(data))
    except Exception as e:  # noqa: BLE001
        _log("CBSL", False, f"interest-rate table: {e}")
        return None, None
    if len(policy) < 100:
        _log("CBSL", False, f"interest-rate table: only {len(policy)} months parsed")
        return None, None
    # the table lags a month or two: bring it up to this month with the live policy-rates page
    now = parse_cbsl_corridor(get(CBSL + "/en/rates-and-indicators/policy-rates", ua=UA, tries=2))
    today = today or datetime.date.today()
    if now is not None:
        # months between the table's end and this month are left out rather than guessed
        policy[f"{today.year}-{today.month:02d}"] = now
    else:
        _log("CBSL", False, "policy-rates page: corridor not found, using the monthly table only")
    return policy, tbill


def parse_cbsl_bonds(rows):
    """Treasury bond auctions: C settlement date, D maturity date (Excel serials), J weighted average yield.
    Returns the monthly average yield of bonds sold with 7.5–12.5 years to maturity."""
    by = defaultdict(list)
    for r in rows:
        try:
            d, mat, y = excel_date(r["C"]), excel_date(r["D"]), float(r["J"])
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        if 7.5 <= (mat - d).days / 365.25 <= 12.5 and y > 0:
            by[d.strftime("%Y-%m")].append(y)
    return sane({k: round(statistics.mean(v), 2) for k, v in by.items()}, 1, 45, "CBSL bond yield")


def cbsl_bond10():
    for sector in ("fiscal-sector", "financial-sector", "monetary-sector"):
        link = _find_link(get(CBSL + f"/en/statistics/statistical-tables/{sector}", ua=UA, tries=2), r"Treasury Bond Auctions")
        if link:
            data = get_bytes(link)
            try:
                out = parse_cbsl_bonds(xlsx_rows(data)) if data else None
            except Exception as e:  # noqa: BLE001
                _log("CBSL", False, f"bond auctions: {e}")
                return None
            if out and len(out) >= 24:
                return out
    _log("CBSL", False, "Treasury bond auction table not found")
    return None


def parse_cbsl_inflation(js):
    """The CBSL inflation chart: month labels ('Oct 26') and a CCPI year-on-year series."""
    cats = re.search(r"categories\s*:\s*\[([^\]]+)\]", js or "")
    ser = re.search(r"name\s*:\s*'[^']*CCPI[^']*'\s*,\s*data\s*:\s*\[([^\]]+)\]", js or "", re.S)
    if not cats or not ser:
        return {}
    labels = re.findall(r"'([A-Za-z]{3})\s+(\d{2})'", cats.group(1))
    vals = [num(v) for v in ser.group(1).split(",") if v.strip()]
    out = {}
    for (mon, yy), v in zip(labels, vals):
        if mon.lower() in MON3 and v is not None:
            out[f"20{yy}-{MON3[mon.lower()]:02d}"] = v
    return sane(out, -15, 100, "CBSL inflation")


def cbsl_inflation():
    out = parse_cbsl_inflation(get(CBSL + "/cbsl_custom/param/inflationchart.php", ua=UA, tries=2))
    if not out:
        _log("CBSL", False, "inflation chart: CCPI series not found")
    return out or None


# ---------- Colombo Stock Exchange ----------
def parse_cse_history(txt):
    pts = {}
    for p in json.loads(txt):
        if p.get("v"):
            pts[datetime.datetime.fromtimestamp(p["d"] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")] = round(float(p["v"]), 2)
    return sane(pts, 100, 1e6, "CSE index")


def cse_history():
    """About a year of daily closes for the All Share Price Index. {'YYYY-MM-DD': close} or None."""
    txt = get("https://www.cse.lk/api/chartData", data=b"symbol=ASPI&chartId=1&period=5", ua=UA, tries=2)
    try:
        out = parse_cse_history(txt) if txt else None
    except Exception as e:  # noqa: BLE001
        _log("CSE", False, f"history: {e}")
        return None
    return out if out and len(out) >= 20 else None


# ---------- China: CFETS government bond yields ----------
def parse_china_yields(txt):
    out = {}
    for r in json.loads(txt).get("records", []):
        try:
            d = datetime.datetime.strptime(r["dateString"], "%d %b %Y").strftime("%Y-%m-%d")
            out[d] = float(r["tenRate"])
        except (KeyError, ValueError, TypeError):
            continue
    return sane(out, 0.1, 15, "China 10-year yield")


def china_y10():
    """Daily 10-year government bond yield for about the last month (the feed carries no deeper history)."""
    txt = get("https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/SddsIntrRateGovYldHis?lang=EN&pageNum=1&pageSize=40", ua=UA, tries=2)
    try:
        out = parse_china_yields(txt) if txt else None
    except Exception as e:  # noqa: BLE001
        _log("CFETS", False, str(e))
        return None
    if not out:
        _log("CFETS", False, "no 10-year yields in the response")
    return out or None


# ---------- Brazil: Tesouro Nacional ----------
def parse_brazil_yields(text):
    """Tesouro Direto daily prices and rates. For each day take the fixed-rate bond ('Tesouro Prefixado...')
    whose maturity is nearest to 10 years (at least 6 years out); return the monthly average of its yield."""
    best = {}
    rd = csv.reader(io.StringIO(text), delimiter=";")
    next(rd, None)
    for r in rd:
        if len(r) < 4 or not r[0].startswith("Tesouro Prefixado"):
            continue
        try:
            mat = datetime.datetime.strptime(r[1], "%d/%m/%Y").date()
            base = datetime.datetime.strptime(r[2], "%d/%m/%Y").date()
            y = float(r[3].replace(".", "").replace(",", "."))
        except ValueError:
            continue
        yrs = (mat - base).days / 365.25
        if yrs >= 6 and (base not in best or abs(yrs - 10) < abs(best[base][0] - 10)):
            best[base] = (yrs, y)
    by = defaultdict(list)
    for d, (_, y) in best.items():
        by[d.strftime("%Y-%m")].append(y)
    return sane({k: round(statistics.mean(v), 2) for k, v in by.items()}, 1, 40, "Brazil 10-year yield")


def brazil_y10():
    data = get_bytes("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/"
                     "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv", timeout=120)
    try:
        out = parse_brazil_yields(data.decode("latin-1")) if data else None
    except Exception as e:  # noqa: BLE001
        _log("Tesouro Nacional", False, str(e))
        return None
    return out if out and len(out) >= 24 else None


# ---------- Singapore: MAS benchmark yields ----------
def parse_mas_table(page_html):
    """Result table of the MAS 'SGS Prices and Yields - Benchmark Issues' query, monthly frequency:
    rows of [year, month, yield] where the year is only written on its first row."""
    out, year = {}, None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html or "", re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 3:
            continue
        if re.fullmatch(r"(19|20)\d\d", cells[0]):
            year = int(cells[0])
        mon = MON3.get(cells[1][:3].lower())
        v = num(cells[-1])
        if year and mon and v is not None:
            out[f"{year}-{mon:02d}"] = v
    return sane(out, 0.05, 15, "Singapore 10-year yield")


def singapore_y10(start_year=2005):
    """Month-end 10-year SGS benchmark yield. The MAS site answers a small query form, so this loads the
    form, then posts it back asking for the 10-year yield at monthly frequency."""
    url = "https://eservices.mas.gov.sg/statistics/fdanet/BenchmarkPricesAndYields.aspx"
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        page = op.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=45).read().decode("utf-8", "replace")
        hidden = {n: html.unescape(v) for n, v in re.findall(r'<input type="hidden" name="(__[A-Z]+)" id="[^"]*" value="([^"]*)"', page)}
        p = "ctl00$ContentPlaceHolder1$"
        form = {**hidden, p + "StartYearDropDownList": str(start_year), p + "StartMonthDropDownList": "1",
                p + "EndYearDropDownList": str(datetime.date.today().year), p + "EndMonthDropDownList": "12",
                p + "FrequencyDropDownList": "M", p + "TenYearBondYieldCheckBox": "on", p + "DisplayButton": "Display"}
        res = op.open(urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), headers={"User-Agent": UA, "Referer": url}),
                      timeout=90).read().decode("utf-8", "replace")
        out = parse_mas_table(res)
    except Exception as e:  # noqa: BLE001
        _log("MAS", False, str(e))
        return None
    if len(out) < 24:
        _log("MAS", False, f"only {len(out)} months of 10-year yields parsed")
        return None
    return out


# ---------- Euro area: European Commission economic sentiment (Eurostat) ----------
def parse_eurostat(txt):
    d = json.loads(txt)
    idx = d["dimension"]["time"]["category"]["index"]
    vals = d.get("value", {})
    return sane({t: float(vals[str(i)]) for t, i in idx.items() if str(i) in vals}, 40, 140, "EC sentiment")


EURO_AREA_CODES = ["EA20", "EA21"]  # the euro area's Eurostat code changes when a country joins: add the new code at the end


def eurostat_esi(since="2005-01"):
    """Economic Sentiment Indicator for the euro area, seasonally adjusted, long-run average = 100.
    {'YYYY-MM': value} or None. Later codes overwrite earlier ones, so the series follows the current membership."""
    out = {}
    for geo in EURO_AREA_CODES:
        txt = get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/ei_bssi_m_r2"
                  f"?format=JSON&geo={geo}&indic=BS-ESI-I&s_adj=SA&sinceTimePeriod={since}", tries=2)
        try:
            out.update(parse_eurostat(txt) if txt else {})
        except Exception as e:  # noqa: BLE001
            _log("Eurostat", False, f"{geo}: {e}")
    if len(out) < 24:
        return None
    last = max(out)
    age = (datetime.date.today().year - int(last[:4])) * 12 + datetime.date.today().month - int(last[5:])
    if age > 4:
        _log("Eurostat", False, f"euro-area sentiment stops at {last}: the area code may have changed (see EURO_AREA_CODES)")
    return out


# ---------- Euro area: ECB yield curve ----------
def parse_ecb_csv(text):
    """ECB data-portal CSV -> monthly average of the daily observations. {'YYYY-MM': value}"""
    by = defaultdict(list)
    for r in csv.DictReader(io.StringIO(text)):
        v = num(r.get("OBS_VALUE"))
        if v is not None and r.get("TIME_PERIOD"):
            by[r["TIME_PERIOD"][:7]].append(v)
    return sane({k: round(statistics.mean(v), 3) for k, v in by.items()}, -2, 20, "ECB 10-year yield")


def ecb_y10(start="2005-01-01"):
    """10-year spot yield on AAA-rated euro-area government bonds, from the ECB's daily yield curve."""
    txt = get("https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
              f"?startPeriod={start}&format=csvdata", accept="text/csv", tries=2, timeout=90)
    try:
        out = parse_ecb_csv(txt) if txt else None
    except Exception as e:  # noqa: BLE001
        _log("ECB", False, f"yield curve: {e}")
        return None
    return out if out and len(out) >= 24 else None
