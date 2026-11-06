"""Golden vectors: Unified Edge Framework §10 (FX-01..16) and edge_framework.md Appendix B (CO-FX-01..04).

Run from tools/:  python -m unittest discover -s tests -v
CO-FX tests need the parsed baseline runs in ../tester/aos/runs (corb_parse.py) and are skipped otherwise.
"""
import csv
import json
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import corb_metrics as cm  # noqa: E402

RUNS = os.path.normpath(os.path.join(HERE, "..", "..", "tester", "aos", "runs"))
FRAC = 1e-4   # ±0.0001 on fractions
PP = 1e-4     # ±0.01 pp on margins (as fractions)


class GenericFixtures(unittest.TestCase):
    def test_fx01_bwr_table(self):
        for r, want in ((0.5, 0.666667), (0.75, 0.571429), (1.0, 0.5), (1.25, 0.444444), (1.5, 0.4),
                        (2.0, 0.333333), (3.0, 0.25), (4.0, 0.2), (5.0, 0.166667)):
            self.assertAlmostEqual(cm.bwr(r), want, delta=FRAC)

    def test_fx02_decomposition(self):
        wr, r = 0.57, 1.20
        self.assertAlmostEqual(cm.bwr(r), 0.454545, delta=FRAC)
        self.assertAlmostEqual(wr - cm.bwr(r), 0.115455, delta=PP)
        self.assertAlmostEqual(cm.e_n(wr, r), 0.254, delta=FRAC)
        self.assertAlmostEqual((r + 1) * (wr - cm.bwr(r)), cm.e_n(wr, r), delta=1e-12)

    def test_fx03_equal_margin_unequal_edge(self):
        for r, wr, want in ((1, 0.55, 0.10), (2, 0.383333, 0.15), (4, 0.25, 0.25)):
            self.assertAlmostEqual(wr - cm.bwr(r), 0.05, delta=PP)
            self.assertAlmostEqual(cm.e_n(wr, r), want, delta=FRAC)

    def test_fx04_frontier_trap(self):
        self.assertAlmostEqual(cm.bwr(0.15), 0.869565, delta=FRAC)
        self.assertAlmostEqual(0.90 - cm.bwr(0.15), 0.0304, delta=PP)
        self.assertAlmostEqual(cm.e_n(0.90, 0.15), 0.035, delta=FRAC)

    def test_fx05_cost_to_leak(self):
        self.assertAlmostEqual(cm.leak(0.11, 1.2), 0.05, delta=FRAC)

    def test_fx06_production_gate_fragile(self):
        bm = 0.55 - cm.bwr(1.0)
        ef = bm - cm.leak(0.06, 1.0)
        m = cm.uncertainty_margin(0.55, 500)
        self.assertAlmostEqual(bm, 0.05, delta=PP)
        self.assertAlmostEqual(ef, 0.02, delta=PP)
        self.assertAlmostEqual(m, 0.0436, delta=PP)
        self.assertTrue(0 < ef <= m)

    def test_fx07_wilson(self):
        lo, hi = cm.wilson_interval(0.55, 100)
        self.assertAlmostEqual(lo, 0.4524, delta=FRAC)
        self.assertAlmostEqual(hi, 0.6439, delta=FRAC)
        self.assertAlmostEqual((lo + hi) / 2, 0.5482, delta=FRAC)
        self.assertAlmostEqual(cm.wilson_half(0.55, 100), 0.0957, delta=FRAC)

    def test_fx08_sample_tiers(self):
        self.assertEqual(cm.sample_size(0.05), 385)
        self.assertEqual(cm.sample_size(0.03), 1068)

    def test_fx09_geometric(self):
        self.assertAlmostEqual(cm.geometric_g([0.5, -0.5]), -0.133975, delta=FRAC)

    def test_fx10_vol_drag(self):
        self.assertAlmostEqual(cm.vol_drag(0.10, 0.10), 0.095, delta=FRAC)
        self.assertAlmostEqual(cm.vol_drag(0.10, 0.30), 0.055, delta=FRAC)

    def test_fx11_recovery(self):
        self.assertAlmostEqual(cm.recovery_return(0.20), 0.25, delta=FRAC)
        self.assertAlmostEqual(cm.recovery_return(0.50), 1.00, delta=FRAC)

    def test_fx12_kelly(self):
        f = cm.kelly_binary(0.55, 1.5)
        self.assertAlmostEqual(f, 0.25, delta=FRAC)
        self.assertAlmostEqual(f / 2, 0.125, delta=FRAC)
        self.assertAlmostEqual(f / 4, 0.0625, delta=FRAC)

    def test_fx13_drawdown(self):
        self.assertAlmostEqual(cm.max_drawdown([0.10, -0.05, -0.10, 0.20]), 0.145, delta=FRAC)

    def test_fx14_basket(self):
        self.assertAlmostEqual(cm.aggregate_legs([150, -80, 40], 10, 300), 0.3333, delta=FRAC)

    def test_fx15_fmi(self):
        self.assertAlmostEqual(cm.fmi(0.50, 0.40), 0.25, delta=FRAC)

    def test_fx16_streak(self):
        e = cm.expected_streak(500, 0.55)
        self.assertAlmostEqual(e, 7.78, delta=0.01)
        self.assertEqual(math.ceil(1.5 * e), 12)


def _run(run_id):
    path = os.path.join(RUNS, run_id)
    if not os.path.isdir(path):
        raise unittest.SkipTest(f"run folder missing: {run_id} (run corb_parse.py on the baseline journal)")
    with open(os.path.join(path, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with open(os.path.join(path, "events.csv"), encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    return meta, events


class CycleOrbFixtures(unittest.TestCase):
    def test_cofx01_eurusd_ny(self):
        meta, ev = _run("vle1.08_EURUSD_26110200_2026-01-01_2026-10-31_500")
        c = cm.core([float(e["pnl_R"]) for e in ev])
        self.assertEqual(c["n"], 95)
        self.assertAlmostEqual(c["WR"], 0.484, delta=0.005)
        self.assertAlmostEqual(c["R"], 1.63, delta=0.005)
        self.assertAlmostEqual(c["BWR"], 0.380, delta=0.005)
        self.assertAlmostEqual(c["BM"], 0.104, delta=0.001)
        self.assertAlmostEqual(c["E"], 0.254, delta=0.005)

    def test_cofx02_us500_v109(self):
        meta, ev = _run("v1.09_SPX500_26110900_2025-07-01_2026-10-31_1000")
        c = cm.core([float(e["pnl_R"]) for e in ev])
        self.assertEqual(c["n"], 71)
        self.assertAlmostEqual(c["WR"], 0.563, delta=0.005)
        self.assertAlmostEqual(c["R"], 1.51, delta=0.005)
        self.assertAlmostEqual(c["BM"], 0.165, delta=0.001)
        self.assertEqual(meta["counters"].get("close_fail", 0), 0)
        self.assertEqual(meta["counters"].get("skip_skip_date", 0), 6)

    def test_cofx03_uk100_lot_min(self):
        m500, e500 = _run("v1.09_UK100_26110800_2025-12-17_2026-10-31_500")
        m1000, e1000 = _run("v1.09_UK100_26110800_2025-12-17_2026-10-31_1000")
        self.assertEqual((len(e500), len(e1000)), (54, 88))
        self.assertEqual(m500["sides_lot_min"], 82)
        self.assertEqual(m1000["sides_lot_min"], 0)

    def test_cofx04_de40_deposit_invariance(self):
        _, e500 = _run("v1.09_DE30_26110310_2025-07-01_2026-10-31_500")
        _, e1000 = _run("v1.09_DE30_26110310_2025-07-01_2026-10-31_1000")
        self.assertEqual([e["event_id"] for e in e500], [e["event_id"] for e in e1000])
        self.assertEqual([e["pnl_R"] for e in e500], [e["pnl_R"] for e in e1000])
        c = cm.core([float(e["pnl_R"]) for e in e1000])
        self.assertEqual(c["n"], 120)
        self.assertAlmostEqual(c["E"], 0.235, delta=0.005)


if __name__ == "__main__":
    unittest.main()
