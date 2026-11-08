"""INF-P6 phase-prove rules: the T02 perturbation set (one step either side of every §8.2 threshold that applies,
seeds, embargo), the size-only sensitivity and the stability bar. The real-data run is python -m corb prove all."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import evaluate as ev  # noqa: E402
from corb import prove  # noqa: E402

POL = ev.policy()


class Perturbations(unittest.TestCase):
    def test_model_families_move_each_threshold_one_step_both_ways(self):
        v = {label: pol for label, pol, _, _ in prove._variants("gbt")}
        self.assertEqual(v["model_rule.pred_e_max -0.05"]["model_rule"]["pred_e_max"], -0.15)
        self.assertEqual(v["model_rule.pred_e_max +0.05"]["model_rule"]["pred_e_max"], -0.05)
        self.assertEqual(v["model_rule.p_loss_min +0.05"]["model_rule"]["p_loss_min"], 0.65)
        self.assertEqual(v["skip_budget.max_share_per_asset -0.05"]["skip_budget"]["max_share_per_asset"], 0.10)

    def test_unsure_band_follows_the_skip_threshold(self):
        v = {label: pol for label, pol, _, _ in prove._variants("ridge_logit")}
        self.assertEqual(v["model_rule.pred_e_max -0.05"]["model_rule"]["unsure_band"], [-0.15, 0.0])

    def test_cell_rule_steps_keep_integer_counts(self):
        v = {label: pol for label, pol, _, _ in prove._variants("cell_rule")}
        self.assertEqual(v["cell_rule.qualifying_n +5"]["cell_rule"]["qualifying_n"], 20)
        self.assertIsInstance(v["cell_rule.qualifying_n -5"]["cell_rule"]["qualifying_n"], int)

    def test_every_family_gets_seeds_and_embargo_and_the_policy_file_is_untouched(self):
        for fam in ("cell_rule", "ridge_logit", "gbt"):
            labels = [label for label, _, _, _ in prove._variants(fam)]
            self.assertEqual(len(labels), 10)
            self.assertIn("seed 20261107", labels)
            self.assertIn("embargo 10 days", labels)
        self.assertEqual(ev.policy(), POL)


class SizeOnly(unittest.TestCase):
    def test_skipped_days_count_at_half_size(self):
        rng = np.random.default_rng(3)
        y = rng.choice([1.5, -1.0], 60)
        sd = pd.DataFrame(dict(role="asset", local_day=[f"2026.03.{i % 28 + 1:02d}" for i in range(60)],
                               event_id=[f"e{i:02d}" for i in range(60)], y=y, c_slip=0.02, f_op=0.01,
                               verdict=["skip" if i < 6 else "fire" for i in range(60)]))
        r = prove.size_only(sd)
        a = sd.sort_values(["local_day", "event_id"])
        want = a.y.where(a.verdict == "fire", a.y * 0.5).mean()
        self.assertAlmostEqual(r["E"][1], want)
        self.assertAlmostEqual(r["E"][0], y.mean())


class StabilityBar(unittest.TestCase):
    def test_bar_is_eighty_percent(self):
        self.assertEqual(prove.STABLE_SHARE, 0.80)


if __name__ == "__main__":
    unittest.main()
