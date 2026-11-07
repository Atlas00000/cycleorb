"""INF-P1 behaviour: contract validator, generated migration = contract, deterministic keys, adapter on real runs,
write-once landing, cross-deposit refusal. Database checks run in the recipe (python -m corb db check)."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aos_compare import compare  # noqa: E402
from corb import contract, landing, paths  # noqa: E402

FUNNEL = dict(run_key="0123456789abcdef", counter="close_fail", value=0)


class ValidatorTests(unittest.TestCase):
    def test_clean_row_passes(self):
        self.assertEqual(contract.validate("funnel", [FUNNEL]), [])

    def test_violations_are_caught(self):
        rows = [dict(FUNNEL, value=-1), dict(FUNNEL), dict(FUNNEL, counter=None, extra=1)]
        problems = sorted(p.split(" ")[0].rstrip(":") for _, _, p in contract.validate("funnel", rows))
        self.assertEqual(problems, ["bounds", "duplicate", "not", "required"])

    def test_enum_pattern_and_row_check(self):
        res = contract.resources()
        bad = contract.validate("run", [dict(run_key="XYZ", kind="nope")], res["run"]["schema"])
        self.assertTrue(any(f == "run_key" and p.startswith("pattern") for _, f, p in bad))
        self.assertTrue(any(f == "kind" and p.startswith("enum") for _, f, p in bad))
        feat = dict(run_key="k", event_id="1-20260101", feature="nr4", value_num=1.0, source="ea",
                    as_of_ts="2026-01-01T09:00:00Z", decision_ts="2026-01-01T08:59:00Z")
        self.assertTrue(any("as_of_ts <= decision_ts" in f for _, f, _ in contract.validate("feature", [feat])))


class MigrationMatchesContract(unittest.TestCase):
    def test_contract_ddl_snapshot_is_current(self):
        """A contract change must regenerate infra/db/contract_ddl.sql (and come with a migration)."""
        with open(os.path.join(paths.INFRA, "db", "contract_ddl.sql"), encoding="utf-8") as f:
            self.assertEqual(f.read().rstrip("\n"), contract.ddl())


class KeyTests(unittest.TestCase):
    META = dict(version="1.11", symbol="DE30", inputs={"InpTargetR": "2.5"}, window=["2025-07-01", "2026-10-31"],
                deposit=1000.0)

    def test_run_key_deterministic_and_deposit_sensitive(self):
        k = contract.run_key(self.META)
        self.assertEqual(k, contract.run_key(dict(self.META)))
        self.assertRegex(k, r"^[0-9a-f]{16}$")
        self.assertNotEqual(k, contract.run_key(dict(self.META, deposit=500.0)))


class AdapterOnRealRuns(unittest.TestCase):
    def adapt(self, run_id):
        d = os.path.join(paths.RUNS, run_id)
        if not os.path.isdir(d):
            self.skipTest(f"missing run {run_id}")
        return contract.adapt(d)

    def test_legs_rebuild_pnl_r(self):
        out = self.adapt("v1.11_DE30_26110310_2025-07-01_2026-10-31_1000")
        ev = {e["event_id"]: e for e in out["event"]}
        self.assertEqual(len(ev), 120)
        for leg in out["leg"]:
            sign = 1 if leg["direction"] == "long" else -1
            r = sign * (leg["exit_price"] - leg["entry_price"]) / ev[leg["event_id"]]["risk_px"]
            self.assertAlmostEqual(r, ev[leg["event_id"]]["pnl_R"], delta=1e-6)
            self.assertTrue(leg["entry_time"].endswith("Z"))
        for name, rows in out.items():
            self.assertEqual(contract.validate(name, rows), [], name)

    def test_aapl_weekend_holds_are_calendar_leaks(self):
        out = self.adapt("v1.11_Apple_26110600_2025-07-01_2026-10-31_1000")
        self.assertGreaterEqual(sum(e["calendar_leak"] for e in out["event"]), 3)


class LandingTests(unittest.TestCase):
    def test_write_once_duplicate_and_tamper(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src, root = os.path.join(tmp, "events.csv"), os.path.join(tmp, "landing")
            with open(src, "w") as f:
                f.write("a,b\n1,2\n")
            self.assertEqual(landing.land([src], "test", root), dict(landed=1, duplicates=0))
            self.assertEqual(landing.land([src], "test", root), dict(landed=0, duplicates=1))
            self.assertEqual(landing.verify(root), [])
            landed = os.path.join(root, landing._manifest(root)[0]["landed_path"])
            os.chmod(landed, stat.S_IWRITE | stat.S_IREAD)
            with open(landed, "a") as f:
                f.write("3,4\n")
            self.assertEqual([b["problem"] for b in landing.verify(root)], ["modified"])
            os.remove(landed)
            self.assertEqual([b["problem"] for b in landing.verify(root)], ["missing"])


class CrossDepositRefusal(unittest.TestCase):
    def test_compare_rejects_different_deposit(self):
        ev = [dict(event_id=f"e{i}", pnl_R=r, c_slip_R=0.02, volume=1.0, pnl_ccy_est=10 * r)
              for i, r in enumerate([1.5, -1.0, 2.0, -1.0, 0.6, -1.0])]
        r = compare(dict(run_id="a", symbol="UK100", deposit=1000.0), ev,
                    dict(run_id="b", symbol="UK100", deposit=500.0), ev)
        self.assertEqual(r["verdict"], "REJECT")
        self.assertTrue(any("deposit" in x for x in r["rejects"]))


if __name__ == "__main__":
    unittest.main()
