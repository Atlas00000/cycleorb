"""aos_compare behaviour on synthetic runs: skip precision, payoff trap, engine-change detection."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aos_compare import compare  # noqa: E402

BASE_R = [1.5, -1.0, 2.0, -1.0, 0.6, -1.0, 1.2, -0.4, 2.0, -1.0, 0.8, -1.0]


def run(rs, ids=None, volume=1.0):
    ids = ids or range(len(rs))
    events = [dict(event_id=f"e{i}", pnl_R=r, c_slip_R=0.02, volume=volume, pnl_ccy_est=10 * r) for i, r in zip(ids, rs)]
    meta = dict(run_id="synthetic", symbol="TEST", deposit=1000.0)
    return meta, events


class CompareTests(unittest.TestCase):
    def test_identical_is_held(self):
        r = compare(*run(BASE_R), *run(BASE_R))
        self.assertEqual(r["fire_retention"], 1.0)
        self.assertEqual(r["withheld"]["n"], 0)
        self.assertEqual(r["verdict"], "ACCEPT")

    def test_withholding_losers_is_precise(self):
        keep = [i for i, x in enumerate(BASE_R) if not (x == -1.0 and i in (1, 5))]
        r = compare(*run(BASE_R), *run([BASE_R[i] for i in keep], keep))
        self.assertLess(r["withheld"]["mean_R"], 0)
        self.assertTrue(r["checks"]["skip_precision"])
        self.assertEqual(r["verdict"], "ACCEPT")

    def test_withholding_winners_is_rejected_by_precision(self):
        keep = [i for i, x in enumerate(BASE_R) if i not in (0, 2)]
        r = compare(*run(BASE_R), *run([BASE_R[i] for i in keep], keep))
        self.assertGreater(r["withheld"]["mean_R"], 0)
        self.assertFalse(r["checks"]["skip_precision"])
        self.assertNotEqual(r["verdict"], "ACCEPT")

    def test_payoff_trap(self):
        # withhold the big winners and most losers: WR 50 % -> 67 %, payoff 1.75 -> 0.5, E_N 0.375 -> 0
        base = [3.0, -1.0, 3.0, -1.0, 0.5, -1.0, 0.5, -1.0]
        keep = [4, 6, 7]
        r = compare(*run(base), *run([base[i] for i in keep], keep))
        self.assertGreater(r["health_variant"]["WR"], r["health_base"]["WR"])
        self.assertIn("payoff trap: WR up, E_N or EF down", r["rejects"])
        self.assertEqual(r["verdict"], "REJECT")

    def test_engine_change_detected(self):
        changed = BASE_R[:]
        changed[3] = 0.5
        r = compare(*run(BASE_R), *run(changed))
        self.assertEqual(r["outcome_changed"], 1)
        self.assertEqual(r["verdict"], "REJECT")

    def test_side_switch_is_not_engine_change(self):
        base_meta, base_ev = run(BASE_R)
        var_meta, var_ev = run(BASE_R)
        for e in base_ev:
            e["side"] = "buy"
        for e in var_ev:
            e["side"] = "buy"
        var_ev[0]["side"], var_ev[0]["pnl_R"] = "sell", -1.0
        r = compare(base_meta, base_ev, var_meta, var_ev)
        self.assertEqual(r["switched"]["n"], 1)
        self.assertEqual(r["outcome_changed"], 0)

    def test_policy_resize_from_ledger(self):
        base_meta, base_ev = run(BASE_R)
        var_meta, var_ev = run(BASE_R, volume=0.5)
        r = compare(base_meta, base_ev, var_meta, var_ev, var_mult={"e1": 0.5, "e3": 0.5})
        self.assertEqual(r["resized_down"]["n"], 2)       # only the policy-resized events
        self.assertEqual(r["volume_drift"], len(BASE_R) - 2)
        self.assertLess(r["resized_down"]["mean_R"], r["health_base"]["E"])

    def test_low_retention_warns(self):
        keep = [0, 2, 4, 6, 8]
        r = compare(*run(BASE_R), *run([BASE_R[i] for i in keep], keep))
        self.assertTrue(any("FREQUENCY_STALL" in w for w in r["warnings"]))


if __name__ == "__main__":
    unittest.main()
