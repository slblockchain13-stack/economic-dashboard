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
            for key in ("name", "series", "monthly", "now", "screen", "summary", "phases", "sources"):
                self.assertIn(key, e, f"{k} missing {key}")
            self.assertIn(e["now"]["phase"], list(A.PHASES) + [None])


if __name__ == "__main__":
    unittest.main()
