"""INF-P5 rules on synthetic files: preset lint (missing / unknown inputs, long strings, skip-date horizon), journal
parsing (setup-day lines get their event_id), and the host-vs-container comparator. The live runs are
python -m corb test all / ops ... / jobs ..."""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import infratest as it  # noqa: E402
from corb import ops  # noqa: E402

EA = """input double InpRiskPct = 0.5;
input string InpSkipDates = "";
sinput int    InpMagicBase = 26110310;
"""


class PresetLint(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.repo, "Include"))
        os.makedirs(os.path.join(self.repo, "Presets", "EXP"))
        with open(os.path.join(self.repo, "CycleORB.mq5"), "w", encoding="utf-8") as f:
            f.write(EA)
        self.saved, it.REPO = it.REPO, self.repo

    def tearDown(self):
        it.REPO = self.saved
        shutil.rmtree(self.repo)

    def preset(self, name, **inputs):
        with open(os.path.join(self.repo, "Presets", name), "w", encoding="utf-8") as f:
            f.write("".join(f"{k}={v}||0||0||0||N\n" for k, v in inputs.items()))

    def lint(self):
        return it.preset_lint(today=date(2026, 11, 7))

    def test_complete_preset_passes(self):
        self.preset("ok.set", InpRiskPct="0.5", InpSkipDates="20270610", InpMagicBase="1")
        self.assertEqual(self.lint()["problems"], [])

    def test_missing_input_is_a_problem(self):
        self.preset("miss.set", InpRiskPct="0.5", InpSkipDates="")
        self.assertTrue(any("missing input InpMagicBase" in p for p in self.lint()["problems"]))

    def test_unknown_input_is_a_problem(self):
        self.preset("extra.set", InpRiskPct="0.5", InpSkipDates="", InpMagicBase="1", InpOld="1")
        self.assertTrue(any("unknown input InpOld" in p for p in self.lint()["problems"]))

    def test_long_string_is_a_problem(self):
        dates = ",".join(["270610"] * 40)   # 279 characters
        self.preset("long.set", InpRiskPct="0.5", InpSkipDates=dates, InpMagicBase="1")
        self.assertTrue(any("characters" in p for p in self.lint()["problems"]))

    def test_unparseable_skip_date_is_a_problem(self):
        self.preset("bad.set", InpRiskPct="0.5", InpSkipDates="2026x101", InpMagicBase="1")
        self.assertTrue(any("does not parse" in p for p in self.lint()["problems"]))

    def test_export_preset_needs_90_days_of_skip_dates(self):
        self.preset("EXP/short.set", InpRiskPct="0.5", InpSkipDates="261218", InpMagicBase="1")
        self.preset("research.set", InpRiskPct="0.5", InpSkipDates="261218", InpMagicBase="1")
        r = self.lint()
        self.assertEqual([p for p in r["problems"] if "90 days" in p], ["Presets/EXP/short.set: skip dates end "
                                                                         "2026-12-18 (< 90 days ahead)"])
        self.assertTrue(any("research.set" in w for w in r["warnings"]))


JOURNAL = "\n".join([
    "AB\t0\t10:00:00.000\tCore 1\tDE40,M5: testing of Experts\\CycleORB.ex5 from 2025.07.01 00:00 to 2026.10.31 "
    "00:00 started with inputs:",
    "CD\t0\t10:00:00.000\tCore 1\t  InpMagicBase=26110310",
    "EF\t0\t10:00:01.000\tCore 1\t2025.07.01 00:00:00   [CycleORB] Init OK v1.11 DE40",
    "GH\t0\t10:00:02.000\tCore 1\t2025.07.08 09:15:00   [CycleORB] RANGE LON 2025.07.08 hi=24000 lo=23900",
    "IJ\t0\t10:00:03.000\tCore 1\t2025.07.08 15:45:00   [CycleORB] PLACE NY 2025.07.08 buy stop 24100",
    "KL\t0\t10:00:04.000\tCore 1\t2025.07.09 08:00:00   unrelated tester line",
])


class JournalParse(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(JOURNAL)

    def tearDown(self):
        os.remove(self.path)

    def test_setup_day_lines_get_event_id_from_magic_and_session(self):
        rows = list(ops.parse_journal(self.path))
        by_kind = {r[6]: r for r in rows if r[6]}
        self.assertEqual(by_kind["RANGE"][5], "26110311-20250708")   # LON = magic + 1
        self.assertEqual(by_kind["PLACE"][5], "26110312-20250708")   # NY = magic + 2
        self.assertEqual(by_kind["PLACE"][2:5], ("DE40", "1.11", "2025-07-08 15:45:00"))

    def test_other_lines_are_kept_without_event_id(self):
        rows = list(ops.parse_journal(self.path))
        self.assertEqual(len(rows), 6)
        self.assertIsNone(rows[-1][5])
        self.assertEqual(rows[-1][7], "unrelated tester line")


class Comparator(unittest.TestCase):
    def test_float_noise_is_equal_but_real_differences_are_not(self):
        self.assertTrue(it._same({"E": 0.254, "n": [95, 1.0]}, {"E": 0.254 + 1e-13, "n": [95, 1.0]}))
        self.assertFalse(it._same({"E": 0.254}, {"E": 0.255}))
        self.assertFalse(it._same({"E": 0.254}, {"E": None}))
        self.assertFalse(it._same([1, 2], [1, 2, 3]))

    def test_a_run_that_wrote_no_scorecard_has_no_card(self):
        saved, it.VAR = it.VAR, tempfile.mkdtemp()
        try:
            self.assertEqual(it._card("INF-X"), {})
        finally:
            shutil.rmtree(it.VAR)
            it.VAR = saved


class ReasonCodes(unittest.TestCase):
    def test_codes_are_unique_and_every_verdict_is_known(self):
        codes = [c[0] for c in ops.REASON_CODES]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue({c[2] for c in ops.REASON_CODES} <= {"fire", "skip", "block"})


if __name__ == "__main__":
    unittest.main()
