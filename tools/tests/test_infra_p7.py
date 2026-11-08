"""INF-P7-T04 forward telemetry rules: the one-way pull (only live ledgers, only changed files, the source untouched),
calendar-leak detection, live drawdown, the 'Below frontier two month-ends' stop rule input. The real run is
python -m corb forward all."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from corb import forward  # noqa: E402


class Pull(unittest.TestCase):
    def setUp(self):
        self.src, self.inbox = tempfile.mkdtemp(), tempfile.mkdtemp()
        for name, text in (("CORB_26110200_EURUSD_live_events.csv", "a\n"), ("CORB_26110200_EURUSD_live_decisions.csv", "b\n"),
                           ("CORB_26110200_EURUSD_tester_1000_events.csv", "c\n"), ("notes.txt", "d\n")):
            with open(os.path.join(self.src, name), "w") as f:
                f.write(text)

    def tearDown(self):
        shutil.rmtree(self.src)
        shutil.rmtree(self.inbox)

    def test_copies_only_live_ledgers_and_only_when_changed(self):
        before = sorted(os.listdir(self.src))
        self.assertEqual(len(forward.pull(self.src, self.inbox)["copied"]), 2)
        self.assertEqual(forward.pull(self.src, self.inbox)["copied"], [])
        with open(os.path.join(self.src, "CORB_26110200_EURUSD_live_events.csv"), "a") as f:
            f.write("more\n")
        self.assertEqual(forward.pull(self.src, self.inbox)["copied"], ["CORB_26110200_EURUSD_live_events.csv"])
        self.assertEqual(sorted(os.listdir(self.src)), before)

    def test_unreachable_source_is_reported_not_raised(self):
        self.assertEqual(forward.pull(os.path.join(self.src, "missing"), self.inbox)["copied"], [])


def ev(eid, entry, exit_, pnl=0.0, day=None):
    return dict(event_id=eid, entry_time=entry, exit_time=exit_, pnl_ccy_est=pnl, pnl_R=pnl / 10, day=day or entry[:10])


class Rules(unittest.TestCase):
    def test_overnight_hold_is_a_calendar_leak(self):
        e = [ev("a", "2026-12-01T14:00:00Z", "2026-12-01T19:00:00Z"), ev("b", "2026-12-02T14:00:00Z", "2026-12-03T14:30:00Z")]
        self.assertEqual(forward.calendar_leaks(e), ["b"])

    def test_live_drawdown_from_realised_money(self):
        e = [ev("a", "2026-12-01T14:00:00Z", "2026-12-01T15:00:00Z", 100.0),
             ev("b", "2026-12-02T14:00:00Z", "2026-12-02T15:00:00Z", -220.0)]
        self.assertAlmostEqual(forward.live_dd_pct(e, 1000), 20.0)

    def test_month_end_states_one_per_forward_month(self):
        base = [1.5, -1.0] * 40
        fwd = [ev(f"e{i}", f"2026-{m:02d}-1{i}T14:00:00Z", f"2026-{m:02d}-1{i}T15:00:00Z", -10.0, f"2026-{m:02d}-1{i}")
               for m in (12, 11) for i in range(5)]
        states = forward.month_end_states(base, sorted(fwd, key=lambda e: e["day"]), 0.25, 0.01)
        self.assertEqual([m for m, _ in states], ["2026-11", "2026-12"])


if __name__ == "__main__":
    unittest.main()
