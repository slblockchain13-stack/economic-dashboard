"""Parser tests for the gap-filling bots (bot/official.py). Each parser is fed a small sample in the
source's real format, including the awkward bits: missing cells, zero yields, changed layouts.
Run: python3 -m unittest discover -s tests"""
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))
import official as O  # noqa: E402
import sources as S  # noqa: E402
import update as U  # noqa: E402


def make_xlsx(rows):
    """rows: [{col: value}] -> bytes of a minimal .xlsx with shared strings, like the CBSL tables."""
    strings, cells = [], []
    for i, row in enumerate(rows, 1):
        cs = ""
        for col, v in row.items():
            if isinstance(v, str):
                strings.append(v)
                cs += f'<c r="{col}{i}" t="s"><v>{len(strings) - 1}</v></c>'
            else:
                cs += f'<c r="{col}{i}"><v>{v}</v></c>'
        cells.append(f'<row r="{i}">{cs}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>' + "".join(cells) + "</sheetData></worksheet>")
    return buf.getvalue()


class CbslRates(unittest.TestCase):
    rows = [{"B": "4.04 Interest Rates - Monthly"}, {"B": "End of Period", "D": "Overnight Policy Rate (OPR)"},
            {"D": -1, "E": -2, "F": -3},
            {"B": 2024, "C": "October", "E": 8.25, "F": 9.25, "I": 9.95},
            {"C": "November", "D": 8, "E": 7.5, "F": 8.5, "I": 9.08},
            {"B": 2026, "C": "May", "D": 8.75, "E": 8.25, "F": 9.25, "I": 9.83},
            {"C": "August ", "D": 8.75, "E": 8.25, "F": 9.25, "I": 9.89},
            {"C": "September", "D": 900, "E": 8.25, "F": 9.25},
            {"B": "(a) All interest rates are as at the end of period."}]

    def test_policy_rate_uses_opr_then_corridor_midpoint(self):
        pol, tb = O.parse_cbsl_rates(O.xlsx_rows(make_xlsx(self.rows)))
        self.assertEqual(pol["2024-10"], 8.75)      # before the OPR: middle of 8.25–9.25
        self.assertEqual(pol["2024-11"], 8.0)       # OPR itself
        self.assertEqual(pol["2026-08"], 8.75)      # month name with a trailing space, year carried down
        self.assertNotIn("2026-09", pol)            # 900% is nonsense: dropped, not shown
        self.assertEqual(tb["2026-05"], 9.83)

    def test_corridor_page(self):
        page = ('<html><head><meta content="Standing Deposit Facility Rate (SDFR) 1.00 Standing Lending Facility Rate (SLFR) 2.00"></head><body>'
                "<table><tr><td>Standing Deposit Facility Rate (SDFR)</td><td>8.25</td></tr>"
                "<tr><td>Standing Lending Facility Rate (SLFR)</td><td>9.25</td></tr></table></body></html>")
        self.assertEqual(O.parse_cbsl_corridor(page), 8.75)
        self.assertIsNone(O.parse_cbsl_corridor("<body>Policy rates have moved to a new page</body>"))
        self.assertIsNone(O.parse_cbsl_corridor("<body>Standing Deposit Facility Rate (SDFR) 9.25 Standing Lending Facility Rate (SLFR) 8.25</body>"))

    def test_bond_auctions_keep_only_ten_year_bonds_with_a_yield(self):
        d = lambda y, m, day: (O.datetime.date(y, m, day) - O.datetime.date(1899, 12, 30)).days  # noqa: E731
        rows = [{"B": "Series", "C": "Settlement Date", "D": "Maturity Date", "J": "Yield"},
                {"C": d(2025, 11, 17), "D": d(2030, 7, 1), "J": 9.56},      # 5 years: ignored
                {"C": d(2025, 11, 17), "D": d(2035, 6, 15), "J": 10.69},    # 10 years
                {"C": d(2025, 8, 15), "D": d(2035, 6, 15), "J": 10.97},
                {"C": d(2025, 8, 15), "D": d(2037, 7, 1), "J": 11.07},      # 12 years: averaged with the line above
                {"C": d(2025, 8, 15), "D": d(2034, 1, 1), "J": 0}]          # no bids accepted: ignored
        out = O.parse_cbsl_bonds(O.xlsx_rows(make_xlsx(rows)))
        self.assertEqual(out, {"2025-11": 10.69, "2025-08": 11.02})

    def test_inflation_chart(self):
        js = ("categories: ['Aug 26','Sep 26','Oct 26'], series: [{ name: 'NCPI (2021=100)', data: [8.1,8.1] },"
              " { name: 'CCPI (2021=100)', data: [8.0,8.0,8.3] }]")
        self.assertEqual(O.parse_cbsl_inflation(js), {"2026-08": 8.0, "2026-09": 8.0, "2026-10": 8.3})
        self.assertEqual(O.parse_cbsl_inflation("<html>maintenance</html>"), {})


class OtherSources(unittest.TestCase):
    def test_cse_history(self):
        txt = json.dumps([{"d": 1763433961000, "v": 23062.65, "pc": -0.69}, {"d": 1763543946000, "v": 23029.86}, {"d": 1763630316000, "v": 0}])
        self.assertEqual(O.parse_cse_history(txt), {"2025-11-18": 23062.65, "2025-11-19": 23029.86})

    def test_china(self):
        txt = json.dumps({"records": [{"dateString": "12 Nov 2026", "oneRate": "1.18", "tenRate": "1.5979"},
                                      {"dateString": "11 Nov 2026", "tenRate": "---"}, {"dateString": "10 Nov 2026", "tenRate": "99"}]})
        self.assertEqual(O.parse_china_yields(txt), {"2026-11-12": 1.5979})

    def test_brazil_picks_the_bond_nearest_ten_years(self):
        csv_text = ("Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha\n"
                    "Tesouro Selic;01/03/2036;10/11/2026;0,02;0,03\n"                                   # floating rate: ignored
                    "Tesouro Prefixado;01/01/2029;10/11/2026;13,10;13,20\n"                             # 2 years: too short
                    "Tesouro Prefixado com Juros Semestrais;01/01/2037;10/11/2026;15,01;15,10\n"        # 10.1 years
                    "Tesouro Prefixado;01/01/2033;10/11/2026;14,50;14,60\n"                             # 6.1 years: further from 10
                    "Tesouro Prefixado com Juros Semestrais;01/01/2037;09/11/2026;15,03;15,10\n"
                    "Tesouro Prefixado;01/01/2029;06/11/2026;13,10;13,20\n")                           # a day with only a short bond: no reading
        self.assertEqual(O.parse_brazil_yields(csv_text), {"2026-11": 15.02})

    def test_mas_table_carries_the_year_down(self):
        page = ("<table><tr><th>End of Period</th><th>10-Year Bond Yield</th></tr>"
                "<tr><td>2026</td><td>Sep</td><td>2.47</td></tr><tr><td></td><td>Oct</td><td>2.24</td></tr>"
                "<tr><td></td><td>Nov</td><td>-</td></tr></table>")
        self.assertEqual(O.parse_mas_table(page), {"2026-09": 2.47, "2026-10": 2.24})

    def test_eurostat_skips_missing_months(self):
        txt = json.dumps({"dimension": {"time": {"category": {"index": {"2026-08": 0, "2026-09": 1, "2026-10": 2}}}}, "value": {"0": 98.2, "2": 96.9}})
        self.assertEqual(O.parse_eurostat(txt), {"2026-08": 98.2, "2026-10": 96.9})

    def test_ecb_daily_to_monthly_average(self):
        txt = "KEY,TIME_PERIOD,OBS_VALUE\nYC.B,2026-11-09,3.27\nYC.B,2026-11-10,3.33\nYC.B,2026-10-30,3.10\nYC.B,2026-10-31,\n"
        self.assertEqual(O.parse_ecb_csv(txt), {"2026-11": 3.3, "2026-10": 3.1})

    def test_ilo_labour_share_keeps_only_the_economies_asked_for(self):
        txt = ("DATAFLOW,REF_AREA,FREQ,MEASURE,TIME_PERIOD,OBS_VALUE,OBS_STATUS\n"
               "ILO:X,LKA,A,LAP_2GDP_RT,2024,28.16,M\nILO:X,LKA,A,LAP_2GDP_RT,2025,28.146,M\n"
               "ILO:X,AFG,A,LAP_2GDP_RT,2025,40.7,I\nILO:X,USA,A,LAP_2GDP_RT,2025,,I\nILO:X,USA,A,LAP_2GDP_RT,2024,555,I\n")
        self.assertEqual(O.parse_ilo_share(txt, ["LKA", "USA"]), {"LKA": {2024: 28.16, 2025: 28.15}, "USA": {}})

    def test_eurostat_wage_share_is_compensation_over_gdp(self):
        txt = json.dumps({"id": ["freq", "unit", "na_item", "geo", "time"], "size": [1, 1, 2, 1, 2],
                          "dimension": {"freq": {"category": {"index": {"A": 0}}}, "unit": {"category": {"index": {"CP_MEUR": 0}}},
                                        "na_item": {"category": {"index": {"B1GQ": 0, "D1": 1}}}, "geo": {"category": {"index": {"EA21": 0}}},
                                        "time": {"category": {"index": {"2024": 0, "2025": 1}}}},
                          "value": {"0": 1000.0, "1": 2000.0, "2": 480.0}})       # GDP 2024, GDP 2025, pay 2024; pay 2025 missing
        self.assertEqual(O.parse_eurostat_share(txt), {2024: 48.0})

    def test_out_of_range_values_are_logged(self):
        n = len(S.LOG)
        self.assertEqual(O.sane({"a": 5.0, "b": 500.0, "c": None}, 0, 40, "test source"), {"a": 5.0})
        self.assertTrue(any(l["source"] == "test source" and not l["ok"] for l in S.LOG[n:]))


class Merging(unittest.TestCase):
    def test_short_history_feeds_accumulate_across_runs(self):
        new = {"series": {"y10": {2026: 1.6}}, "monthly": {"y10": {"2026-11": 1.6}, "rate": {"2026-11": 3.0}}, "sources": {"y10": "x"}}
        prev = {"series": {"y10": {"2026": 1.7}, "gdp": {"2025": 5.0}}, "monthly": {"y10": {"2026-10": 1.8, "2026-11": 1.5}, "rate": {"2020-01": 4.0}}, "sources": {}}
        out = U.merge_macro(new, prev)
        self.assertEqual(out["monthly"]["y10"], {"2026-10": 1.8, "2026-11": 1.6})   # old month kept, this month's value wins
        self.assertEqual(out["monthly"]["rate"], {"2026-11": 3.0})                  # full-history feeds are not merged
        self.assertEqual(out["series"]["y10"], {2026: 1.7})                         # annual average rebuilt from both months
        self.assertEqual(out["series"]["gdp"], {"2025": 5.0})                       # a series missing this run keeps its old values

    def test_colombo_gets_a_12_month_return_from_240_trading_days(self):
        q = {"dates": [f"d{i}" for i in range(240)], "close": [100 + i * 0.1 for i in range(240)]}
        self.assertNotIn("ret_12m", U.equity_stats(q))
        self.assertAlmostEqual(U.equity_stats(q, min_year=225)["ret_12m"], 23.9, places=1)


if __name__ == "__main__":
    unittest.main()
