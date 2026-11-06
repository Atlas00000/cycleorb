# CycleORB Roadmap — EURUSD Opening Range Breakout in Monthly Capital Cycles

Standalone EA. Independent of BMRG: own folder, own includes, own magic numbers.
BMRG and CycleORB are **never run at the same time** on the same account.

---

## 1. Objective

Run EURUSD opening-range breakouts (London + New York) inside discrete monthly capital cycles:

* A fixed allocation is deployed at the start of each month; profits are extracted at month end.
* Drawdown up to ~40% of the month's starting capital is tolerated; past that the book is flattened for the rest of the month.
* Profits are protected with a ratchet once the month is well up.
* Every trade resolves inside its session — the book is flat every evening and at month end.

**Done for v1 means:** compiles clean, runs in the Strategy Tester on EURUSD with real ticks, places/cancels/closes orders at the correct London and New York times across DST changes, and logs a per-month cycle summary that can be scored.

---

## 2. Locked v1 decisions

| Area | Decision |
| --- | --- |
| Instrument | EURUSD, hedging account (DE40 preset since v1.04; the EURUSD warning at init is informational) |
| Setups | London and New York, separate magics, one shared monthly budget. Since v1.06 a third Tokyo setup (JST = UTC+9, no DST; `InpTky*` inputs, default off) |
| Time handling | Sessions defined in London / New York local time; broker server assumed GMT+2 (GMT+3 during US DST); fixed-offset mode available. **YWO-Trade is UTC+0 → use `InpServerTZ=1`, `InpServerFixedOffsetH=0`** (all v1.01 runs used the default and traded 2–3 h late) |
| London | Range 08:00–08:30 London, entries until 11:00, close all 16:00 |
| New York | Range 08:00–08:30 NY (09:30 is a Phase 2 test), entries until 11:30, close all 15:00 |
| Entry | OCO buy-stop / sell-stop at range edge ± buffer; buffer = max(2 × spread, 5% of range). Since v1.03 "spread" = average M1 spread over the range window (the live tick at range end is often a data-release spike) |
| Stop / target | Stop at opposite range edge (mid-range optional); target 2R; time exit always applies. Since v1.02 TargetR < 1 is refused and a side whose TP distance < SL distance is skipped (never TP < SL). Since v1.07 that check allows half a point of float noise, so TargetR = 1 sides are no longer skipped at random |
| Trades | Max one trade per setup per day |
| Filters | Range width 10–35% of daily ATR(14); spread + commission ≤ 10% of range. Since v1.04 optional H1 volatility regime filter: `InpMinVolPct` = minimum percentile of the latest completed H1 ATR(`InpVolATRPeriod`) among the last `InpVolLookback` H1 bars, checked at range end (default 0 = off, so earlier presets are unchanged). Since v1.05 (AAPL) optional daily trend side: `InpTrendSideOnly` arms only the buy stop when the previous D1 close is above its D1 SMA(`InpTrendMAPeriod`), only the sell stop when below, nothing when equal (default off) |
| Sizing | Risk per trade = (cycle equity − hard-flatten level) / 8, capped at 8% of cycle capital |
| Soft halt | −30% cycle drawdown: no new entries for the month |
| Hard flatten | −38% cycle drawdown: close everything, stop for the month |
| Ratchet | Arms at +20%; floor = max(+10%, 50% of peak month profit); hit floor → flatten, stop for the month |
| Month end | No new entries on the last trading day; anything open at month roll is closed |
| Calendar (v1.09) | `InpSkipDates` = exchange-local dates (YYYYMMDD, comma-separated) on which nothing is armed: exchange holidays and early closes. The CFD can stop trading before the session exit, and the time exit then cannot close (2026 tester: US500 held a Juneteenth position over the weekend, −2.23R). US-share and US500 presets carry NYSE 2026–2027, UK100 LSE, DE40 Xetra; FX and JP225 empty. Lists must be extended each year |
| AI OS observe layer (v1.10) | `InpAosLedger` (default off) writes decision / event / shadow ledgers with L1 features (regime, ORB structure, high-impact calendar, cross-session context) to `Common\Files\CycleORB`. Never changes trading: verified event-identical to the v1.09 baselines on 9 symbols (`doc/ai_OS.md` AOS-P1). New includes: `Features.mqh`, `Events.mqh`, `Ledger.mqh`, `Shadow.mqh`; the calendar comes from `Scripts/CycleORB/CycleORB_ExportCalendar.mq5` |
| AI OS guardrails L3 / health L4 (v1.12–1.13) | `Guard.mqh`: calendar-leak kill (refused close, late or carried position), entry-slippage abort, lot-minimum guard, own-equity DD halving, live clock refusal. `Health.mqh`: month-end W40 / W80 lifecycle from the shadow stream, `HEALTH` log, optional sizing and a risk cap while Compressing. All off by default. Recommended forward-test set: `Presets/AOS/AOS-P3-REC_<asset>.set` (`doc/ai_OS.md` AOS-P3) |
| AI OS policy L2 (v1.11) | `Policy.mqh`: side gates, event-day and range-cell size multipliers (≤ 1), pre-release pending cancel. All default off. Every rule tested in AOS-P2 was rejected (each withheld positive trades), so production presets keep the defaults. v1.11 also accepts `YYMMDD` skip dates: MT5 silently truncates string inputs at 255 characters, and the US list now covers 2025-07 → 2027 in 215 characters |
| Market-closed retries (v1.09) | A delete/close rejected with `TRADE_RETCODE_MARKET_CLOSED` is retried at most once a minute (was every tick: 18,836 failed closes in one run) |

"Cycle equity" = cycle capital + this EA's realized P&L this month + its floating P&L. It never uses whole-account equity.

---

## 3. Layout

```
Experts/CycleORB/
  CycleORB.mq5            entry point: OnInit / OnTick / OnTradeTransaction
  ROADMAP.md
  Include/
    Config.mqh            inputs, magics, validation, logging
    SessionClock.mqh      server <-> UTC <-> London / New York, UK + US DST
    Cycle.mqh             monthly cycle: capital, halt, flatten, ratchet, risk money
    Orders.mqh            pending orders / positions by magic, lot sizing
    Setup.mqh             one ORB setup: range, filters, OCO orders, windows, time exit
```

Magics: `InpMagicBase + 1` = London, `InpMagicBase + 2` = New York, `InpMagicBase + 3` = Tokyo (default 26110101 / 26110102 / 26110103).

---

## 4. How to compile and test

### Compile

Open `CycleORB.mq5` in MetaEditor → Compile (F7). Expected: 0 errors, 0 warnings.

### Strategy Tester settings

| Setting | Value |
| --- | --- |
| Expert | `CycleORB\CycleORB` |
| Symbol | EURUSD |
| Timeframe | M1 or M5 (logic is time-based, chart TF does not matter) |
| Modelling | **Every tick based on real ticks** |
| Period | Smoke test: 1 month. Baseline: 2020-01-01 → latest |
| Deposit | e.g. 10 000 |
| `InpCycleCapital` | e.g. 10 000 — each month starts from this base, as if profits were withdrawn |
| Deposit (multi-month runs) | **Much larger than `InpCycleCapital`** (e.g. 1 000 000). The tester cannot refill the account monthly; with deposit = capital, losing streaks exhaust margin and orders get rejected. Read results as % of `InpCycleCapital` |
| `InpCommissionPoints` | Your round-turn commission in points (e.g. 70 for $7/lot on EURUSD), 0 on spread-only accounts |
| `InpServerTZ` | Leave default unless your broker is not GMT+2/+3 |

### What to check in the Journal (smoke test)

1. `Clock <year>: UK DST ... | US DST ...` — DST dates are right.
2. `Init OK ...` — magics and risk settings.
3. Each weekday: one `RANGE LON ...` / `RANGE NY ...` line or a `SKIP ...` line with the reason.
4. `PLACE BUY_STOP` / `PLACE SELL_STOP` right after the range closes:
   * On a GMT+2/+3 broker: London range ends 10:30 server time, New York 15:30 server time, most of the year.
   * During the UK/US DST gap weeks (mid/late March, late October to the first Sunday of November) London ends at 11:30 server time. New York stays at 15:30.
5. `DELETE ... OCO fill` when one side fills.
6. `DELETE ... entry window closed` for unfilled orders, `CLOSE ... time exit` for open positions.
7. `CYCLE_END yyyymm ... pnl=..% state=..` at each month roll — this is the scorecard line.

Live/demo only: if the Journal shows `WARNING server offset mismatch`, change `InpServerTZ`.

---

## 5. Phases

Task IDs: `ORB-P<phase>-T<nn>`.

### Phase 0 — Build and smoke test (this build)

* **ORB-P0-T01** Compile clean. ✅
* **ORB-P0-T02** 1-month tester run (choose a month that contains a DST change, e.g. March or October/November). Verify all items in §4 checklist. ✅ Done on 2026.01–10 (v1.01, see `tester/REVIEW_2026JanOct_v101.md`). Fixed stale-realized bug that caused false ratchet stops.
* **ORB-P0-T03** Verify cycle controls by forcing them: run with `InpSoftHaltPct=2`, `InpHardFlattenPct=4` and separately `InpRatchetArmPct=2`, `InpRatchetFloorPct=1`; confirm `CYCLE_HALT` / `CYCLE_STOP` lines and that no orders are placed afterwards that month.

### Phase 1 — Baseline (v1 defaults, no tuning)

* **ORB-P1-T01** London only, 2020 → latest, real ticks.
* **ORB-P1-T02** New York only, same period. Done 2025.01–2026.10: net −175.8% of one allocation, PF 0.73, 7/22 positive months. FAIL (`tester/REVIEW_NYonly_2025Jan_2026Oct_v101.md`) — **invalid: wrong server clock**.
* **ORB-P1-T03** Both setups together. First pass 2026.01–10: net −15.6%, PF 0.96 — London PF 0.71, New York PF 1.37. Gates missed — **invalid: wrong server clock**.
* **ORB-P1-T04** 6-month EURUSD review on the correct clock (v1.03, NY only, range/ATR 17.5–35 %, 2R, 1 % risk). Tip 2026.05–10: 53 trades, WR 47.2 %, +13.7 %, max DD 4.7 %. 2024.11–2026.10: 199 trades, +45.3 %, max DD 12.5 %, 17/24 positive months. London has no stable region (off). Preset `Presets/CycleORB-M5-EURUSD-6M-NY_chart.set`; review `Ouroboros/research/assets/EURUSD/CycleORB_M5_chart_preset.md`. ✅

* **ORB-P1-T05** DE40 (YWO `DE30`) 6-month review, v1.04, London/Frankfurt setup only: range 09:15–10:15 Frankfurt (08:15 + 60 min London), flat 17:00 Frankfurt, opposite-edge stop, 2.5R, range/ATR 10–40 %, H1 vol percentile ≥ 33, 1 % risk. Tester tip 2026.05–10: 47 trades, WR 44.7 %, +4.7 %, max equity DD 6.2 %. 2025.06–2026.10: 120 trades, WR 49.2 %, +31.2 %, max equity DD 6.4 %, 12/16 positive months. New York off on DE40. Preset `Presets/CycleORB-M5-DE40-6M-FRA_chart.set`; review `Ouroboros/research/assets/DE40/CycleORB_M5_chart_preset.md`. ✅

* **ORB-P1-T07** JP225 (YWO `JPN225`) 6-month review, v1.06, Tokyo setup only: range 09:00–10:00 JST, orders cancelled 11:30 JST, flat 15:25 JST, opposite-edge stop, 1.75R, range/ATR 25–60 %, H1 vol percentile ≥ 33, 1 % risk, magic base 26110500. Tester tip 2026.05–10: 48 trades, WR 50.0 %, +8.6 %, max equity DD 3.1 %. 2025.06–2026.10: 106 trades, WR 54.7 %, +22.2 %, max equity DD 4.2 %, 13/17 positive months. London and New York off (no variant positive in both tip and back-check). Preset `Presets/CycleORB-M5-JP225-6M-TKY_chart.set`; review `Ouroboros/research/assets/JP225/CycleORB_M5_chart_preset.md`. ✅

* **ORB-P1-T08** AAPL (YWO `Apple`) 6-month review, New York setup. **No production preset:** 186,624 + 9,600 variants, none positive after costs in both the tip (2026.05–10) and the back-check (2024.02–2026.04). The 0.29 USD spread (0.09–0.28R per trade) exceeds the long-run gross breakout edge (≈ +0.01–0.02R). **Research preset only (tip-fitted, NOT production):** 09:30+30 range, entries until 13:30, flat 15:55, opposite-edge stop, 1.1R, range/ATR 20–80 %, `InpTrendSideOnly`, 0.5 % risk, magic base 26110600. Tester tip: 32 trades, WR 53.1 % vs BWR 47.7 %, +1.0 %, +0.06R per trade before the framework slippage prior, −0.02R after it (Fragile). Tester 2025.07–2026.04: −0.28R per trade. Broker `Apple` history before 2025-06-18 is stamped UTC+3: tester runs valid from 2025-06-18 only. Preset `Presets/CycleORB-M5-AAPL-6M-NY-RESEARCH_chart.set`; review `Ouroboros/research/assets/AAPL/CycleORB_M5_review.md`. ⚠️

* **ORB-P1-T10** UK100 (YWO `UK100`) 6-month review, v1.06, London setup only: range 08:15–09:15 London, orders cancelled 11:30, flat 16:25, opposite-edge stop, 2.5R, range/ATR 10–50 %, H1 vol percentile ≥ 33, 1 % risk, magic base 26110800. Offline M1 mirror: tip 2026-05–11-03 53 trades, WR 54.7 %, +0.32R; back-check 2025-12-17–2026-04 41 trades, WR 53.7 %, +0.32R; 12/12 perturbations positive in both windows. Full sample EF 14.9 pp > M 9.9 pp, but n = 94 is under the 100-event floor, so not production-worthy. New York off. Preset `Presets/CycleORB-M5-UK100-6M-LON_chart.set`; review `Ouroboros/research/assets/UK100/CycleORB_M5_chart_preset.md`. ⚠️

* **ORB-P1-T09** TSLA (YWO `Tesla`) 6-month review, v1.06, New York setup only: range 09:45–10:00 NY, orders cancelled 11:30, flat 15:50, opposite-edge stop, 2.5R, range/ATR 10–40 %, cost cap 10 %, H1 vol percentile ≥ 33, 0.5 % risk, magic base 26110700. Offline M1 mirror: tip 2026.05–10 39 trades, WR 56.4 %, +0.064R per trade; back-check 2024.02–2026.04 219 trades, WR 45.7 %, +0.083R; 16/16 perturbations positive in both windows. Fragile (EF 4.1 < M 6.1 pp), G2 fails (0/4 OOS folds). **Broker-session dependent:** if `Tesla` uses the US-share session 14:30–21:00 UTC all year (as NVDA), orders arm at 10:30 NY in summer and the tip turns −0.37R; under that session no variant of 186,624 is positive in both windows. Safe through US standard time (to 2027-03-08); watch for `WAIT NY` in the first DST week. Tester not run yet (terminal had live experts). Preset `Presets/CycleORB-M5-TSLA-6M-NY_chart.set`; review `Ouroboros/research/assets/TSLA/CycleORB_M5_chart_preset.md`. ⚠️

* **ORB-P1-T11** US500 (YWO `SPX500`) 6-month review, v1.06, New York setup only: range 10:00–11:00 NY, orders cancelled 12:00, flat 15:00, opposite-edge stop, 2R, `InpTrendSideOnly` (D1 SMA 20), range/ATR 10–40 %, cost cap 15 %, no H1 vol floor, 1 % risk, magic base 26110900. Offline M1 mirror: tip 2026-05–10 23 trades, WR 47.8 %, +0.19R per trade; back-check 2025-07–2026-04 45 trades, WR 62.2 %, +0.25R; long check 2023-02–2025-06 (re-stamped old feed at current costs) 152 trades, WR 57.9 %, +0.13R; 16/16 perturbations positive in all three windows. Full sample EF 11.6 pp > M 6.5 pp (Robust), but G0 (n = 225 < 385), G2 (WFE 0.39 < 0.5) and G4 MC-3 (median terminal 0.91 × C₀) fail: not production-worthy. The plain ORB (no trend side) is negative after costs. Broker `SPX500` history before 2025-06-18 is stamped UTC+2/+3 with a different spread: tester runs valid from 2025-06-18 only. Tester not run yet (terminal had live experts). Preset `Presets/CycleORB-M5-US500-6M-NY_chart.set`; review `Ouroboros/research/assets/US500/CycleORB_M5_chart_preset.md`. ⚠️

* **ORB-P1-T12** XOM (YWO `Exxon`) 6-month review, New York setup. **NO-GO for production.** Research-only preset on request (least-negative cell: 09:30+60 range, entries until 11:30, flat 12:00, opposite stop, 1.5R, range/ATR 40–150 %, cost cap 30 %, 0.25 % risk, magic base 26111000; mirror WR 53.5 % tip / 58.5 % back but −0.25R per trade, 0/25 months positive) `Presets/CycleORB-M5-XOM-6M-NY-RESEARCH_chart.set`. Bid/ask M1 mirror, 715,680 variants ungated + 715,680 gated (14:30 UTC session): 0 positive after costs on the tip (2026-05–10), 0 on the back-check (2024-09–2026-04). Gross breakout edge −0.18 to +0.04R vs 0.19–0.37R cost (spread 0.29 USD vs 09:30 opening ranges that are 50–65 % of daily ATR, ~90 % time exits). No regime filter or target fixes it; a failed-breakout fade probe is negative before costs too. Broker gap: no `Exxon` bars 2026-05-12 → 06-30. Review `Ouroboros/research/assets/XOM/CycleORB_M5_review.md`. ❌

* **ORB-P1-T10** MSFT (YWO `Microsoft`) 6-month review, v1.07, New York setup. **No production preset (NO-GO).** 0 / 186,624 variants positive after framework costs in both the tip (2026-05–10) and the back-check (2024-02–2026-04), with orders at range end or session-gated (14:30 UTC). Focused sweep (cost caps 7–10 %, 15–90 min ranges): 0 / 5,676 on framework costs, 12 on realistic costs (chance level). Gross breakout edge ≈ 0 (−0.08 to +0.03R per trade); 0.33 USD spread = 0.10–0.28R per trade. Best EA-runnable cell (09:45+15, band 20–60 %, cap 10 %, 1R) is −0.009R per trade on framework costs, +0.03R realistic, not a plateau, edge only on H1-ranging days. Broker history has no bars 2026-05-12 → 06-30. **Research preset only** (that cell: entries until 13:30, flat 14:00, buffer 1 × spread, 0.5 % risk, magic base 26111100), demo only: `Presets/CycleORB-M5-MSFT-6M-NY-RESEARCH_chart.set`. v1.07 lets TargetR = 1 sides through the TP ≥ SL check (half-point float tolerance). Tester `.ini` files `tester/run_v107_MSFT_NY_*.ini` not run yet (terminal has live experts). Review `Ouroboros/research/assets/MSFT/CycleORB_M5_review.md`. ⚠️

* **ORB-P1-T13** v1.09 re-score at small-account size (500 / 1000 USD), longest valid real-tick window, holiday skip dates on. US500 2025-07 → 2026-10: 71 trades, WR 56.3 %, +0.28R, PF 1.95, max DD 4.0–4.7 %, 0 failed exits (was 18,836 in the v1.08 run). UK100 2025-12-17 → 2026-10: at 1000 USD 88 trades, +0.40R, PF 1.99. At 500 USD only 54 trades (82 order sides below the 0.1-lot minimum), so UK100 needs ≈ 1000 USD at 1 % risk. DE40-500USD 2025-07 → 2026-10: 120 trades, +0.24R, PF 1.52, +86 % (500) / +102 % (1000), but the second half is +0.10R and the MC P95 drawdown is 24.5–27.4 %. ini `tester/run_v109_*`; review `doc/CycleORB_System_Profile.md` §13. ✅

Note: YWO-Trade real ticks start 2025-06, so the longest real-tick baseline is 2025-06 → latest.

Score per month, not over the whole period:

| Metric | Proposed gate |
| --- | --- |
| Mean monthly P&L % | > 0 |
| Median monthly P&L % | ≥ 0 |
| Months hitting hard flatten | ≤ 10% |
| Months stopped by ratchet / ending positive | report |
| Worst run of losing months | report |
| Trades per month | report (expect ~10–35) |
| Average R per trade after costs | > 0 |

### Phase 2 — Robustness of the core (no new features)

* **ORB-P2-T01** Range length 15 / 30 / 45 / 60 min.
* **ORB-P2-T02** Target 1.5 / 2 / 2.5 / 3 R.
* **ORB-P2-T03** Stop mode opposite vs mid.
* **ORB-P2-T04** New York range 08:00 vs 09:30.
* **ORB-P2-T05** ATR band and cost cap neighbourhood.
* **ORB-P2-T06** Walk-forward: tune on 2020–2023, check 2024 → latest unchanged.

Accept only parameter regions where neighbouring values also pass Phase 1 gates.

### Phase 3 — Filters, one at a time (keep only if per-month metrics improve)

* **ORB-P3-T01** Compression: prior day NR4 / NR7 or inside day.
* **ORB-P3-T02** Daily trend direction filter.
* **ORB-P3-T03** News date blacklist (CSV) for ECB / NFP / CPI / FOMC days.
* **ORB-P3-T04** Day-of-week review (data first, filter only if clear).

### Phase 4 — More setups under the same budget

* **ORB-P4-T01** Asian range (00:00–07:00 UTC) breakout into London.
* **ORB-P4-T02** Failed-breakout fade (closes back inside range → trade opposite).

### Phase 5 — Mean-reversion partner (same EA, new module)

* **ORB-P5-T01** Spec the mean-reversion module (new code, not BMRG's grid), own magic, same cycle budget, month-end flatten.
* **ORB-P5-T02** Correlation check vs ORB monthly results.

### Phase 6 — Forward test and go-live

* **ORB-P6-T01** Demo forward test ≥ 2 full months; confirm server offset, fills and slippage vs tester.
* **ORB-P6-T02** Live with reduced `InpMaxRiskPct` for the first cycle.

### Phase 7 — AI OS around the frozen engine

Status 2026-11-06: AOS-P0–P4 and P6 done, P5 (retraining) deferred. Outcome: no trade-selection layer beats the production filters (P2 rules and the P4 learned gate were rejected out of sample). The accepted additions are survival guards and monitoring (P3). The forward-test candidate `Presets/AOS/AOS-P3-REC_<asset>.set` was **signed off on 2026-11-06** (`doc/aos_promotion_queue.md`), so AOS-P7 (demo forward test) can start. Research and test presets are archived in `Presets/AOS/archive/` and `Profiles/Tester/ORB/AOS/archive/`.

Layered permit / withhold / resize / guardrail stack (L1 Perception … L8 Promotion queue) that enhances the production presets without changing range, stop, target or exit. Full plan, task IDs `AOS-P0` … `AOS-P7`, acceptance bar and test-preset naming: `doc/ai_OS.md`. Baselines and triggers: `doc/edge_framework.md`.

---

## 6. Known limitations (v1)

* Commission is an input (points), not read from the broker.
* Lot sizing floors to the volume step; if risk is too small for the minimum lot, that side is skipped (logged).
* In the tester, ratchet peak / stopped state are not persisted (each run starts clean). Live, they are kept in terminal global variables `CORB_<magicBase>_<symbol>_<yyyymm>_peak|stopped` so a restart mid-month does not re-arm a stopped cycle. Since v1.08 the name includes the symbol: before, two charts with the same magic base on one terminal shared the ratchet peak and stopped flag. On the first restart after upgrading, a cycle stopped earlier in the month under the old name is not restored.
* Every preset sets all inputs (v1.08 preset pass). A `.set` that omits an input leaves the chart's or tester's previous value in place (e.g. Tokyo left enabled from a JP225 run), so new presets must list every input. Each chart preset needs its own `InpMagicBase`; `EURUSD-LON0700` moved from 26110300 (shared with DE40) to 26110210.
* With `InpCycleCapital = 0`, capital = account balance at month start minus this month's realized P&L. Deposits/withdrawals mid-month shift that base.
* If both stop orders trigger between two ticks (extreme whipsaw), both positions can open; each still has its own stop, target and time exit.
* No news filter in v1 (MT5 calendar is not available in the tester).
* Holiday / early-close dates are a static input (`InpSkipDates`), not read from the broker; session tables do not carry holidays. Extend each preset's list before a new year starts (current lists end 2027-12-31).

---

## 7. Out of scope for v1

Trailing stops, break-even moves, partial exits, re-entries after stop-out, multi-symbol, dashboards, external config files. Add only through a phase task above.
