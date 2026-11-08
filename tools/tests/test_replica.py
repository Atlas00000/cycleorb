"""INF-P3-T07 replica mechanics on synthetic bars: OCO fills (first touch, gap, both in one bar), stop / target /
time exits (the sell side uses the ask), cycle risk money and ratchet, lot sizing, last trading day, clean clock
months. The parity with the tester is python -m corb replica parity."""
import os
import sys
import unittest
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import replica  # noqa: E402

PT = 0.01


def bars(rows, t0=1_750_000_000):
    """rows: (open, high, low, close) per minute, spread 0 unless given as a 5th value (points)."""
    a = np.array([r if len(r) == 5 else (*r, 0) for r in rows], dtype=float)
    return dict(time=np.arange(len(rows), dtype="int64") * 60 + t0, open=a[:, 0], high=a[:, 1], low=a[:, 2],
                close=a[:, 3], spread=a[:, 4])


def cycle(**kw):
    c = replica.Cycle({k: str(v) for k, v in kw.items()}, 1000.0)
    c.roll(1_750_000_000)
    return c


class Fills(unittest.TestCase):
    def test_first_side_touched_fills_at_its_level(self):
        m1 = bars([(100, 101, 99, 100), (100, 103, 100, 102.5)])
        self.assertEqual(replica._first_fill(m1, 0, {1: 102.0, -1: 98.0}, PT, 10 ** 12), (1, 1, 102.0))

    def test_gap_through_the_level_fills_at_the_open(self):
        m1 = bars([(100, 101, 99, 100), (97, 97.5, 96, 96.5)])
        self.assertEqual(replica._first_fill(m1, 0, {1: 102.0, -1: 98.0}, PT, 10 ** 12), (1, -1, 97.0))

    def test_buy_stop_triggers_on_the_ask(self):
        m1 = bars([(100, 101.95, 99.5, 101, 10)])   # bid high 101.95 + 0.10 spread = ask 102.05
        self.assertEqual(replica._first_fill(m1, 0, {1: 102.0}, PT, 10 ** 12)[1:], (1, 102.0))

    def test_both_sides_in_one_bar_take_the_one_nearer_the_open(self):
        m1 = bars([(101.5, 102.5, 97.5, 98)])
        self.assertEqual(replica._first_fill(m1, 0, {1: 102.0, -1: 98.0}, PT, 10 ** 12)[1], 1)

    def test_no_fill_after_entry_end(self):
        m1 = bars([(100, 100.5, 99.5, 100), (100, 103, 100, 102)])
        self.assertIsNone(replica._first_fill(m1, 0, {1: 102.0}, PT, int(m1["time"][1])))


class Exits(unittest.TestCase):
    def test_buy_target(self):
        m1 = bars([(102, 102.5, 101.8, 102.2), (102.2, 106.1, 102, 105)])
        k, px, how = replica._exit(m1, 0, 1, 100.0, 106.0, PT, 10 ** 12, cycle(), 1.0, 1.0, 102.0)
        self.assertEqual((k, px, how), (1, 106.0, "TP"))

    def test_buy_stop_gapped_fills_at_the_open(self):
        m1 = bars([(102, 102.5, 101.8, 102.2), (99, 99.5, 98, 98.5)])
        self.assertEqual(replica._exit(m1, 0, 1, 100.0, 106.0, PT, 10 ** 12, cycle(), 1.0, 1.0, 102.0)[1:], (99.0, "SL"))

    def test_sell_stop_loss_uses_the_ask(self):
        m1 = bars([(98, 98.2, 97.8, 98, 20), (98, 99.85, 97.9, 99.5, 20)])   # ask high 99.85 + 0.20 >= 100
        self.assertEqual(replica._exit(m1, 0, -1, 100.0, 94.0, PT, 10 ** 12, cycle(), 1.0, 1.0, 98.0)[2], "SL")

    def test_time_exit_at_the_first_bar_after_the_exit_time(self):
        m1 = bars([(102, 102.5, 101.8, 102.2), (102.2, 102.4, 102, 102.3), (102.3, 102.6, 102.1, 102.5)])
        k, px, how = replica._exit(m1, 0, 1, 100.0, 106.0, PT, int(m1["time"][2]), cycle(), 1.0, 1.0, 102.0)
        self.assertEqual((k, px, how), (2, 102.3, "TIME"))


class CycleAndSizing(unittest.TestCase):
    def test_risk_money_is_budget_over_divisor_capped(self):
        c = cycle(InpHardFlattenPct=38, InpRiskDivisor=8, InpMaxRiskPct=3)
        self.assertAlmostEqual(c.risk_money(), 30.0)          # (1000 - 620) / 8 = 47.5, cap 3 % = 30
        c.close(-200.0)
        self.assertAlmostEqual(c.risk_money(), 22.5)          # (800 - 620) / 8

    def test_ratchet_stops_the_month(self):
        c = cycle(InpRatchetArmPct=20, InpRatchetFloorPct=10, InpRatchetTrail=0.5)
        self.assertIsNone(c.update(250.0))                    # peak 25 %
        self.assertEqual(c.update(120.0), "STOP")             # 12 % <= max(10, 12.5)

    def test_new_month_resets_capital_to_the_balance(self):
        c = cycle()
        c.close(100.0)
        c.roll(int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp()))
        self.assertEqual((c.capital, c.realized), (1100.0, 0.0))

    def test_lots_floor_to_step_and_respect_the_minimum(self):
        self.assertEqual(replica._lots(30.0, 82.01, 1.16, "DE30", 50), 0.3)
        self.assertEqual(replica._lots(5.0, 3.0, 1.0, "Apple", 50), 1.66)
        self.assertEqual(replica._lots(2.5, 3.0, 1.0, "Apple", 50), 0.0)   # 0.83 lots < 1.0 minimum


class Calendar(unittest.TestCase):
    def test_last_trading_day_skips_the_weekend(self):
        fri = int(datetime(2026, 1, 30, 9, tzinfo=timezone.utc).timestamp())
        thu = int(datetime(2026, 1, 29, 9, tzinfo=timezone.utc).timestamp())
        self.assertTrue(replica._last_trading_day(fri))
        self.assertFalse(replica._last_trading_day(thu))

    def test_clean_months_drop_unknown_and_change_neighbours(self):
        off = {"2024-01": 0, "2024-02": 0, "2024-03": 0, "2024-04": 1, "2024-05": 1, "2024-06": 1, "2024-07": None,
               "2024-08": 1, "2024-09": 1, "2024-10": 1}
        self.assertEqual(replica.clean_months(off), {"2024-02", "2024-05", "2024-09"})


if __name__ == "__main__":
    unittest.main()
