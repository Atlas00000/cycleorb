# CycleORB v1.01 — New York only, EURUSD 2025.01.01 → 2026.10.31

* Task: ORB-P1-T02 (New York only)
* Preset: `Profiles/Tester/ORB/CycleORB_EURUSD_v1_NYonly.set` (baseline with `InpLonEnable=false`)
* Tester: YWO-Trade, EURUSD M5, every tick based on real ticks, 1:100
* Deposit **1 000 000** with `InpCycleCapital=10000` — sizing and cycle limits use 10 000; the large deposit only
  stands in for the monthly refill so margin never binds. Read results as % of the 10 000 allocation.
* Run config: `tester/run_NYonly_2025Jan_2026Oct.ini` · report: `<data>/reports/CycleORB_v101_NYonly_2025Jan_2026Oct.htm`
* Journal extract: `tester/run_v101_NYonly_2025Jan_2026Oct_journal.log`

A first attempt with deposit 10 000 is invalid: after cumulative monthly losses the real balance could not
cover margin (orders rejected "not enough money" from 2025-10, final balance 281.84).

## Data quality

| Period | Ticks |
| --- | --- |
| 2025-01 → 2025-05 | No real ticks on server — generated from M1 |
| 2025-06 → 2025-12 | Real ticks largely discarded by tester (mismatch with M1) — mostly generated |
| 2026-01 → 2026-10 | Real ticks (3 minor gaps in 2026-04) |

## Per-month cycle result (% of 10 000)

| Month | P&L % | Peak % | End |
| --- | --- | --- | --- |
| 2025-01 | −14.41 | 5.27 | active |
| 2025-02 | +13.41 | 26.82 | ratchet |
| 2025-03 | −8.79 | 3.20 | active |
| 2025-04 | −9.48 | 17.51 | active |
| 2025-05 | +8.69 | 20.09 | ratchet |
| 2025-06 | −13.43 | 0.46 | active |
| 2025-07 | −25.83 | 4.48 | active |
| 2025-08 | −13.63 | 11.67 | active |
| 2025-09 | −24.49 | 3.00 | active |
| 2025-10 | −23.47 | 11.38 | active |
| 2025-11 | +10.94 | 22.52 | ratchet |
| 2025-12 | −21.74 | 13.22 | active |
| 2026-01 | +2.23 | 6.80 | active |
| 2026-02 | −13.34 | 5.86 | active |
| 2026-03 | −16.60 | 7.78 | active |
| 2026-04 | +18.88 | 37.78 | ratchet |
| 2026-05 | −18.40 | 18.32 | active |
| 2026-06 | +16.72 | 33.52 | ratchet |
| 2026-07 | −24.24 | 7.77 | active |
| 2026-08 | −10.58 | 0.26 | active |
| 2026-09 | −18.61 | 1.83 | active |
| 2026-10 | +10.33 | 20.68 | ratchet |

Positive 7/22 (sum +81.2%), negative 15/22 (sum −257.0%). Net −175.8% of one allocation
(2025: −122.2%, 2026: −53.6%). No soft halt or hard flatten — losses are a steady bleed, not blow-ups.

## Trade stats

| Metric | Value |
| --- | --- |
| Trades | 291 |
| Win % | 34.4 |
| Profit factor | 0.73 |
| Avg win / avg loss | 476 / −341 (1.40) |
| Exits TP / SL / time / cycle stop | 39 / 133 / 113 / 6 |
| ATR / cost filter skips | 0 (filters never bind for NY) |

## Verdict

**FAIL.** New York alone has no edge with v1 defaults, on real ticks (2026) and generated ticks (2025) alike.

The New York profit seen in the combined 2026 run (PF 1.37) was path-dependent: shared-budget ratchet stops
cut New York off in its bad stretches. On its own, 2026 is −53.6%.

## Implications for next tests

* The 2R stop-order breakout at 08:00–08:30 NY does not continue often enough: 46% of trades hit the full stop.
* Filters never trigger for NY — the ATR band 10–35% is not selective here.
* Candidates worth one run each before changing design: range start 09:30 NY; stop mode mid; failed-breakout
  fade (Phase 4) — a 34% win rate with a 1.4 payoff suggests the opposite side may be the edge.
