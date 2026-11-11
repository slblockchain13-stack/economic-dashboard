# Economic Machine Monitor: live

A live dashboard of the business cycles of 13 major economies plus the world as a whole. It covers cycle phases, OECD leading indicators, long-term debt cycles, markets, news and rule-based investment screens. It updates itself every hour.

**How it works:** a Python bot (`bot/update.py`) runs on GitHub Actions every hour. It pulls free public data (IMF, World Bank, BIS, OECD, FRED, Yahoo Finance, the Colombo Stock Exchange, ECB FX rates and Google News), applies the rules in `bot/analyze.py`, writes `docs/data/data.json` and republishes the site on GitHub Pages. The page (`docs/`) is plain HTML/JS. It re-checks the data file every 2 minutes and shows a notice when new data lands.

No server, no database, no API keys, no cost.

## Put it online (one time, about 10 minutes)

1. Create a free account at github.com if you don't have one.
2. Create a **new public repository**, e.g. `economic-dashboard` (GitHub Pages is free for public repos).
3. Push this folder to it:
   ```bash
   cd live
   git remote add origin https://github.com/<your-username>/economic-dashboard.git
   git push -u origin main
   ```
4. In the repository on GitHub, open **Settings → Pages**. Under **Build and deployment → Source**, choose **GitHub Actions**.
5. Open the **Actions** tab, then **Update dashboard → Run workflow** (tick "full refresh"). After about 4 minutes the site is live at
   `https://<your-username>.github.io/economic-dashboard/`.

From then on it runs every hour by itself. Share that link with anyone. Links to a country work too, e.g. `…/#country/LK`.

## Run it on your own computer

```bash
cd live
python3 bot/update.py            # refresh the data (add --full to force the slow economic data)
python3 -m http.server 8000 --directory docs
# open http://localhost:8000
```
Python 3.9+ only, no packages to install. `python3 -m unittest discover -s tests` runs the rule tests.

## Things you may want to edit

| What | Where |
|---|---|
| Add or remove a country | `bot/countries.py` → `COUNTRIES` (one line each) |
| Sri Lanka policy rate (no free feed) | `bot/countries.py` → `LK_POLICY` (add the new year-end value when CBSL moves) |
| Cycle, debt and screen rules | `bot/analyze.py` (tested in `tests/test_rules.py`) |
| News search terms and tone words | `bot/news.py` |
| Update frequency | `.github/workflows/update.yml` → `cron` |

## If something breaks

- Every source is fetched separately. If one fails, the last good values are kept and a warning appears under **How it works → Data health**.
- If the whole run fails validation, the data file is not overwritten, so the site keeps showing the last good data. The header dot turns amber ("Delayed") when the data is more than 3 hours old.
- GitHub pauses scheduled workflows in repos with no commits for 60 days. The bot commits a data snapshot on the 1st of each month to prevent this.

*Educational tool. The signals are mechanical rules over public data, not investment advice.*
