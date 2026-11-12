"""News bot: pulls headlines from Google News RSS (Bing News RSS as fallback),
tags the topic and scores the tone with transparent keyword rules.
"""
import email.utils
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from sources import get, _log

TOPICS = {
    "Rates": ["central bank", "interest rate", "rate cut", "rate hike", "rates", "policy rate", "fed ", "federal reserve", "ecb", "boj", "rbi", "bank of england", "monetary", "repo rate", "cbsl", "pboc", "rba", "selic", "yield"],
    "Inflation": ["inflation", "cpi", "prices", "deflation", "cost of living"],
    "Growth": ["gdp", "growth", "recession", "economy grew", "contraction", "output", "pmi", "manufacturing", "industrial"],
    "Jobs": ["jobs", "unemployment", "payrolls", "labour", "labor", "wages", "hiring", "layoffs"],
    "Trade": ["tariff", "trade", "exports", "imports", "trade deal", "sanction", "supply chain"],
    "Markets": ["stocks", "shares", "index", "equities", "market", "nifty", "sensex", "nikkei", "dax", "ftse", "s&p", "dow", "bond"],
    "Currency": ["currency", "rupee", "yen", "yuan", "dollar", "euro", "sterling", "pound", "real ", "exchange rate", "forex"],
    "Fiscal": ["budget", "deficit", "debt", "imf", "bailout", "default", "tax", "spending", "fiscal", "credit rating", "downgrade", "upgrade"],
    "Energy": ["oil", "gas", "energy", "opec", "commodity", "gold", "copper"],
    "Geopolitics": ["war", "conflict", "election", "geopolit", "protest", "government collapse", "strike"],
}
POS = ["growth", "grew", "surge", "rally", "rallies", "beats", "beat ", "boost", "record high", "upgrade", "upgraded", "rebound", "recover",
       "strong", "stronger", "expand", "expansion", "eases", "easing", "cools", "cooling inflation", "improve", "optimism", "gains", "rises",
       "jumps", "soars", "investment", "inflows", "surplus", "deal", "stabil", "outperform", "hiring", "boom", "accelerat", "upbeat", "robust"]
NEG = ["recession", "slump", "falls", "fall ", "fell", "crisis", "default", "downgrade", "contraction", "contract", "layoffs", "tariff",
       "war", "sanction", "deficit", "weak", "weaker", "slowdown", "slows", "plunge", "plunges", "tumble", "drops", "drop ", "fears", "risk",
       "warns", "warning", "cut forecast", "uncertain", "turmoil", "sell-off", "selloff", "stagflation", "shrinks", "debt crisis",
       "outflows", "bankrupt", "strike", "inflation surge", "inflation rises", "hot inflation", "loses", "losses", "worst", "pressure"]


def classify(title):
    t = " " + title.lower() + " "
    topics = [k for k, words in TOPICS.items() if any(w in t for w in words)][:3] or ["General"]
    pos = sum(1 for w in POS if w in t)
    neg = sum(1 for w in NEG if w in t)
    tone = 0 if pos == neg else (1 if pos > neg else -1)
    return topics, tone


def _parse_rss(txt, source_hint):
    items = []
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate") or ""
        src = it.findtext("source") or ""
        if not src and " - " in title:
            title, src = title.rsplit(" - ", 1)
        elif src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        try:
            ts = int(email.utils.parsedate_to_datetime(pub).timestamp())
        except Exception:  # noqa: BLE001
            ts = int(time.time())
        if title and link:
            items.append({"title": title.strip(), "link": link, "source": src.strip() or source_hint, "ts": ts})
    return items


def fetch(query, max_items=14, max_age_days=7, key=None):
    q = urllib.parse.quote(query)
    txt = get(f"https://news.google.com/rss/search?q={q}+when:{max_age_days}d&hl=en-US&gl=US&ceid=US:en", ua="Mozilla/5.0", tries=2, timeout=30)
    items = _parse_rss(txt, "Google News") if txt else []
    if not items:
        txt = get(f"https://www.bing.com/news/search?q={q}&format=rss", ua="Mozilla/5.0", tries=2, timeout=30)
        items = _parse_rss(txt, "Bing News") if txt else []
    if not items:
        _log("News", False, f"no headlines for: {query}")
        return []
    cutoff = time.time() - max_age_days * 86400
    seen, out = set(), []
    for it in sorted(items, key=lambda x: -x["ts"]):
        dkey = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:60]
        if dkey in seen or it["ts"] < cutoff or (key and not relevant(it["title"], key)):
            continue
        it["topics"], it["tone"] = classify(it["title"])
        if key and it["topics"] == ["General"]:
            continue  # names the country but touches no economic topic
        seen.add(dkey)
        out.append(it)
        if len(out) >= max_items:
            break
    return out


# Words that must appear in a headline for it to count as news about that economy.
ALIASES = {
    "US": ["US", "U.S.", "America", "American", "Fed", "Federal Reserve", "Wall Street", "Treasury", "Treasuries", "Dow", "S&P", "Nasdaq", "Powell"],
    "CN": ["China", "Chinese", "Beijing", "yuan", "PBOC", "PBoC", "Shanghai", "Shenzhen"],
    "EA": ["euro", "eurozone", "euro zone", "euro area", "ECB", "Lagarde", "European", "Europe", "EU"],
    "DE": ["Germany", "German", "Bundesbank", "DAX", "Bund", "Berlin"],
    "JP": ["Japan", "Japanese", "BOJ", "BoJ", "yen", "Nikkei", "Tokyo", "Topix"],
    "IN": ["India", "Indian", "RBI", "rupee", "Sensex", "Nifty", "Mumbai"],
    "UK": ["UK", "U.K.", "Britain", "British", "BoE", "Bank of England", "sterling", "pound", "FTSE", "gilt", "gilts", "Reeves"],
    "FR": ["France", "French", "CAC", "Paris", "Banque de France"],
    "BR": ["Brazil", "Brazilian", "Ibovespa", "Selic", "Lula", "Banco Central"],
    "CA": ["Canada", "Canadian", "BoC", "Bank of Canada", "loonie", "TSX", "Ottawa"],
    "AU": ["Australia", "Australian", "RBA", "ASX", "Aussie"],
    "SG": ["Singapore", "MAS", "STI", "Straits Times Index"],
    "LK": ["Sri Lanka", "Sri Lankan", "Lanka", "CBSL", "Colombo", "CSE"],
}
SHORT_CASE = {"US", "EU", "MAS", "CSE", "STI", "UK", "BoC", "BoE", "BOJ", "BoJ", "RBI", "RBA", "ASX", "ECB", "TSX", "CAC", "DAX", "Fed"}


def relevant(title, key):
    words = ALIASES.get(key)
    if not words:
        return True
    for w in words:
        flags = 0 if w in SHORT_CASE else re.IGNORECASE
        if re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", title, flags):
            return True
    return False


def query_for(country):
    q = {"US": '(US OR "Federal Reserve" OR "Wall Street") (economy OR inflation OR rates OR stocks OR GDP)',
         "UK": '(UK OR Britain OR "Bank of England") (economy OR inflation OR rates OR gilts OR GDP)',
         "EA": '(eurozone OR "euro area" OR ECB) (economy OR inflation OR rates OR growth)',
         "LK": '"Sri Lanka" (economy OR CBSL OR rupee OR stocks OR IMF OR inflation)'}.get(country["key"])
    return q or f'"{country["name"]}" (economy OR inflation OR "central bank" OR stocks OR GDP OR rates)'


def tone_summary(items):
    if not items:
        return {"score": 0, "pos": 0, "neg": 0, "n": 0}
    pos = sum(1 for i in items if i["tone"] > 0)
    neg = sum(1 for i in items if i["tone"] < 0)
    return {"score": round((pos - neg) / len(items), 2), "pos": pos, "neg": neg, "n": len(items)}
