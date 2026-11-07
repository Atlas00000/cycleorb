"""INF-P3 behaviour: registry = adapter features, completed-bar rule (shift 1) independent of the current bar,
future-shift cut, MT5 ATR, regime tagging helpers. Parity and the future-shift test on real data run in the recipe
(python -m corb features build)."""
import json
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import contract, featbuild, paths, regime  # noqa: E402

H = 3600


def bars(times, high, low, close):
    a = {"time": np.array(times, dtype="int64"), "open": np.array(close, float), "high": np.array(high, float),
         "low": np.array(low, float), "close": np.array(close, float), "spread": np.zeros(len(times))}
    return featbuild.Bars("TEST", {"H1": a, "D1": a})


class Registry(unittest.TestCase):
    def test_registry_names_the_adapter_features(self):
        with open(regime.REGISTRY, encoding="utf-8") as f:
            reg = json.load(f)
        self.assertEqual([x["name"] for x in reg["features"]], contract.FEATURES)
        self.assertEqual({x["name"] for x in reg["features"] if not x["offline"]},
                         {"spread_live_pt", "spread_avg_pt", "cost_pct"})


class CompletedBar(unittest.TestCase):
    def setUp(self):
        self.b = bars([7 * H, 8 * H, 9 * H], [1, 2, 3], [0, 1, 2], [0.5, 1.5, 2.5])

    def test_shift_one_on_and_after_the_hour(self):
        self.assertEqual(self.b.completed_before("H1", 9 * H), 1)          # decision at 09:00 -> the 08:00 bar
        self.assertEqual(self.b.completed_before("H1", 9 * H + 900), 1)    # 09:15 -> still the 08:00 bar

    def test_cut_does_not_move_shift_one(self):
        cut = self.b.cut(9 * H)                                           # the 09:00 bar deleted
        self.assertEqual(len(cut.tf["H1"]["time"]), 2)
        self.assertEqual(cut.completed_before("H1", 9 * H), 1)


class Atr(unittest.TestCase):
    def test_mt5_true_range_mean(self):
        b = bars([0, 86400, 2 * 86400], [10, 12, 11], [8, 9, 7], [9, 11, 8])
        # TR(1) = max(12, 9) - min(9, 9) = 3; TR(2) = max(11, 11) - min(7, 11) = 4
        self.assertAlmostEqual(featbuild._atr(b, "D1", 2, 2), 3.5)
        self.assertIsNone(featbuild._atr(b, "D1", 1, 2))


class RegimeHelpers(unittest.TestCase):
    def test_bands(self):
        self.assertEqual([regime._band(x, 20, 30) for x in (10, 20, 29.9, 30)], ["narrow", "mid", "mid", "wide"])
        self.assertEqual([regime._vol_tercile(x) for x in (10, 40, 90, None)], ["low", "mid", "high", None])


if __name__ == "__main__":
    unittest.main()
