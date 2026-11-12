# Economic Machine Monitor: guide for Claude

A self-updating dashboard of business cycles for 13 economies plus the world, read through Ray Dalio's "economic machine" framework. Python standard library and plain JavaScript only: **no packages, no build step. Keep it that way.**

## Run, test, refresh
- `python3 run_local.py` serves `docs/` at http://localhost:8765, refreshes data on start and hourly, and answers the page's Ask AI requests through the local `claude` command.
- `python3 -m unittest discover -s tests` runs every test (rules and source parsers). Run it after any change to `bot/`.
- `python3 bot/update.py` refreshes data once (`--full` forces the slow economic data too, about 4 minutes).
- After changing `docs/*.js` or `docs/style.css`, reload the page and check the browser console for errors at desktop and phone width.

## Layout
| Path | What it is |
|---|---|
| `bot/countries.py` | The economies and their source codes. One row per country. |
| `bot/sources.py` | Fetchers for the international feeds (IMF, World Bank, BIS, OECD, FRED, Yahoo, FX). |
| `bot/official.py` | Fetchers for national sources (CBSL, CSE, CFETS, Tesouro, MAS, ECB, Eurostat). Each has a pure `parse_*` function, tested in `tests/test_official.py`, and a thin fetcher. |
| `bot/analyze.py` | Every rule: cycle phase, leading-indicator clock, long-term debt stage, levers, rules of thumb, investment screen, summaries, change detection. Pure functions. |
| `bot/news.py` | Headlines, topic tags, keyword tone. |
| `bot/update.py` | Orchestrator. Writes `docs/data/data.json`. |
| `docs/app.js` | Page shell, charts, World / Opportunities / News / How it works tabs. |
| `docs/cycles.js` | Countries, Compare and The Machine tabs, cycle charts, Ask AI panel. |
| `run_local.py` | Local server: static files, `/api/status`, `/api/ask`, `/api/refresh`. |
| `.github/workflows/update.yml` | Hourly run and deploy for the public GitHub Pages copy (not included in the local zip). |
| `tools/make_pack.py` | Builds the shareable zip. |

## Rules of the house
- **Nothing on the page is hand-written.** Phases, stages, levers and summaries are computed from data on every run. Do not add hand-entered assessments or numbers. A rule change goes in `bot/analyze.py` with a test.
- **Every source fails soft.** A fetcher returns `None` on failure and logs through `sources._log`; the previous value is kept and the page shows a warning under Data health. Never let one source stop a run.
- **Range-check what you scrape.** New parsers go through `official.sane()` so a changed page layout cannot put a nonsense number on screen.
- **Stale data is labelled.** A bond yield older than six months is charted but not used in signals. Follow that pattern for any new series.
- **The data file is the contract.** `tests/test_rules.py::PublishedFile` lists the fields the page needs. If you add a field the page relies on, add it there. If you add a series to `fetch_macro`, raise `MACRO_VERSION` in `bot/update.py` so the next run does a full refresh.
- **Colours and charts.** Phase colours are the `--ph-*` tokens in `style.css`, validated for colour-blind safety in light and dark. Text uses ink tokens, never a series colour. One y-axis per chart.
- **Ask AI runs Claude with all tools off** (`run_local.py`, `ask_claude`). Keep it that way: the brief contains third-party headlines.
- **Plain English on the page.** The readers are investors, not economists.

## Common requests
- Add a country: add a row to `COUNTRIES` (codes explained at the top of the file), add its aliases to `ALIASES` in `bot/news.py`, run `python3 bot/update.py --full`.
- Change when a phase or stage is called: edit `phase` or `lt_cycle` in `bot/analyze.py`, update the matching test, and update the wording in `PH_RULE` / `LTS` in `docs/cycles.js` so The Machine tab still tells the truth.
- A source broke: Data health names it. Fetch the page, compare it with the sample in `tests/test_official.py`, fix the parser, add the new shape to the test.
