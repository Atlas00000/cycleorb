"""INF-P0 behaviour: run-id parsing, duplicate detection, tolerance checks, source-register statuses, path portability."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import baseline, inventory, paths, sources  # noqa: E402


class RunIdTests(unittest.TestCase):
    def test_tagged_run(self):
        r = inventory.parse_run_id("v1.11_DE30_26110310_2025-07-01_2026-10-31_1000_P1obs")
        self.assertEqual((r["version"], r["symbol"], r["magic_base"], r["deposit"], r["tag"]),
                         ("1.11", "DE30", 26110310, 1000.0, "P1obs"))

    def test_untagged_and_legacy_prefix(self):
        self.assertIsNone(inventory.parse_run_id("v1.11_SPX500_26110900_2025-07-01_2026-10-31_1000")["tag"])
        self.assertEqual(inventory.parse_run_id("vle1.08_UK100_26110800_2026-01-01_2026-10-31_500")["version"], "1.08")


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(inventory.classify("%REPO%/tester/aos/runs/x/events.csv"), "run_events")
        self.assertEqual(inventory.classify("%COMMON%/CycleORB/CORB_26110310_DE30_tester_1000_shadow.csv"),
                         "ledger_shadow")
        self.assertEqual(inventory.classify("%COMMON%/CycleORB/events.csv"), "calendar")
        self.assertEqual(inventory.classify("%TERMINAL%/Tester/logs/20261106.log"), "journal")
        self.assertIsNone(inventory.classify("%REPO%/tools/corb_bench.py"))


class InventoryOnRepoTests(unittest.TestCase):
    """Runs on the committed evidence: the v1.10 observe run and the v1.11 baseline carry identical DE40 events."""

    def test_same_events_group_found(self):
        inv = inventory.build(external=False)
        groups = [set(g["run_ids"]) for g in inv["duplicates"]["same_events"]]
        self.assertTrue(any({"v1.10_DE30_26110310_2025-07-01_2026-10-31_1000_P1obs",
                             "v1.11_DE30_26110310_2025-07-01_2026-10-31_1000"} <= g for g in groups))
        self.assertTrue(all(f["path"].startswith("%REPO%/") for f in inv["files"]))


class ToleranceTests(unittest.TestCase):
    def test_within_and_outside(self):
        self.assertTrue(baseline.check("x", 0.2630, 0.2679, baseline.FRAC)["ok"])
        self.assertFalse(baseline.check("x", 0.2630, 0.2690, baseline.FRAC)["ok"])
        self.assertFalse(baseline.check("zone", "Robust", "Fragile", 0)["ok"])
        self.assertFalse(baseline.check("x", 0.1, None, 1.0)["ok"])


class SourcesTests(unittest.TestCase):
    def spec(self, location, ouroboros_path="research/x.md"):
        return dict(broker=dict(bases="%TERMINAL%/no_such_bases", symbols=[]),
                    sources=[dict(id="s", location=location, valid_from="2025-07-01")],
                    ouroboros=dict(source_commit=None, slices=[dict(id="o", path=ouroboros_path, priority="low")]))

    def test_existing_source_ok_and_ouroboros_holds(self):
        with tempfile.TemporaryDirectory(dir=paths.REPO) as d:
            open(os.path.join(d, "a.csv"), "w").close()
            res = sources.check(self.spec("%REPO%/" + os.path.basename(d)))
        self.assertEqual(res["sources"][0]["status"], "ok")
        self.assertEqual(res["verdict"], "HOLD")

    def test_missing_source_rejects(self):
        res = sources.check(self.spec("%REPO%/no_such_dir"))
        self.assertEqual(res["sources"][0]["status"], "missing")
        self.assertEqual(res["verdict"], "REJECT")

    def test_freeze_then_detect_change(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "m1.pkl"), "w") as f:
                f.write("bars")
            spec = self.spec("%REPO%/tools", ouroboros_path="m1.pkl")
            spec["ouroboros"].update(root=root, source_commit="abc")
            spec["ouroboros"]["slices"] += [dict(id="c", path=None, covered_by="broker", priority="low"),
                                           dict(id="n", path=None, available=False, priority="low")]
            self.assertEqual(sources.check(spec)["ouroboros"]["slices"][0]["status"], "unfrozen")
            res = sources.check(spec, freeze=True)
            self.assertEqual([s["status"] for s in res["ouroboros"]["slices"]], ["ok", "covered", "not_available"])
            if not paths.OUROBOROS:
                self.assertEqual(res["verdict"], "ACCEPT")
            with open(os.path.join(root, "m1.pkl"), "w") as f:
                f.write("bars moved")
            self.assertEqual(sources.check(spec)["ouroboros"]["slices"][0]["status"], "changed")

    def test_unknown_ouroboros_path(self):
        res = sources.check(self.spec("%REPO%/tools", ouroboros_path=None))
        self.assertEqual(res["ouroboros"]["slices"][0]["status"], "path_unknown")


class PathTests(unittest.TestCase):
    def test_portable_roundtrip(self):
        p = os.path.join(paths.REPO, "tester", "aos")
        self.assertEqual(paths.portable(p), "%REPO%/tester/aos")
        self.assertEqual(os.path.normcase(paths.resolve("%REPO%/tester/aos")), os.path.normcase(p))
        self.assertIsNone(paths.resolve("%NOPE%/x"))


if __name__ == "__main__":
    unittest.main()
