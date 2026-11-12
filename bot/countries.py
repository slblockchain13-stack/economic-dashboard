"""The economies the dashboard follows. Add a row here to add a country.

key     short id used everywhere (URL hash, data file)
iso3    World Bank code; imf = IMF DataMapper code
bis     BIS code for policy rate + credit (euro members use XM = ECB)
oecd    OECD CLI area (None = not published)
y10     FRED 10-year government bond yield series (None = no free source)
index   Yahoo symbol for the main equity index ("CSE" = Colombo Stock Exchange API)
target  inflation benchmark (central bank target)
"""

COUNTRIES = [
    dict(key="US", name="United States", flag="🇺🇸", iso3="USA", imf="USA", bis="US", oecd="USA", y10="IRLTLT01USM156N", index="^GSPC", index_name="S&P 500", ccy="USD", target=2.0, cb="Federal Reserve", region="Americas"),
    dict(key="CN", name="China", flag="🇨🇳", iso3="CHN", imf="CHN", bis="CN", oecd="CHN", y10=None, index="000001.SS", index_name="Shanghai Composite", ccy="CNY", target=2.0, cb="People's Bank of China", region="Asia"),
    dict(key="EA", name="Euro area", flag="🇪🇺", iso3="EMU", imf="EURO", bis="XM", oecd=None, y10="IRLTLT01EZM156N", index="^STOXX50E", index_name="Euro Stoxx 50", ccy="EUR", target=2.0, cb="European Central Bank", region="Europe", aggregate=True),
    dict(key="DE", name="Germany", flag="🇩🇪", iso3="DEU", imf="DEU", bis="XM", oecd="DEU", y10="IRLTLT01DEM156N", index="^GDAXI", index_name="DAX", ccy="EUR", target=2.0, cb="European Central Bank", region="Europe", credit_bis="DE"),
    dict(key="JP", name="Japan", flag="🇯🇵", iso3="JPN", imf="JPN", bis="JP", oecd="JPN", y10="IRLTLT01JPM156N", index="^N225", index_name="Nikkei 225", ccy="JPY", target=2.0, cb="Bank of Japan", region="Asia"),
    dict(key="IN", name="India", flag="🇮🇳", iso3="IND", imf="IND", bis="IN", oecd="IND", y10="INDIRLTLT01STM", index="^BSESN", index_name="BSE Sensex", ccy="INR", target=4.0, cb="Reserve Bank of India", region="Asia"),
    dict(key="UK", name="United Kingdom", flag="🇬🇧", iso3="GBR", imf="GBR", bis="GB", oecd="GBR", y10="IRLTLT01GBM156N", index="^FTSE", index_name="FTSE 100", ccy="GBP", target=2.0, cb="Bank of England", region="Europe"),
    dict(key="FR", name="France", flag="🇫🇷", iso3="FRA", imf="FRA", bis="XM", oecd="FRA", y10="IRLTLT01FRM156N", index="^FCHI", index_name="CAC 40", ccy="EUR", target=2.0, cb="European Central Bank", region="Europe", credit_bis="FR"),
    dict(key="BR", name="Brazil", flag="🇧🇷", iso3="BRA", imf="BRA", bis="BR", oecd="BRA", y10=None, index="^BVSP", index_name="Ibovespa", ccy="BRL", target=3.0, cb="Banco Central do Brasil", region="Americas"),
    dict(key="CA", name="Canada", flag="🇨🇦", iso3="CAN", imf="CAN", bis="CA", oecd="CAN", y10="IRLTLT01CAM156N", index="^GSPTSE", index_name="S&P/TSX", ccy="CAD", target=2.0, cb="Bank of Canada", region="Americas"),
    dict(key="AU", name="Australia", flag="🇦🇺", iso3="AUS", imf="AUS", bis="AU", oecd="AUS", y10="IRLTLT01AUM156N", index="^AXJO", index_name="ASX 200", ccy="AUD", target=2.5, cb="Reserve Bank of Australia", region="Asia"),
    dict(key="SG", name="Singapore", flag="🇸🇬", iso3="SGP", imf="SGP", bis=None, oecd=None, y10=None, index="^STI", index_name="Straits Times", ccy="SGD", target=2.0, cb="Monetary Authority of Singapore", region="Asia", credit_bis="SG", asset_backed=True),
    dict(key="LK", name="Sri Lanka", flag="🇱🇰", iso3="LKA", imf="LKA", bis=None, oecd=None, y10=None, index="CSE", index_name="CSE All Share", ccy="LKR", target=5.0, cb="Central Bank of Sri Lanka", region="Asia"),
]

WORLD = dict(key="WORLD", name="World", iso3="WLD", imf="WEOWORLD", oecd="G20", index="ACWI", index_name="MSCI ACWI (ETF)")

# Central Bank of Sri Lanka policy rate, year end. No free API carries it.
# Midpoint of SDFR/SLFR to Nov 2024, then the Overnight Policy Rate (OPR).
# Entered by hand from CBSL announcements: verify and update here when CBSL moves.
LK_POLICY = {2015: 6.75, 2016: 7.75, 2017: 8.0, 2018: 8.5, 2019: 7.5, 2020: 5.0,
             2021: 5.5, 2022: 15.0, 2023: 9.5, 2024: 8.0, 2025: 7.75}

# asset_backed=True: government debt is issued to invest and is matched by larger assets, so it is left out of the debt-pressure score.
# Known sovereign defaults. The bot also detects a debt crisis from the data itself
# (output down 5%+ with inflation of 20%+), so this list is only a backstop.
DEFAULTS = {"LK": 2022}
EMERGING = {"CN", "IN", "BR", "LK"}

# Global market gauges (Yahoo symbol, label, unit hint)
GLOBAL_MARKETS = [
    ("^GSPC", "S&P 500", "idx"), ("ACWI", "World equities (ACWI)", "usd"), ("^VIX", "VIX fear gauge", "idx"),
    ("BZ=F", "Brent crude", "usd"), ("GC=F", "Gold", "usd"), ("DX-Y.NYB", "US dollar index", "idx"),
    ("^TNX", "US 10-year yield", "pct"), ("BTC-USD", "Bitcoin", "usd"), ("HG=F", "Copper", "usd"),
]

EVENTS = {  # shown on history charts
    "GLOBAL": [[2001, "Dot-com bust"], [2008, "Global financial crisis"], [2020, "COVID-19"], [2022, "Global inflation surge"]],
    "US": [[2008, "Fed to zero, QE"], [2022, "Fastest hikes since 1980s"]],
    "UK": [[2016, "Brexit vote"], [2022, "Gilt crisis"]],
    "IN": [[2013, "Taper tantrum"], [2016, "Demonetisation"]],
    "CN": [[2015, "Stock crash, devaluation"], [2021, "Evergrande defaults"]],
    "EA": [[2012, "Euro debt crisis"], [2015, "ECB starts QE"]],
    "DE": [[2022, "Energy shock"]], "FR": [[2012, "Euro debt crisis"]],
    "JP": [[2013, "Abenomics"], [2024, "BoJ ends negative rates"]],
    "BR": [[2015, "Deep recession"]], "CA": [[2015, "Oil price slump"]],
    "AU": [[2020, "First recession in ~30 years"]], "SG": [[2009, "Global crisis recession"]],
    "LK": [[2019, "Easter attacks"], [2022, "Sovereign default"], [2023, "IMF programme"]],
}
