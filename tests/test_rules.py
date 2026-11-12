"""Rule tests. Run: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))
import analyze as A  # noqa: E402
import news as N  # noqa: E402


class Phase(unittest.TestCase):
    def test_each_phase(self):
        self.assertEqual(A.phase(0.2, 1, 2, 2, 2, 0), "rec")            # growth under 0.5%
        self.assertEqual(A.phase(2, 2, 6, 2, 2, 0), "rec")              # 4 pts under trend
        self.assertEqual(A.phase(2, 2, 2, 2, 2, 0, unemp_chg=1.0), "rec")
        self.assertEqual(A.phase(3, 2, 2, 4, 2, 0.5), "tight")          # hiking with inflation over target
        self.assertEqual(A.phase(3, 2, 2, 4, 2, 0), "late")             # above trend, inflation high, not hiking
        self.assertEqual(A.phase(1.5, 2, 2, 2, 2, -0.5), "slow")        # under trend and cutting
        self.assertEqual(A.phase(3, 2, 2, 2, 2, 0), "early")            # above trend, inflation ok, accelerating
        self.assertEqual(A.phase(3, 3.5, 2, 2, 2, 0), "mid")            # above trend but decelerating
        self.assertIsNone(A.phase(None, 2, 2, 2, 2, 0))

    def test_recession_boundary(self):
        # 3.5 points under trend is the line (3 points mislabelled India's 2019 slowdown)
        self.assertNotEqual(A.phase(3.1, 6, 6.2, 4, 4, 0), "rec")
        self.assertEqual(A.phase(2.6, 6, 6.2, 4, 4, 0), "rec")

    def test_trend_needs_five_years(self):
        self.assertIsNone(A.trend({2020: 1, 2021: 2, 2022: 3, 2023: 4}, 2024))
        self.assertEqual(A.trend({y: 2.0 for y in range(2010, 2024)}, 2024), 2.0)

    def test_bench_before_targeting_uses_median(self):
        cpi = {y: float(y - 2000) for y in range(2000, 2016)}
        self.assertEqual(A.bench("IN", 4.0, cpi, 2012), 6.5)   # median of 2002..2011
        self.assertEqual(A.bench("IN", 4.0, cpi, 2017), 4.0)


class Clock(unittest.TestCase):
    def test_quadrants(self):
        mk = lambda vals: {f"2026-{i + 1:02d}": v for i, v in enumerate(vals)}  # noqa: E731
        self.assertEqual(A.cli_phase(mk([100, 100.2, 100.4, 100.6]))["phase"], "expansion")
        self.assertEqual(A.cli_phase(mk([101, 100.8, 100.6, 100.4]))["phase"], "downturn")
        self.assertEqual(A.cli_phase(mk([99.5, 99.4, 99.3, 99.2]))["phase"], "slowdown")
        self.assertEqual(A.cli_phase(mk([98, 98.5, 99, 99.5]))["phase"], "recovery")
        self.assertIsNone(A.cli_phase({"2026-01": 100}))


class LongTerm(unittest.TestCase):
    def test_low_debt_is_early(self):
        s, stage, _ = A.lt_score(40, 60, 40, 55, 3.0, 4, 8)
        self.assertEqual(stage, 0)

    def test_japan_like_is_very_late(self):
        s, stage, _ = A.lt_score(230, 160, 220, 150, 0.0, 1.5, 2)
        self.assertEqual(stage, 3)

    def test_default_pushes_emerging_economy_later(self):
        base = A.lt_score(97, 45, 75, 30, 5.0, 7.75, 9.3, emerging=True)[0]
        dflt = A.lt_score(97, 45, 75, 30, 5.0, 7.75, 9.3, emerging=True, default_year=2022, year=2026)[0]
        self.assertGreater(dflt, base)
        self.assertGreaterEqual(dflt, 0.5)

    def test_nothing_known(self):
        self.assertEqual(A.lt_score(None, None, None, None, None, None, None), (None, None, []))


class LongTermStage(unittest.TestCase):
    """The five-stage call must come from data alone and match textbook cases."""
    base = {"score": 0.2, "private": 80, "hh": 40, "dsr": 10, "total_chg_10y": 2, "private_chg_5y": 1, "min_rate": 3.0,
            "cpi_avg2": 2.5, "cpi_now": 2.5, "target": 2.0, "crisis": None, "year": 2026, "gdp_last2": [2, 2], "gov": 50, "gov_peak": None}

    def call(self, **kw):
        return A.lt_cycle({**self.base, **kw})

    def test_early(self):
        self.assertEqual(self.call()["stage"], 1)

    def test_bubble_when_debt_outgrows_income_or_households_strained(self):
        self.assertEqual(self.call(score=0.36, total_chg_10y=25)["stage"], 2)
        self.assertEqual(self.call(score=0.38, hh=114, dsr=20, min_rate=0.1)["stage"], 2)       # Australia-like
        self.assertEqual(self.call(score=0.57, min_rate=2.0)["stage"], 2)                       # heavy, but rates never hit zero

    def test_top_needs_the_zero_bound(self):
        self.assertEqual(self.call(score=0.6, min_rate=0.1)["stage"], 3)
        self.assertEqual(self.call(score=0.45, min_rate=0.0, total_chg_10y=-18, private_chg_5y=-20)["stage"], 3)  # euro-area-like

    def test_deflationary_deleveraging(self):
        r = self.call(score=0.64, private=204, dsr=19, cpi_avg2=0.5, total_chg_10y=70)                          # China-like
        self.assertEqual(r["stage"], 4)

    def test_crisis_then_normalisation(self):
        fresh = self.call(score=0.55, crisis=2022, year=2023, gdp_last2=[-7.3, -2.0], cpi_now=17, target=5, gov=110, gov_peak=116)
        self.assertEqual(fresh["stage"], 4)
        healed = self.call(score=0.55, crisis=2022, gdp_last2=[5, 5], cpi_now=5.3, target=5, gov=97, gov_peak=116)  # Sri Lanka 2026
        self.assertEqual(healed["stage"], 5)

    def test_position_runs_left_to_right(self):
        ps = [self.call()["pos"], self.call(score=0.4, total_chg_10y=25)["pos"], self.call(score=0.7, min_rate=0)["pos"],
              self.call(score=0.64, private=204, cpi_avg2=0.5)["pos"],
              self.call(score=0.55, crisis=2022, gdp_last2=[5, 5], cpi_now=5, target=5, gov=97, gov_peak=116)["pos"]]
        self.assertEqual(ps, sorted(ps))
        self.assertIsNone(A.lt_cycle({"score": None}))

    def test_crisis_detected_from_data(self):
        gdp, cpi = {2021: 4.2, 2022: -7.3, 2023: -2.0}, {2021: 6, 2022: 46, 2023: 17}
        self.assertEqual(A.crisis_year(gdp, cpi, 2026), 2022)
        self.assertIsNone(A.crisis_year({2020: -9.0}, {2020: 1.0}, 2026))      # a pandemic slump is not a debt crisis
        self.assertIsNone(A.crisis_year(gdp, cpi, 2040))                       # outside the window

    def test_asset_backed_debt_scores_private_only(self):
        s, _, why = A.lt_score(None, 168, None, 150, None, None, None)
        self.assertLess(s, 0.5)
        self.assertTrue(any("Private debt" in w for w in why))

    def test_evidence_reads_the_series(self):
        s = {"rate": {2007: 5.0, 2008: 0.1, 2015: 0.4, 2019: 2.4, 2020: 0.1, 2025: 3.9}, "gov": {2007: 64, 2025: 124},
             "credit": {2007: 168, 2020: 165, 2025: 140}, "gdp": {}, "cpi": {}, "dsr": {2025: 13}}
        ev = A.lt_evidence(s, 2025, None, [[2022, "Fastest hikes"]])
        txt = " | ".join(e[1] for e in ev)
        self.assertIn("zero bound", txt)
        self.assertIn("up from 64% in 2007", txt)
        self.assertIn("Fastest hikes", txt)
        self.assertEqual([e[0] for e in ev], sorted(e[0] for e in ev))


class LeversAndRules(unittest.TestCase):
    def test_post_crisis_economy_pulls_three_levers_hard(self):
        r = A.levers({"pb": 2.3, "pb_3y": 0.6, "crisis": 2022, "year": 2026, "private_chg_5y": None, "rev": 15.9, "rev_5y": 8.3,
                      "real_rate": 2.5, "nominal": 9.3, "rate": 7.75, "rate_label": "policy rate"})
        self.assertEqual([l["level"] for l in r["levers"]], [3, 3, 3, 0])
        self.assertIn("above", r["verdict"])

    def test_loose_budget_and_negative_real_rate(self):
        r = A.levers({"pb": -4.9, "pb_3y": -4.9, "crisis": None, "year": 2026, "private_chg_5y": -2, "rev": 30, "rev_5y": 31.7,
                      "real_rate": -2.5, "nominal": 4, "rate": 5})
        self.assertEqual([l["level"] for l in r["levers"]], [0, 0, 0, 3])
        self.assertIn("below", r["verdict"])

    def test_missing_data_is_not_measured(self):
        r = A.levers({"year": 2026})
        self.assertEqual([l["level"] for l in r["levers"]], [None, 0, None, None])
        self.assertIsNone(r["verdict"])

    def test_rules_of_thumb(self):
        credit = {2020: 150.0, 2024: 141.0, 2025: 140.0}
        prod = {**{y: 1.0 for y in range(2006, 2021)}, **{y: 2.0 for y in range(2021, 2026)}}
        r = A.rules_of_thumb(credit, prod, 2025)
        self.assertEqual([x["st"] for x in r], ["ok", "na", "ok"])
        self.assertEqual(r[0]["bars"][1][1], -10.0)
        self.assertEqual(A.rules_of_thumb({2019: 47.0, 2018: 46.0}, {}, 2025)[0]["st"], "na")   # stale credit data is not judged
        self.assertEqual(A.rules_of_thumb({2025: 105.0, 2024: 102.0}, {}, 2025)[0]["st"], "no")

    def test_rule_two_reads_the_labour_income_share(self):
        share = {2019: 58.2, 2020: 59.1, 2024: 55.5, 2025: 56.4, 2026: 56.5}
        r = A.rules_of_thumb({}, {}, 2025, lshare=share)[1]
        self.assertEqual((r["st"], r["bars"]), ("no", [["Last year", 0.9], ["Last 5 years", -2.7]]))    # 2026 is a projection: not used
        self.assertIn("faster than productivity", r["msg"])
        self.assertEqual(A.rules_of_thumb({}, {}, 2025, lshare={2024: 55.0, 2025: 54.4})[1]["st"], "ok")
        steady = A.rules_of_thumb({}, {}, 2025, lshare={2024: 55.0, 2025: 55.2})[1]
        self.assertEqual(steady["st"], "ok")                                                           # within 0.2 pt counts as steady
        self.assertIn("steady", steady["msg"])
        self.assertEqual(A.rules_of_thumb({}, {}, 2025, lshare={2024: 55.0, 2025: 55.3})[1]["st"], "no")
        self.assertEqual(A.rules_of_thumb({}, {}, 2025, lshare={2019: 36.0, 2020: 38.0})[1]["st"], "na")   # stale data is not judged
        self.assertEqual(A.rules_of_thumb({}, {}, 2025)[1]["st"], "na")

    def test_phase_details_carry_the_inputs(self):
        s = {"gdp": {y: 2.0 for y in range(2000, 2021)}, "cpi": {y: 2.0 for y in range(2000, 2021)}, "rate": {2019: 2.0, 2020: 0.25}}
        s["gdp"][2020] = -3.0
        d = A.phase_details("US", s, 2.0, 2019, 2020)
        self.assertEqual(d[2020]["phase"], "rec")
        self.assertEqual(d[2020]["rate_chg"], -1.75)
        self.assertEqual(d[2020]["kind"], "target")


class Screen(unittest.TestCase):
    def test_recovery_with_cuts_is_favourable_for_equities(self):
        r = A.screen({"phase": "early", "cli_phase": "recovery", "rate_chg_12m": -1, "eq_ret_12m": 5, "eq_above_200d": True})
        self.assertEqual(r["equities"]["stance"], "Favourable")

    def test_tightening_in_downturn_is_cautious(self):
        r = A.screen({"phase": "tight", "cli_phase": "downturn", "rate_chg_12m": 1, "eq_above_200d": False, "eq_ret_12m": -5})
        self.assertEqual(r["equities"]["stance"], "Cautious")

    def test_external_risks_flagged(self):
        r = A.screen({"ca": -6, "reserves_months": 2, "cpi": 9, "target": 4})
        self.assertEqual(r["currency"]["stance"], "Cautious")
        self.assertEqual(len(r["risks"]), 3)

    def test_asset_backed_government_debt_is_not_a_risk(self):
        self.assertTrue(any("Government debt" in r for r in A.screen({"gov_debt": 166})["risks"]))
        self.assertFalse(any("Government debt" in r for r in A.screen({"gov_debt": 166, "asset_backed": True})["risks"]))

    def test_empty_metrics_do_not_crash(self):
        r = A.screen({})
        self.assertEqual(r["equities"]["stance"], "Neutral")
        self.assertEqual(r["score100"], 50)


class News(unittest.TestCase):
    def test_classify(self):
        topics, tone = N.classify("Central bank cuts interest rate as inflation cools")
        self.assertIn("Rates", topics)
        self.assertIn("Inflation", topics)
        self.assertEqual(tone, 1)
        self.assertEqual(N.classify("Economy slips into recession as exports slump")[1], -1)

    def test_relevance_filter(self):
        self.assertTrue(N.relevant("RBI holds repo rate steady", "IN"))
        self.assertFalse(N.relevant("Banned Pakistani cream still sold", "BR"))
        self.assertFalse(N.relevant("Business users trust the platform", "US"))  # 'us' inside words / lower case
        self.assertTrue(N.relevant("US jobs report beats forecasts", "US"))


class Diff(unittest.TestCase):
    def test_phase_and_rate_changes_reported(self):
        e = lambda ph, rate: {"economies": {"US": {"name": "United States", "cb": "Fed", "index_name": "S&P", "now": {"phase": ph, "rate": rate}}}}  # noqa: E731
        out = A.diff(e("mid", 4.0), e("late", 3.75), 1)
        kinds = sorted(c["kind"] for c in out)
        self.assertEqual(kinds, ["cycle", "rates"])
        self.assertIn("cut", next(c["text"] for c in out if c["kind"] == "rates"))
        self.assertEqual(A.diff(None, e("mid", 4.0), 1), [])

    def test_long_term_stage_change_reported(self):
        e = lambda st: {"economies": {"LK": {"name": "Sri Lanka", "cb": "CBSL", "index_name": "ASPI", "now": {"phase": "mid", "rate": 7.75, "lt": {"stage": st}}}}}  # noqa: E731
        out = A.diff(e(4), e(5), 1)
        self.assertEqual([c["kind"] for c in out], ["debt"])
        self.assertIn("Normalisation", out[0]["text"])


class PublishedFile(unittest.TestCase):
    """The data file the site reads must have every field the page uses."""

    def test_shape(self):
        f = ROOT / "docs" / "data" / "data.json"
        if not f.exists():
            self.skipTest("no data file yet")
        d = json.loads(f.read_text())
        for key in ("schema", "generated", "economies", "world", "markets", "news", "changes", "health", "year"):
            self.assertIn(key, d)
        self.assertGreaterEqual(len(d["economies"]), 10)
        for k, e in d["economies"].items():
            for key in ("name", "series", "monthly", "now", "screen", "summary", "phases", "phase_detail", "sources", "events", "notes"):
                self.assertIn(key, e, f"{k} missing {key}")
            self.assertIn(e["now"]["phase"], list(A.PHASES) + [None])
            for key in ("lt", "levers", "rules", "inputs", "metrics"):
                self.assertIn(key, e["now"], f"{k} missing now.{key}")
            lt = e["now"]["lt"]
            if lt:
                self.assertIn(lt["stage"], (1, 2, 3, 4, 5))
                self.assertTrue(0 <= lt["pos"] <= 1)
                for key in ("rule", "score", "why", "flags", "name"):
                    self.assertIn(key, lt, f"{k} missing lt.{key}")
            self.assertEqual(len(e["now"]["levers"]["levers"]), 4)
            self.assertEqual(len(e["now"]["rules"]), 3)
            mv = e.get("monthly_view")
            if mv:
                for key in ("phase", "inputs", "screen", "summary", "month", "annual_cpi", "monthly_cpi"):
                    self.assertIn(key, mv, f"{k} missing monthly_view.{key}")
                self.assertIn(mv["phase"], list(A.PHASES) + [None])
        self.assertGreaterEqual(sum(1 for e in d["economies"].values() if e["now"]["lt"]), 10)
        self.assertGreaterEqual(sum(1 for e in d["economies"].values() if e["now"]["rules"][1]["st"] != "na"), 10, "rule 2 should be measured for most economies")


if __name__ == "__main__":
    unittest.main()
