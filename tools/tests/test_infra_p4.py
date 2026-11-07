"""INF-P4 harness rules on synthetic data: decay guard, anchored folds, skip budget, evaluation verdicts (no skips,
payoff trap, missing controls, skip precision). The real-data runs are the recipes (python -m corb train ...)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import evaluate as ev  # noqa: E402

POL = ev.policy()


def frame(asset, months, n_per_month, role="asset"):
    rows = []
    rng = np.random.default_rng(1)
    for m in months:
        for i in range(n_per_month):
            rows.append(dict(asset=asset, role=role, month=m, local_day=f"{m.replace('-', '.')}.{i + 1:02d}",
                             y=float(rng.choice([1.5, -1.0, 0.8, -0.9])), event_id=f"{asset}-{m}-{i}"))
    return pd.DataFrame(rows)


def decisions(df, skip_ids=(), reason="SKIP_MODEL_LOSER"):
    sd = df.copy()
    sd["c_slip"], sd["f_op"] = 0.02, 0.01
    sd["verdict"] = np.where(sd.event_id.isin(skip_ids), "skip", "fire")
    sd["reason_code"] = np.where(sd.event_id.isin(skip_ids), reason, "ALLOW_DEFAULT")
    return sd


class DecayGuard(unittest.TestCase):
    def test_decay_only_training_is_refused(self):
        self.assertFalse(ev.decay_guard_ok(frame("DE40", ["2026-09", "2026-10"], 5)))

    def test_anchored_training_with_six_earlier_months_is_accepted(self):
        months = [f"2026-{m:02d}" for m in range(3, 11)]
        self.assertTrue(ev.decay_guard_ok(frame("DE40", months, 5)))


class Folds(unittest.TestCase):
    def test_anchored_and_never_trains_on_the_test_month(self):
        df = pd.concat([frame("A", [f"2026-{m:02d}" for m in range(1, 7)], 60),
                        frame("C", [f"2026-{m:02d}" for m in range(1, 7)], 10, role="control")]).reset_index(drop=True)
        fl = ev.folds(df, min_train=100)
        self.assertEqual([f[0] for f in fl], ["2026-03", "2026-04", "2026-05", "2026-06"])
        for m, tr, te in fl:
            self.assertTrue((df.loc[tr].month < m).all())
            self.assertTrue((df.loc[tr].role == "asset").all())       # controls are never trained on
            self.assertTrue((df.loc[te].month == m).all())


class Evaluate(unittest.TestCase):
    def setUp(self):
        months = [f"2026-{m:02d}" for m in range(1, 7)]
        self.df = pd.concat([frame("A", months, 40), frame("B", months, 40),
                             frame("CTRL", months, 10, role="control")]).reset_index(drop=True)
        self.df.loc[self.df.role == "control", "y"] = -1.0          # a negative control

    def test_no_skips_is_accepted_unchanged(self):
        r = ev.evaluate(decisions(self.df), POL)
        self.assertEqual(r["verdict"], "ACCEPT")
        self.assertEqual(r["pooled"]["withheld"], 0)

    def test_withholding_winners_fails_skip_precision(self):
        winners = self.df[(self.df.role == "asset") & (self.df.y > 1)].event_id.head(20)
        r = ev.evaluate(decisions(self.df, set(winners)), POL)
        self.assertNotEqual(r["verdict"], "ACCEPT")
        self.assertTrue(any(c["name"].startswith("skip precision") and not c["ok"] for c in r["checks"]))

    def test_missing_controls_fail_closed(self):
        r = ev.evaluate(decisions(self.df[self.df.role == "asset"]), POL)
        self.assertEqual(r["verdict"], "REJECT")


class SkipBudget(unittest.TestCase):
    def test_budget_caps_skips_at_15_percent_per_asset(self):
        df = frame("A", ["2026-01"], 40)
        sd = decisions(df, set(df.event_id.head(20)))
        sd["severity"] = np.arange(len(sd), dtype=float)
        out = ev.apply_budget(sd, POL)
        allowed = int(POL["skip_budget"]["max_share_per_asset"] * len(sd))           # 6 of 40
        self.assertEqual((out.verdict == "skip").sum(), allowed)
        self.assertEqual((out.reason_code == "ALLOW_BUDGET_CAP").sum(), 20 - allowed)
        kept = out[out.verdict == "skip"].severity
        self.assertTrue((kept >= sd.loc[sd.event_id.isin(df.event_id.head(20)), "severity"].nlargest(allowed).min()).all())


if __name__ == "__main__":
    unittest.main()
