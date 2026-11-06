# CycleORB v1.01 — baseline review, EURUSD 2026.01.01 → 2026.10.31

* Tasks: ORB-P0-T02 (smoke test) + first baseline (ORB-P1-T03 on available real-tick data)
* Preset: `Profiles/Tester/ORB/CycleORB_EURUSD_v1_baseline.set` (defaults, capital 10 000)
* Tester: YWO-Trade, EURUSD M5, every tick based on real ticks, deposit 10 000, 1:100
* Run config: `tester/run_2026JanOct.ini` · report: `<data>/reports/CycleORB_v101_2026JanOct.htm`
* Journal extract: `tester/run_v101_2026JanOct_journal.log`

## Fix found during this run (v1.00 → v1.01)

When a position closed, the next tick could see floating P&L = 0 before realized P&L was refreshed
(`OnTradeTransaction` can arrive after `OnTick`). TP closes looked like a drop → false ratchet stops
(Apr/May/Jun); SL closes briefly inflated the month peak. Realized is now refreshed whenever the
EA's own open-position count changes. v1.00 results are invalid.

## Smoke test checks

| Check | Result |
| --- | --- |
| DST dates logged (UK 03.29–10.25, US 03.08–11.01) | OK |
| London range end 10:30 server, 11:30 in UK/US gap week (e.g. 2026.10.26) | OK |
| New York range end 15:30 server all period | OK |
| OCO delete on fill, time exit closes, no PLACE FAIL | OK |
| Soft halt (Jul −30.0%), ratchet stops (Mar, Apr, May, Jun, Oct) | OK |
| Last-trading-day block | OK (6 skips) |

## Per-month cycle result (capital 10 000 each month)

| Month | P&L % | End state |
| --- | --- | --- |
| 2026-01 | −9.17 | active |
| 2026-02 | −13.49 | active |
| 2026-03 | +8.54 | ratchet stop |
| 2026-04 | +27.67 | ratchet stop (peak 55.5) |
| 2026-05 | +12.93 | ratchet stop |
| 2026-06 | +27.59 | ratchet stop (peak 56.1) |
| 2026-07 | −30.22 | soft halt |
| 2026-08 | −21.91 | active |
| 2026-09 | −27.69 | active |
| 2026-10 | +10.19 | ratchet stop |

Positive months 5/10 (sum +86.9%), negative 5/10 (sum −102.5%). Net −15.6%. No month reached hard flatten.

## Trade stats

| | All | London | New York |
| --- | --- | --- | --- |
| Trades | 172 | 76 | 96 |
| Win % | 35.5 | 28.9 | 40.6 |
| Net $ | −1 556 | −6 590 | +5 034 |
| Profit factor | 0.96 | 0.71 | 1.37 |
| TP / SL / time-or-cycle close | 32 / 83 / 57 | 20 / 52 / 4 | 12 / 31 / 53 |

## Verdict

**Mechanics: PASS. Edge: FAIL (v1 defaults).** Phase 1 gates missed: mean and median month negative.

* London 08:00–08:30 breakout loses (PF 0.71, 29% win) — most trades hit the full stop.
* New York is positive (PF 1.37), mostly via the 15:00 time exit rather than the 2R target.
* Only 10 months of real ticks are available on this server (ticks from 2025-06) — small sample.

## Next tests (Phase 2, no new features)

1. NY only, same period — confirm it stands alone.
2. London: stop mode mid, target 1.5R, range 15 / 45 / 60 min.
3. NY: target 1.5R vs time-exit-only (large TargetR), range start 09:30.
4. Extend to 2025-06 → 2026-10 (all real ticks available) for every candidate.
