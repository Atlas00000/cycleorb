"""INF-P2 behaviour: live (VPS) ledgers -> monthly kind=live runs, ledger vs journal reconciliation (and its detection of
a misfiled ledger), measured swap, the collector's newest-version rule, content hashing, preset parsing.
Database steps run in the recipes (python -m corb ingest / dq / replay / import)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aos_tape  # noqa: E402
from corb import contract, dq, ingest, paths  # noqa: E402

OWNER = "v1.13_DE30_26110310_2025-07-01_2026-10-31_1000_P3G"
APPLE_V111 = "v1.11_Apple_26110600_2025-07-01_2026-10-31_1000_P1obs"
APPLE_V110 = "v1.10_Apple_26110600_2025-07-01_2026-10-31_1000_P1obs"


def run_dir(run_id):
    d = os.path.join(paths.RUNS, run_id)
    if not os.path.isdir(d):
        raise unittest.SkipTest(f"missing run {run_id}")
    return d


class LiveFixture(unittest.TestCase):
    """A tester ledger renamed as a VPS live ledger stands in for the forward test."""

    def test_live_ledgers_become_monthly_live_runs(self):
        src = run_dir(OWNER)
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for kind in ("decisions", "events", "shadow"):
                dst = os.path.join(tmp, f"CORB_26110310_DE30_live_{kind}.csv")
                shutil.copyfile(os.path.join(src, f"ledger_{kind}.csv"), dst)
                files.append(dst)
            with open(ingest.LIVE_CONFIG, encoding="utf-8") as f:
                config = json.load(f)
            with mock.patch.object(ingest, "LIVE", os.path.join(tmp, "live")):
                dirs = ingest.build_live(files, config)
            self.assertEqual(len(dirs), 16)                      # 2025-07 .. 2026-10
            keys, n_events = set(), 0
            for d in dirs:
                rows = contract.adapt(d, kind="live")
                for name, r in rows.items():
                    self.assertEqual(contract.validate(name, r), [], f"{os.path.basename(d)} {name}")
                self.assertEqual(rows["run"][0]["kind"], "live")
                self.assertTrue(rows["run"][0]["run_id"].endswith("_live"))
                keys.add(rows["run"][0]["run_key"])
                n_events += len(rows["event"])
            self.assertEqual(len(keys), 16)
            self.assertEqual(n_events, 120)


class Reconcile(unittest.TestCase):
    def test_owned_ledger_matches_journal(self):
        rec = dq.reconcile(run_dir(OWNER))
        self.assertEqual((rec["only_journal"], rec["only_ledger"], rec["field_diffs"]), (0, 0, {}))

    def test_misfiled_ledger_is_caught(self):
        """The v1.11 ledger next to the v1.10 journal: the 2025 holiday trade and the lot sizes after it differ."""
        with tempfile.TemporaryDirectory() as tmp:
            for f in ("meta.json", "events.csv"):
                shutil.copyfile(os.path.join(run_dir(APPLE_V110), f), os.path.join(tmp, f))
            for kind in ("decisions", "events", "shadow"):
                shutil.copyfile(os.path.join(run_dir(APPLE_V111), f"ledger_{kind}.csv"),
                                os.path.join(tmp, f"ledger_{kind}.csv"))
            rec = dq.reconcile(tmp)
        self.assertEqual(rec["only_journal"], 1)
        self.assertGreater(rec["field_diffs"].get("volume", 0), 0)


class SwapFromLedger(unittest.TestCase):
    def test_weekend_holds_have_measured_swap(self):
        legs = contract.adapt(run_dir(APPLE_V111))["leg"]
        measured = [l for l in legs if "swap=measured_ledger_residual" in l["cost_flags"]]
        self.assertEqual(len(measured), 3)
        self.assertTrue(all(l["cost_swap_ccy"] > 0 for l in measured))
        self.assertTrue(all(l["cost_swap_ccy"] == 0.0 for l in legs if "swap=zero_intraday" in l["cost_flags"]))


class CollectNewestOnly(unittest.TestCase):
    def test_reused_tag_goes_to_newest_version_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs, common = os.path.join(tmp, "runs"), os.path.join(tmp, "common")
            os.makedirs(common)
            for ver in ("1.12", "1.13"):
                d = os.path.join(runs, f"v{ver}_DE30_26110310_2025-07-01_2026-10-31_1000_P3G")
                os.makedirs(d)
                with open(os.path.join(d, "meta.json"), "w") as f:
                    json.dump(dict(magic_base=26110310, symbol="DE30", deposit=1000.0, version=ver,
                                   run_id=os.path.basename(d)), f)
            for kind in ("decisions", "events", "shadow"):
                with open(os.path.join(common, f"CORB_26110310_DE30_tester_1000_P3G_{kind}.csv"), "w") as f:
                    f.write("x\n")
            with mock.patch.object(aos_tape, "COMMON", common):
                aos_tape.collect(runs, "P3G")
            has = {v: os.path.exists(os.path.join(runs, f"v{v}_DE30_26110310_2025-07-01_2026-10-31_1000_P3G",
                                                  "ledger_events.csv")) for v in ("1.12", "1.13")}
            self.assertEqual(has, {"1.12": False, "1.13": True})


class Helpers(unittest.TestCase):
    def test_content_sha_is_stable(self):
        d = run_dir(OWNER)
        self.assertEqual(ingest.content_sha(d), ingest.content_sha(d))

    def test_parse_set_strips_optimiser_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "x.set")
            with open(p, "w") as f:
                f.write("; comment\nInpTargetR=2.5||1.0||0.5||3.0||N\nInpLonEnable=true\n")
            self.assertEqual(ingest.parse_set(p), {"InpTargetR": "2.5", "InpLonEnable": "true"})


if __name__ == "__main__":
    unittest.main()
