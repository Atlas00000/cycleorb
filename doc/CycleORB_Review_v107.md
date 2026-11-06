# CycleORB v1.07 — Design, Concept and Performance Review

**Date:** 2026-11-04  
**Scope:** EA source (`CycleORB.mq5` + `Include/*.mqh`, v1.07), `ROADMAP.md`, all 12 presets in `Presets/`, tester reviews in `tester/`, and the per-asset research cards in `Ouroboros/research/assets/<SYMBOL>/CycleORB_*.md`.  
**Broker context:** YWO-Trade, hedging, spread-only, server clock UTC+0.  
**Not:** a new backtest. Every performance number below is taken from the existing tester runs and offline M1 mirrors. Where they disagree, the source is named.

---

## 1. Executive summary

**Verdict: the engineering is sound and the edge is real but not yet proven. No asset passes every framework gate. Four assets have tester-confirmed positive expectancy and justify a frozen-preset demo forward test: DE40, JP225, EURUSD (NY) and NVDA.**

| Area | Grade | One-line reason |
| --- | --- | --- |
| Code / architecture | **A−** | Small, modular, defensive. DST handling, OCO, restart guards and session gating are all correct. Three operational issues (§3.3) |
| Trading concept | **B+** | The first-hour breakout with a time exit is a well-known intraday drift trade. The regime filters are relative and declared, not fitted peaks |
| Monthly capital cycle | **C** | Well built, but dormant. At the 0.5–1 % risk used by every preset, halt, flatten and ratchet never trigger (§4.6) |
| Evidence quality | **C+** | Positive in every window on 4 assets, but samples are 51–199 tester trades. Walk-forward (G2) fails everywhere, and real-tick history only starts 2025-06 |
| Asset fit | Mixed | **Index CFDs: good.** FX: workable. US single stocks: mostly no edge after spread (§5) |

**What works:** cash-session index opens with tight spreads (DE40, JP225, UK100, US500), the EURUSD 08:30 NY data window, and expansion opens on NVDA.  
**What fails:** low-beta or mean-reverting US shares at a ~0.30 USD spread (AAPL, MSFT, XOM), and every unfiltered "plain" ORB on every asset.

**Top three actions** (details in §9):
1. Fix the operational risks before running more than one instance on the terminal: the shared magic base (`26110300`), the global-variable names that don't include the symbol, and the presets that leave some inputs unset.
2. Run the pending tester confirmations (UK100, US500, TSLA, MSFT, DE40-500USD) and start the demo forward test (ORB-P6-T01) on DE40, JP225, EURUSD-NY and NVDA, with presets frozen.
3. Decide what the monthly cycle is for. Either recalibrate it to the 1 % risk regime or document it as a catastrophe-only guard.

---

## 2. Concept — what the EA does

CycleORB is an **opening-range breakout (ORB)** that runs inside a **monthly capital cycle**.

1. **Range.** For each enabled session (London, New York, Tokyo, each in its own local time with its own DST rules), the EA records the high and low of M1 bars over a fixed window, for example 09:15–10:15 Frankfurt.
2. **Filters at range end.** The range must be a set fraction of the previous daily ATR(14). Spread plus commission must be a small share of the range. Two filters are optional: the H1 ATR percentile must be at least a floor ("not low volatility"), and orders can be limited to the side of the previous D1 close against its SMA(20).
3. **Orders.** A buy-stop goes above the high and a sell-stop below the low, each offset by a buffer of max(k × spread, p % of range). They are linked as OCO: when one fills, the other is deleted.
4. **Exits.** The stop sits at the opposite range edge (or mid-range). The target is `TargetR` × the stop distance and is never shorter than the stop. Unfilled orders are cancelled at the entry-window end. Everything is closed at the session exit time. There is at most one trade per setup per day, and the book is flat every evening.
5. **Monthly cycle.** Each month starts from a capital base. Risk per trade is (equity − hard-flatten floor) / 8, capped at `InpMaxRiskPct` of capital. A −30 % drawdown is a soft halt (no new entries). −38 % is a hard flatten for the rest of the month. A profit ratchet arms at +20 % and locks max(+10 %, 50 % of peak).

**Where the edge comes from in practice.** The target works mostly as a cap. Time exits close 44–78 % of trades on the positive assets (DE40 44 %, US500 67 %, JP225 73 %, NVDA 78 %). So the strategy is really *"enter the first-hour break, hold the session's drift to the close"*, and less *"break to 2R"*. Realised payoff (R ≈ 1.25–1.8) is well below the designed RR (1.5–3.0) on every positive preset. This is a property of the strategy, not a defect, but it matters for monitoring: watch the RR − R gap, not the TP hit rate.

**How the concept drifted.** v1 was "EURUSD London + New York, 8 % risk, monthly cycle as the core". By v1.07 it has become "one session per symbol, 0.5–1 % risk, regime-filtered, cycle dormant". The ROADMAP title and the init warning (`built and defaulted for EURUSD`) still describe v1.

---

## 3. Architecture and code review

### 3.1 Structure

| Module | Responsibility | Assessment |
| --- | --- | --- |
| `CycleORB.mq5` | `OnInit` / `OnTick` / `OnTradeTransaction`, wiring | Thin and clear. Refuses netting accounts (correct: setups can overlap) |
| `Config.mqh` | Inputs, magics, validation | Strong validation: refuses TargetR < 1, inverted bands, and soft halt ≥ hard flatten |
| `SessionClock.mqh` | Server ↔ UTC ↔ London / NY / Tokyo, UK and US DST | Correct rules (last Sunday Mar/Oct 01:00 UTC; 2nd Sunday Mar / 1st Sunday Nov). Gap weeks handled. Fixed-offset mode covers UTC+0 brokers |
| `Cycle.mqh` | Capital, realized/floating, halt, flatten, ratchet, risk money | Counts only this EA's deals on this symbol (never whole-account equity). The v1.01 stale-realized fix is in place |
| `Orders.mqh` | Count/delete/close by magic, lot sizing, stop orders | Sizing through `OrderCalcProfit` handles any contract (FX, index, share, JPY). Floors to the volume step and skips below the minimum lot |
| `Setup.mqh` | One ORB setup: day roll, range, filters, OCO, windows | Well guarded: restart guard (`OrdersEnteredSince`), session-gate wait (v1.05), range-window spread (v1.03), and float-tolerant TP ≥ SL (v1.07) |

About 900 lines in total, with no external dependencies beyond `Trade.mqh`. Every module does one job. It is easy to audit.

### 3.2 Strengths

- **Time handling is the hardest part of an ORB and it's done right.** Sessions are defined in exchange-local time, so the windows follow each venue through DST changes without manual edits.
- **Defensive order flow.** OCO deletion runs on the fill transaction and again on the next tick. A position left over from the previous day is closed before the new range (`now < tRangeStart && positions > 0`). Orders are skipped, with a log line, if price is already through the entry, the TP would be shorter than the SL, or the lot is below the minimum.
- **Never TP < SL is enforced twice:** at init (`InpTargetR ≥ 1`) and for each order after price normalisation.
- **Logging is scoreable.** `RANGE`, `SKIP <reason>`, `PLACE`, `WAIT`, `CYCLE_*` lines let an offline scorer rebuild every decision, and the research scripts depend on this.
- **Lessons were turned into fixes:** stale realized P&L (v1.01), the live-tick spread spike (v1.03), the broker session table lagging quotes (v1.05), and float noise at TargetR = 1 (v1.07).

### 3.3 Issues found (ranked)

| # | Severity | Issue | Where | Effect | Simplest fix |
| ---: | --- | --- | --- | --- | --- |
| 1 | **High (live)** — ✅ fixed v1.08 | Global-variable names omit the symbol: `CORB_<magicBase>_<yyyymm>_peak/stopped` | `Cycle.mqh` `CycleGVName` | Two instances with the same magic base on one terminal share the ratchet peak and the stopped flag. After a restart, one symbol's ratchet stop or high peak can stop the other symbol for the rest of the month | Add `_Symbol` to the name (done: `CORB_<magicBase>_<symbol>_<yyyymm>_…`) |
| 2 | **High (live)** — ✅ fixed v1.08 | `EURUSD-LON0700` and `DE40-6M-FRA` both use `InpMagicBase=26110300` | Presets | Triggers issue 1 if both run on one terminal. P&L stays separate (deals are filtered by symbol), but the cycle state does not | Give LON0700 its own base (done: `26110210`) |
| 3 | **Medium** — ✅ fixed v1.08 | Older presets don't set every input. EURUSD-NY and LON0700 lack `InpTky*`, `InpMinVolPct` and `InpTrendSideOnly`. NVDA lacks `InpTky*` and `InpTrendSideOnly`. AAPL lacks `InpTky*` | Presets | Loading a `.set` on a chart keeps the current value of any input the file omits. Loading EURUSD-NY onto a chart that last ran JP225 would leave the **Tokyo setup enabled** and the vol floor at 33. The DE40 preset comment already notes this for the tester | Regenerate every preset with the full key set |
| 4 | Medium | Pending orders are `ORDER_TIME_GTC` | `Orders.mqh` `OrdersPlaceStop` | If the terminal or VPS goes down, orders stay live after the entry window and fills can be held overnight. SL and TP stay at the broker, but the time exit is lost | Use `ORDER_TIME_SPECIFIED` with expiration `tEntryEnd` where `SYMBOL_EXPIRATION_MODE` allows it |
| 5 | Medium | Capital = `ACCOUNT_BALANCE − own realized` when `InpCycleCapital=0` | `Cycle.mqh` `CycleBegin` | With several instances or other EAs on the account, other P&L moves this instance's base and risk at each restart or month roll. The research cards mention live BMRG experts on the terminal | Set `InpCycleCapital` explicitly per instance for multi-instance use |
| 6 | Low | Sizing ignores the exit-side spread and stop-fill slippage | `OrdersLotForRisk` | Real loss at the stop is about (1 + spread / stop) × risk. With the cost cap at 10 %, that is up to ~10 % above the planned risk | Document it, or add the average spread to the SL distance in sizing |
| 7 | Low | `InpNoEntryLastDay=true` in every preset, but positions never cross midnight | `Cycle.mqh` | Drops about 1 in 21 trading days (NVDA lost 9 days in 9 months) with no risk benefit, since everything is flat before the month roll | Research question: re-score with it off. If neutral, default it off |
| 8 | Low | Init warning `built and defaulted for EURUSD` fires on every non-EURUSD symbol, and the defaults (GMT+2/+3, London+NY 08:00) are known to be wrong for YWO | `OnInit`, `Config.mqh` | Noise in the journal. A user who attaches the EA without a preset trades the wrong hours | Drop the warning. Consider making the live clock-mismatch check refuse init instead of warning |
| 9 | Info | `.ex5` timestamp (2026-11-03 23:08) is older than the sources (2026-11-04 14:40) | Folder | Probably a file sync touch, but unverified | Recompile once (F7) before the next run |
| 10 | Info | ROADMAP: task ID `ORB-P1-T10` is used twice (UK100 and MSFT), NVDA has no `ORB-P1-T06` entry, and the title still says "EURUSD" | `ROADMAP.md` | Traceability | Renumber and add NVDA |

No logic errors were found in the range build, filter order, OCO handling, DST maths, or risk/lot arithmetic.

---

## 4. Trading design analysis

### 4.1 Range

- **Skipping the opening auction is the most consistent finding across assets.** 15-minute ranges at the cash open are auction noise on DE40, JP225, UK100, US500 and TSLA. The stable windows either start 15 minutes after the open (DE40 09:15, UK100 08:15, TSLA 09:45) or cover the full first hour (JP225 09:00–10:00, US500 10:00–11:00).
- **EURUSD is the exception that proves the rule.** Its NY range ends exactly at the 08:30 US data release, and pulling the release spike into the range (a 33-minute range) flips the result. The edge is the release move.

### 4.2 Entry

- Stop orders at edge ± max(2 × spread, 5 % of range) are reasonable. Using the range-window average spread (v1.03) instead of the live tick was a measurable fix. On EURUSD it recovered 6 of 7 skipped 2R winners.
- Because there is no market-entry fallback, a breakout that happens while the EA waits on a gated session (US shares in DST) is skipped, not chased. That's the right choice for cost.

### 4.3 Stop

- An opposite-edge stop beats a mid-range stop on every asset reviewed (higher WR at similar expectancy). Mid stops were never part of a stable region.
- A wide stop (the full range) is what makes spread affordable. Cost per trade on DE40 is ~0.01–0.03R (stops 94 pt against a 0.84 pt spread). On AAPL and MSFT it is 0.10–0.28R.

### 4.4 Target and time exit

- Targets sit on flat plateaus (DE40 2.25–3.5R, JP225 1.5–4R, US500 1–4R, TSLA 1.5–4R), which is a good sign: the target isn't a tuned peak. The flat plateau is also *why* the target barely matters: the time exit does most of the work.
- Exit times sit just before each venue's close or spread widening (DE40 17:00 Frankfurt before the 17:30 widening, JP225 15:25 before the TSE close, NVDA 15:50 before the Friday session end). This detail is easy to miss and the presets get it right.

### 4.5 Regime filters

| Filter | Used on | Assessment |
| --- | --- | --- |
| Range / D1 ATR band | All | Core filter. It removes dead opens and opens that already used up the day's range. Bands differ by asset (10–40 % DE40 and US500, 25–60 % JP225, ≥ 40 % NVDA, 17.5–35 % EURUSD), which is expected: each venue's first hour is a different share of its day |
| H1 ATR percentile ≥ 33 | DE40, JP225, UK100, TSLA | Uses the framework's own tercile line, not a fitted cutoff, and ±10 % neighbours stay positive. On DE40 and UK100 this is what turns a flat ORB positive |
| D1 trend side | US500 (and AAPL research) | Turns US500 from negative to positive in all three windows. It halves trade count and makes results depend on clean index trends. On AAPL it was trend beta, not edge |
| Cost cap | All | Binding on single stocks only (NVDA, TSLA, MSFT). It never binds on the index CFDs |

All filters are **relative** (to ATR, to the vol distribution, or to the spread), so they adapt to price level and volatility. That is the right design for a multi-asset EA.

### 4.6 Sizing and the monthly cycle

This is the weakest part of the design. The machinery is fine; it's the calibration that doesn't fit.

- **The cycle was designed for ~8 % risk per trade.** At that risk, the v1.01 run showed the cycle *dominating* results. New York's apparent PF 1.37 came from ratchet stops cutting it off in bad stretches; on its own, New York was −53.6 %.
- **At the 0.5–1 % risk every preset now uses, the cycle never triggers.** The divisor cap only binds once drawdown passes ~30 % ((38 − x) / 8 < 1 ⇒ x > 30), which is exactly where the soft halt already blocks entries. The best months are +4–6.5 %, far from the +20 % ratchet arm. In effect the EA is **fixed-fractional on month-start capital**, and every research card confirms "cycle never engaged".
- **The 500 USD DE40 variant** (3 % cap) shows a second sizing problem: lot granularity. At 0.1 lot minimum, effective risk varies from 1.5 % to 3 %, and trades with stops above ~133 points are skipped (64 of 77 trades kept, Jan–Oct 2026). That quietly changes the strategy by removing wide-range days. Its offline result (+19.3 %, max DD 10.8 %) has not been tester-confirmed yet: `run_v107_DE40_FRA_500USD_2026JanOct.ini` has no report.

**Options** (a design decision, not a bug):

1. Keep the cycle as a catastrophe-only guard and say so in the ROADMAP.
2. Scale the thresholds to risk, for example soft halt ≈ 6R, hard flatten ≈ 8R, ratchet arm ≈ 8R of month profit. That makes the cycle meaningful at 1 %. It would need re-scoring, because it reintroduces path dependence.

---

## 5. Performance by asset class

Tester = YWO real-tick Strategy Tester. Mirror = offline M1 replica of `Setup.mqh` with framework costs. "Net R" is per trade after costs. Return and DD are at the preset's risk. "≈ % / month" is net R × trades per month × risk, a rough expectation only.

### 5.1 Summary table

| Asset | Class | Session / range | Source | Trades | WR | Net R | Return (DD) | ≈ % / month | Status |
| --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | --- |
| **DE40** | Index | 09:15–10:15 Frankfurt, 2.5R | Tester 17 m | 120 | 49.2 % | **+0.22** | +31.2 % (6.4 %) @1 % | ~1.6 | Research. G2 fails. **Best index result** |
| **JP225** | Index | 09:00–10:00 JST, 1.75R | Tester 17 m | 106 | 54.7 % | **+0.17** | +22.2 % (4.2 %) @1 % | ~1.1 | Research. G0 and G2 fail. **Best risk-adjusted** |
| UK100 | Index | 08:15–09:15 London, 2.5R | Mirror 10.5 m | 94 | 54.3 % | +0.32 | — (no tester) | ~2.5 | Research. n < 100. **Tester pending** |
| US500 | Index | 10:00–11:00 NY, trend side, 2R | Mirror 45 m | 225 | 57.8 % | +0.16 | — (no tester) | ~0.8 | Research. G0, G2 and MC-3 fail. **Tester pending** |
| **EURUSD (NY)** | FX | 08:00–08:30 NY, 2R | Tester 24 m | 199 | 44.7 % | **+0.20** | +45.3 % (12.5 %) @1 % | ~1.6 | Research. G0, G1 and G2 open |
| EURUSD (LON0700) | FX | 07:00–08:00 London, 3R | Tester 12 m / replica 6 y | 170 / 1,086 | 51.2 % | +0.16 / +0.10 | +14.0 % (7.3 %) @0.5 % | ~1.2 @0.5 % | Research. G1 near frontier over 6 years |
| **NVDA** | US share | 09:30–10:00 NY, ≥ 40 % ATR, 1.5R | Tester 9 m | 51 | 64.7 % | **+0.18** | +12.7 % (2.7 %) @1 % | ~1.0 | Research. n = 51 is too few for any verdict |
| TSLA | US share | 09:45–10:00 NY, 2.5R | Mirror 33 m | 258 | 47.3 % | +0.08 | — (no tester) | ~0.3 @0.5 % | Fragile. Session-dependent (fails if gated in DST) |
| AAPL | US share | 09:30–10:00 NY, research | Tester 16 m | 88 | 38.6 % | −0.19 | −4.3 % @0.5 % | < 0 | **NO-GO** |
| MSFT | US share | 09:45–10:00 NY, research | Mirror | 261 | 54.8 % | −0.01 | — | ≈ 0 | **NO-GO** |
| XOM | US share | 09:30–10:30 NY, research | Mirror | 166 | 57.2 % | −0.26 | — | < 0 | **NO-GO** (0 / 25 months positive) |

### 5.2 Index CFDs — the best fit

- **Why it works:** a real cash-open information event, deep liquidity, and a spread that is 1–3 % of the stop. Every index found a stable region once the opening auction was skipped and low-volatility days were removed.
- **DE40** has the strongest tester record (PF 1.50, 12 / 16 months positive, 12 / 12 perturbations positive, cost-stress positive at ×2). Watch item: the last 6 months are its weakest window (+0.09R per trade versus +0.31R before), and Jan–Oct 2026 offline is in the "Fragile" zone (EF 6.7 pp < M 10.9 pp).
- **JP225** has the cleanest risk profile (PF 1.76, max DD 4.2 %). Its tip is *not* weaker than its history. It trades in the Asian session, so it is the best diversifier against the European and US presets. Note the 100-lot broker cap: above ~30k USD capital at 1 %, it under-sizes.
- **UK100 and US500** look good offline but have **no tester confirmation**. The DE40 and NVDA mirrors matched their tester runs within ~0.02R. The AAPL mid-price mirror was ~0.06R optimistic, though, so the tester run still matters. 152 of US500's 225 trades come from a re-stamped, re-priced pre-2025-06 feed.

### 5.3 FX (EURUSD) — workable, thin cost headroom

- **The v1 defaults never tested the intended strategy.** The GMT+2/+3 default against a UTC+0 server shifted every window by 2–3 h. The v1.01 FAIL reviews are invalid for that reason.
- **NY 08:00–08:30**, filtered to wide pre-release ranges (≥ 17.5 % of ATR), is positive in every window (tester +0.20R over 24 months). Cost headroom ends near a 40-point round turn, so a raw-spread account with high commission could kill it.
- **LON0700** is the only preset with a **6-year** replica (n = 1,086). It is positive in all six yearly blocks on a tester-equivalent basis but sits right on the frontier (EF 2.8 pp versus M 3.0 pp). That makes it the most *honest* sample in the set, and it shows how thin a long-run ORB edge really is.
- The London 08:00 default loses on EURUSD in every dataset.

### 5.4 US single stocks — mostly no edge at this broker

- **Cost decides everything.** A flat ~0.29–0.33 USD spread is 6–16 % of a typical opening range and costs 0.10–0.37R per trade. The long-run *gross* breakout edge on AAPL, MSFT and XOM is about 0 (−0.18 to +0.04R), so no filter can rescue it. 186k–715k variants per symbol were swept with 0–4 survivors, which is chance level.
- **NVDA works only on expansion opens** (first 30 min ≥ 40 % of daily ATR). There it is a session-hold trade (78 % time exits). The sample (51 trades) is too small for any verdict.
- **TSLA is the riskiest live preset** because of the broker session table. If `Tesla` is gated to 14:30 UTC during US DST (as NVDA and Apple are), orders arm at 10:30 NY and the tip turns −0.37R per trade. Until 2027-03-08 both behaviours are identical. Watch for `WAIT NY` in the first DST week.
- AAPL, MSFT and XOM profile as mean-reverting on H1. The research correctly points them to the BMRG mean-reversion family instead.

---

## 6. Cross-asset findings — what makes CycleORB work

1. **Cost-to-range ratio is the first-order variable.** Assets where the full-range stop is ≥ 30–100 spreads (DE40, JP225, UK100, US500) work. Assets at ~10–15 spreads (US shares) only work in an expansion regime, if at all.
2. **Skip the auction, take the first hour.** Every stable cell avoids the first 15 minutes of the cash open or spans the full hour.
3. **The plain ORB is roughly zero after costs everywhere.** The edge lives in a declared regime: a normal-width range relative to ATR, plus volatility that is not low (or, on US500, trend side). That is consistent with the literature: ORB pays on days with directional information flow.
4. **Opposite-edge stop, time exit near the close, target as a cap.** This combination recurs across every positive asset.
5. **Broker plumbing matters as much as the signal.** Server clock offset, history stamped in a different timezone before 2025-06-18, session tables that lag the quotes, and data gaps (MSFT / XOM 2026-05-12 → 06-30) each invalidated or changed results at least once.

---

## 7. Robustness and evidence quality

### 7.1 Framework gate matrix (Unified Edge Framework v1.0)

| Asset | Stage 0 | G0 sample | G1 EF > M | G2 walk-fwd | G3 regime | G4 MC | G5 perturb/cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DE40 | Pass | Waived (120) | Pass | **Fail** | Pass | Pass @1 % | Pass |
| JP225 | Pass | **Fail** (106) | Pass | **Fail** (WFE 0.29) | Pass | Pass @1 % | Pass |
| UK100 | Pass | **Fail** (94) | n/a | n/a | Would pass | Would pass | Pass |
| US500 | Pass | **Fail** (225) | Pass | **Fail** (WFE 0.39) | Pass | **Fail** (MC-3) | Pass |
| EURUSD NY | Pass | **Fail** (199) | Open | Open | Pass | Pass @1 % | Mostly |
| EURUSD LON0700 | Pass | Pass (1,086) | **Fail** (near) | **Fail** | Pass | Pass @0.5 % | Pass |
| NVDA | Pass | **Fail** (51) | Indicative | **Fail** | n/a | Indicative | Pass (gated) |
| TSLA | Pass | **Fail** (258) | **Fail** | **Fail** | Pass | Pass @0.5 % | Pass |
| AAPL / MSFT / XOM | Negative | — | — | — | — | — | — |

### 7.2 Reading the evidence honestly

- **Multiple testing is the main risk.** Sweeps ran 64k–715k variants per asset. The research mitigates this well: presets are taken from the *centre of plateaus*, not peaks, and checked with ±10 % perturbations (12 / 12 to 16 / 16 positive on every positive asset). That is meaningful evidence of a stable region.
- **G2 fails on every asset with a candidate, always the same way.** Re-picking the in-sample maximum each fold chases sharp cells that collapse out of sample. The plateau presets do better per fold (DE40 4 / 4, JP225 3 / 4, US500 5 / 5 positive), but each was chosen with the whole history in view. **There is no clean out-of-sample result anywhere yet.** Only forward trading can produce one.
- **The history is short.** Real ticks on YWO start 2025-06. Most tester windows are 9–24 months, with 5–10 trades per month, so monthly numbers are noisy.
- **No news calendar** (the MT5 calendar isn't available in the tester). Several presets *depend* on scheduled events: the EURUSD 08:30 release, DE40's 10:00 EZ data slot, NVDA earnings gaps. None of them is separated in the results.

---

## 8. Risk and portfolio considerations

- **Time overlap = correlation.** DE40 and UK100 use the *identical* window (08:15–09:15 London) on two highly correlated European indices. Running both at 1 % is close to a single 2 % bet. US500, NVDA, TSLA and EURUSD-NY all trade the NY morning. JP225 is the only time-diversified preset.
- **There is no account-level risk cap.** Each instance runs its own cycle. Six instances at 1 % can put ~6 % at risk on a correlated day, and the cycle guards (dormant at 1 %) won't catch it.
- **Session and clock drift is a live risk.** The EA warns on a clock mismatch but keeps trading. A broker clock change (it has already happened at YWO) would silently shift every window.
- **Holidays and half-days.** The EA trades whenever the broker quotes. Thin CFD quotes on exchange holidays usually fail the ATR or vol filters, but this isn't guaranteed. US half-days (13:00 close) land before the 15:00–15:55 exits.

---

## 9. Recommendations

### Priority 1 — before running several instances live or on demo

1. **Add `_Symbol` to `CycleGVName`** and give `EURUSD-LON0700` its own magic base. (Issues 1 and 2. A one-line code change plus one preset edit.)
2. **Regenerate the EURUSD-NY, LON0700, NVDA and AAPL presets with every input set** (all `InpTky*`, `InpMinVolPct`, `InpTrendSideOnly`). (Issue 3.)
3. **Set `InpCycleCapital` explicitly** for every instance on a shared account. (Issue 5.)
4. **Recompile once** and confirm the journal shows `v1.07`. (Issue 9.)

### Priority 2 — evidence

5. Run the pending tester `.ini` files with the terminal closed: UK100, US500, TSLA (this also answers the session-gate question), MSFT research, and DE40-500USD.
6. Start ORB-P6-T01 demo forward tests with frozen presets on **DE40, JP225, EURUSD-NY and NVDA**. Re-score at 100 trades per asset. The compression trigger in each card (next 30–50 trades below +0.05R) is the stop rule.
7. Keep AAPL, MSFT and XOM off. Their research presets are for measuring cost models on demo, not for making money.

### Priority 3 — design (one change at a time, each re-scored)

8. **Broker-side expiry on pending orders** (`ORDER_TIME_SPECIFIED` = entry end). (Issue 4.)
9. **Re-score `InpNoEntryLastDay=false`.** Positions are intraday, so the rule probably only costs sample. (Issue 7.)
10. **Decide the cycle's role** (§4.6): document it as a catastrophe guard, or scale its thresholds to R units at 1 % risk.
11. **Portfolio rule:** don't run DE40 and UK100 together at full size. Treat them as one European-open allocation.
12. Clean up the ROADMAP: retitle it from "EURUSD", fix the duplicate `ORB-P1-T10`, add the NVDA task, and drop the EURUSD init warning.

### Out of scope (correctly)

Trailing stops, break-even moves, partial exits and re-entries remain out of scope (ROADMAP §7). Nothing in this review argues for adding them. The target barely matters, so trade management is unlikely to be where the edge is.

---

## Appendix A — Preset registry

| Preset | Symbol | Setup | Range (local) | Entry end / flat | Stop / TP | Filters | Risk | Magic base |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: |
| `EURUSD-6M-NY_chart` | EURUSD | NY | 08:00 + 30 | 11:30 / 15:00 | opp / 2.0R | ATR 17.5–35 %, cost 10 % | 1.0 % | 26110200 |
| `EURUSD-LON0700` | EURUSD | LON | 07:00 + 60 | 11:00 / 14:00 | opp / 3.0R | ATR ≥ 18 %, cost 20 % | 0.5 % | 26110210 (was 26110300) |
| `DE40-6M-FRA_chart` | DE30 | LON | 08:15 + 60 | 11:30 / 16:00 | opp / 2.5R | ATR 10–40 %, vol ≥ 33 | 1.0 % | 26110300 |
| `DE40-6M-FRA-500USD_chart` | DE30 | LON | 08:15 + 60 | 11:30 / 16:00 | opp / 2.5R | ATR 10–40 %, vol ≥ 33 | 3.0 % | 26110310 |
| `NVDA-6M-NY_chart` | NVDA | NY | 09:30 + 30 | 13:30 / 15:50 | opp / 1.5R | ATR ≥ 40 %, cost 10 % | 1.0 % | 26110400 |
| `JP225-6M-TKY_chart` | JPN225 | TKY | 09:00 + 60 | 11:30 / 15:25 | opp / 1.75R | ATR 25–60 %, vol ≥ 33 | 1.0 % | 26110500 |
| `AAPL-6M-NY-RESEARCH_chart` | Apple | NY | 09:30 + 30 | 13:30 / 15:55 | opp / 1.1R | ATR 20–80 %, trend side | 0.5 % | 26110600 |
| `TSLA-6M-NY_chart` | Tesla | NY | 09:45 + 15 | 11:30 / 15:50 | opp / 2.5R | ATR 10–40 %, cost 10 %, vol ≥ 33 | 0.5 % | 26110700 |
| `UK100-6M-LON_chart` | UK100 | LON | 08:15 + 60 | 11:30 / 16:25 | opp / 2.5R | ATR 10–50 %, vol ≥ 33 | 1.0 % | 26110800 |
| `US500-6M-NY_chart` | SPX500 | NY | 10:00 + 60 | 12:00 / 15:00 | opp / 2.0R | ATR 10–40 %, cost 15 %, trend side | 1.0 % | 26110900 |
| `XOM-6M-NY-RESEARCH_chart` | Exxon | NY | 09:30 + 60 | 11:30 / 12:00 | opp / 1.5R | ATR 40–150 %, cost 30 % | 0.25 % | 26111000 |
| `MSFT-6M-NY-RESEARCH_chart` | Microsoft | NY | 09:45 + 15 | 13:30 / 14:00 | opp / 1.0R | ATR 20–60 %, cost 10 % | 0.5 % | 26111100 |

All presets: `InpServerTZ=1`, `InpServerFixedOffsetH=0` (YWO = UTC+0), cycle defaults (30 / 38 / 20 / 10 / 0.5, divisor 8), `InpNoEntryLastDay=true`, `InpCommissionPoints=0`.

## Appendix B — Sources

- EA: `CycleORB.mq5`, `Include/Config.mqh`, `SessionClock.mqh`, `Cycle.mqh`, `Orders.mqh`, `Setup.mqh` (v1.07)
- `ROADMAP.md`, `tester/REVIEW_2026JanOct_v101.md`, `tester/REVIEW_NYonly_2025Jan_2026Oct_v101.md`
- Research cards: `Ouroboros/research/assets/{EURUSD, DE40, JP225, NVDA, UK100, US500, TSLA, AAPL, MSFT, XOM}/CycleORB_*.md`, and `DE40/cycleorb_monthly_202601_202610.json`
- Tester reports: `<data>/reports/CycleORB_*.htm` (v1.01–v1.06). There are no v1.07 reports yet.
