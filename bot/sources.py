"""Free data sources. Standard library only, so the bot runs anywhere with Python 3.9+.

Every function returns an empty result on failure instead of raising: one dead
source must never stop the whole update. The caller keeps the previous values.
"""
import csv
import io
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict

LOG = []  # (source, ok, detail) — written into the data file as a health report


def _log(src, ok, detail=""):
    LOG.append({"source": src, "ok": bool(ok), "detail": str(detail)[:160]})


def get(url, ua="curl/8.7.1", tries=3, timeout=45, data=None, accept="*/*"):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": ua, "Accept": accept})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(1.5 * (i + 1))
    _log(url.split("/")[2], False, f"{err} · {url[:90]}")
    return None


# ---------- annual macro ----------
_WB_FAILS = 0


def world_bank(indicator, iso3s, start=1990):
    """{iso3: {year: value}}"""
    global _WB_FAILS
    out = defaultdict(dict)
    if _WB_FAILS >= 2:  # the API is down: don't spend minutes timing out on every indicator; previous values are kept
        _log("World Bank", False, f"{indicator}: skipped, the API failed twice already this run")
        return out
    url = (f"https://api.worldbank.org/v2/country/{';'.join(iso3s)}/indicator/{indicator}"
           f"?format=json&per_page=20000&date={start}:2031")
    txt = get(url, tries=2, timeout=40)
    _WB_FAILS = 0 if txt else _WB_FAILS + 1
    try:
        data = json.loads(txt) if txt else []
        for row in (data[1] if len(data) > 1 and data[1] else []):
            if row["value"] is not None:
                out[row["countryiso3code"]][int(row["date"])] = round(float(row["value"]), 3)
    except Exception as e:  # noqa: BLE001
        _log("World Bank", False, f"{indicator}: {e}")
    return out


def imf(indicator, codes):
    """IMF DataMapper (WEO incl. projections). {code: {year: value}}"""
    txt = get(f"https://www.imf.org/external/datamapper/api/v1/{indicator}/" + "/".join(codes))
    out = defaultdict(dict)
    try:
        vals = json.loads(txt).get("values", {}).get(indicator, {}) if txt else {}
        for code in codes:
            for y, x in (vals.get(code) or {}).items():
                if x is not None:
                    out[code][int(y)] = round(float(x), 3)
    except Exception as e:  # noqa: BLE001
        _log("IMF", False, f"{indicator}: {e}")
    return out


def bis(flow, ver, key, start="1990"):
    """BIS SDMX CSV -> {period: value}"""
    txt = get(f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/{ver}/{key}?format=csv&startPeriod={start}")
    if not txt or not txt.startswith("FREQ"):
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(txt)):
        v = r.get("OBS_VALUE")
        if v not in (None, "", "NaN"):
            out[r["TIME_PERIOD"]] = round(float(v), 3)
    return out


def fred(series_id):
    """FRED public CSV (no key) -> {date: value}"""
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    out = {}
    if not txt or "," not in txt.splitlines()[0]:
        return out
    for r in list(csv.reader(io.StringIO(txt)))[1:]:
        try:
            out[r[0]] = round(float(r[1]), 4)
        except (ValueError, IndexError):
            pass
    return out


def oecd_cli(areas, start="2000-01"):
    """OECD composite leading indicators, amplitude adjusted. {area: {YYYY-MM: value}}"""
    url = ("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,/"
           f"{'+'.join(areas)}.M.LI...AA...H?startPeriod={start}&format=csv")
    txt = get(url, timeout=90)
    out = defaultdict(dict)
    if not txt or "REF_AREA" not in txt[:400]:
        return out
    for r in csv.DictReader(io.StringIO(txt)):
        if r.get("OBS_VALUE"):
            out[r["REF_AREA"]][r["TIME_PERIOD"]] = round(float(r["OBS_VALUE"]), 3)
    return out


# ---------- markets ----------
def yahoo(symbol, rng="2y"):
    """Daily closes from Yahoo's chart endpoint. {"dates": [...], "close": [...], "price": x, "time": epoch}"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?range={rng}&interval=1d")
    txt = get(url, ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", tries=3, timeout=30)
    try:
        res = json.loads(txt)["chart"]["result"][0]
        ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
        dates, close = [], []
        for t, c in zip(ts, cl):
            if c is not None:
                dates.append(time.strftime("%Y-%m-%d", time.gmtime(t)))
                close.append(round(c, 4))
        meta = res["meta"]
        if not close:
            return None
        return {"dates": dates, "close": close, "price": meta.get("regularMarketPrice", close[-1]),
                "time": meta.get("regularMarketTime"), "currency": meta.get("currency")}
    except Exception as e:  # noqa: BLE001
        if txt:
            _log("Yahoo", False, f"{symbol}: {e}")
        return None


def cse_aspi():
    """Colombo Stock Exchange All Share Price Index (latest value only)."""
    txt = get("https://www.cse.lk/api/aspiData", data=b"", ua="Mozilla/5.0", tries=2)
    try:
        d = json.loads(txt)
        return {"price": d["value"], "change_pct": round(d["percentage"], 3), "time": int(d["timestamp"] / 1000)}
    except Exception as e:  # noqa: BLE001
        if txt:
            _log("CSE", False, str(e))
        return None


def fx_latest():
    """Units of each currency per USD. ECB reference rates (Frankfurter) + open.er-api for LKR."""
    rates, date = {}, None
    txt = get("https://api.frankfurter.dev/v1/latest?base=USD")
    try:
        d = json.loads(txt)
        rates.update(d["rates"])
        date = d["date"]
    except Exception:  # noqa: BLE001
        pass
    txt = get("https://open.er-api.com/v6/latest/USD")
    try:
        d = json.loads(txt)
        for k, v in d["rates"].items():
            rates.setdefault(k, v)
        date = date or time.strftime("%Y-%m-%d", time.gmtime(d["time_last_update_unix"]))
    except Exception:  # noqa: BLE001
        pass
    return rates, date


def fx_history(days_back=400):
    """ECB rates per USD over ~1 year, for currency trend. {ccy: {date: rate}}"""
    start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days_back * 86400))
    txt = get(f"https://api.frankfurter.dev/v1/{start}..?base=USD")
    out = defaultdict(dict)
    try:
        for d, rs in json.loads(txt)["rates"].items():
            for k, v in rs.items():
                out[k][d] = v
    except Exception:  # noqa: BLE001
        pass
    return out
