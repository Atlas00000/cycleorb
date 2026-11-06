# CycleORB Edge Framework

**Version:** 1.0 (2026-11-05)  
**Applies:** `doc/unified_edge_framework.md` **v1.0** (the "generic framework") to CycleORB **v1.09**  
**Built from:** `doc/CycleORB_System_Profile.md` (§1–§13) and the tester logs scored there  
**Consumed by:** `doc/genericAIOS.md` (the AI OS reads this file as its baseline: the per-asset health vectors in §5 are the numbers an AI layer must beat or hold)

This document has three jobs:

1. **Bind the generic framework to CycleORB:** the adapter declaration, the trade-event definition and the cost model (§2–§3).
2. **Fill the gaps and fix the issues** where the generic rules don't fit a low-frequency, regime-filtered, time-stopped intraday breakout. Each gap is numbered (`CO-xx`) and resolved with an explicit CycleORB override (§4).
3. **Set the per-asset benchmarks** against which every CycleORB preset, and every future AI OS layer, is scored (§5–§9).

Where this document and the generic framework disagree, **this document wins for CycleORB only**. The generic file is unchanged. Formula names and symbols are the generic ones (`WR, AW, AL, R, RR, BWR, BM, FMI, E_N, c_R, Leak, EF, M, ΔD, G, DD, MaxDD, f*, f, PF, n, WFE`). No synonyms are introduced.

A visual companion canvas exists (see §11 for its caveats).

---

## 1. The edge being benchmarked

**Strategy class:** intraday momentum / volatility-expansion breakout with a session time-stop (trend-following on an intraday horizon). It is not mean reversion.

**Mechanism:** information arrives at the cash open or at a scheduled release → the first-hour range defines the auction → a break of that range on a "trend day" tends to persist into the session → hold to a fixed exit time. The stop at the opposite edge is the natural invalidation point. Regime filters select the days on which the mechanism is likely (range not dead and not exhausted versus ATR, volatility not in the low tercile, or the D1 trend side).

**Expected signature** (System Profile §3.2). These are the class priors that every asset benchmark is checked against:

| Metric | Class prior (breakout + time-stop) |
| --- | --- |
| `WR` | 45–55 % |
| `R` | 0.55–0.85 × `RR` ≈ 1.3–1.8 |
| `BWR` | 36–44 % |
| `BM` | +5 to +17 pp |
| `E` (mean R per event) | +0.10 to +0.40R |
| `PF` | 1.3–2.0 |
| Exit mix | SL 15–45 %, TP 5–30 %, time 30–75 % |
| Median event | ≈ 0R |
| Loss tail | −1R, plus slippage to about −2.4R on releases and gaps |

**An asset whose observed vector falls outside these bands is not "better" or "worse". It is a different edge from the one the EA was designed for, and it needs an explanation before it is benchmarked.**

---

## 2. Adapter declaration (generic §8)

### 2.1 EA metadata

| Field | CycleORB value |
| --- | --- |
| `ea_name`, `ea_version` | `CycleORB`, `1.09` (printed in the `Init OK v1.09 …` journal line) |
| `designed_rr` | Per preset `InpTargetR` (1.5–3.0) |
| `risk_definition` | **Hard stop.** 1R = \|planned entry − initial stop\| × filled volume × point value. The stop is the opposite range edge (`InpStopMode=0` on every preset) |
| `regime_filtered` | **true.** Declared filters per asset in §5.1. CycleORB never trades the low-volatility tercile (where `InpMinVolPct=33`) or ranges outside its ATR band |
| `baseline_frequency` | Per asset in §5.2 (events per 90 days) |
| `costs_defaulted` | `slippage` only (see §3). Spread is measured inside the tester fills. Commission is 0 at YWO. Swap is 0 (intraday, except failed exits) |

### 2.2 Trade-event definition (generic §1.3 applied)

| Situation | Rule |
| --- | --- |
| One setup, one local day, one side filled | **One event** |
| OCO side that never filled | Not an event. Counted in the fill-rate statistic ("armed days → filled days") |
| Both OCO sides filled between two ticks (whipsaw) | **One event** (`event_id` = magic + exchange-local date). `pnl_R` is the sum of both legs over the single declared 1R |
| Order skipped (filter, lot below minimum, skip date) | Not an event. Logged as a `SKIP` reason and counted in the funnel |
| Position closed late (market closed at the exit time) | Same event. Swap and gap are charged to it. Flagged `CALENDAR_LEAK` (CO-17) |

### 2.3 Blotter source

CycleORB does not yet emit the generic CSV blotter. **The adapter is the journal parser**: `PLACE` / `order … triggered` / `deal …` / `stop loss` / `take profit` / `close #` lines rebuild every leg, and `RANGE` lines tag each event with range/ATR %, average spread and trend side. A native CSV logger is an AI OS L6 (Memory / Ledger) task.

---

## 3. Cost model binding (generic §4.1)

The tester fills already sit at bid/ask, so **the spread is inside `pnl_R`**. Subtracting it again would double-count (CO-04). For CycleORB:

```
BM        = WR − BWR                        computed from net-of-spread tester fills
c_spread  = avg range-window spread / 1R    reported only (already in BM)
c_slip    = 0.5 × spread × (market legs) / 1R
            market legs = 1 (stop entry) + 1 if the exit is SL or time; a TP exit is a limit order (0)
Leak      = mean(c_slip) / (R + 1)
EF        = BM − Leak
c_R       = c_spread + c_slip                used for the cost stress (G5)
```

The slippage prior is the generic default and is deliberately conservative: the tester already contains real-tick gap slippage on stops. Measured live slippage replaces the prior after 40 forward events.

---

## 4. Gaps and issues in the generic framework, and the CycleORB resolutions

The generic framework is written for a strategy-independent EA population with abundant events. CycleORB trades 5–12 events per month per asset, on a broker whose real-tick history starts in 2025-06, inside declared regime filters, with a time-stop. The table lists every place where the generic rule is unfit, ambiguous or silent, and the override this profile uses.

| # | Generic rule | Issue for CycleORB | CycleORB resolution |
| --- | --- | --- | --- |
| **CO-01** | §5.2 tiers: `n < 100` = no verdicts; `n ≥ 385` to pass G1–G3; G0 needs ≥ 385 | At 5–12 events/month, 385 events take 3–6 years. Real-tick history is 16 months. The rule blocks every asset forever | **Sample tiers are evidence labels, not gates.** Uncertainty is carried by `M` (Wilson), the bootstrap CI of `R`, fold consistency and the forward test. Labels: < 50 Indicative · 50–149 Provisional · ≥ 150 Established · ≥ 385 Standard |
| **CO-02** | §5.1 windows W100 / W250 / W500, step 25 events | Equal to 1–8 years of CycleORB trading. Lifecycle could never be evaluated | **W20 (fast), W40 (decision), W80 (confirm)**, evaluated at every month end. W20 never triggers action alone |
| **CO-03** | §5.5 lifecycle keys on `EF > M` and `ΔD` ±1 pp | At W40, `M ≈ ±15 pp`, so `EF > M` is unreachable and every asset would sit permanently in "Near frontier". `ΔD` noise at W40 is ≈ ±10 pp, so ±1 pp is pure noise | Lifecycle uses the **sign of `EF`** and **changes in `E` versus the validation baseline** (§6.1). `M` is used only for the full-sample production gate. A `ΔD` move counts only at ≥ 5 pp |
| **CO-04** | §4.1 cost model: subtract all costs from gross BM | Tester fills already include spread. Applying `spread_cost` again double-counts | `BM` from net fills. `Leak` = unmeasured slippage only (§3). Spread is reported as `c_spread` for drift monitoring and stress tests |
| **CO-05** | §4.1 slippage default "0.5 × spread per market-order leg" | Silent on stop entries and stop exits | Stop entry = market leg. SL exit = market leg. Time exit = market leg. TP = limit (0). Release days (NFP, CPI) slip far beyond the prior (−2.4R observed). Covered by the tail monitor (§6.2), not the prior |
| **CO-06** | §1.3 event = one decision | Silent on OCO brackets | §2.2: one setup-day = one event. Unfilled sides are funnel statistics, not events |
| **CO-07** | §1.1 1R in account currency at entry | Lot rounding (0.01–0.1 steps) makes the actual currency risk differ from `CycleRiskMoney()` by up to 50 % on small accounts | `pnl_R` is computed in **price units** against the planned stop distance, which is independent of lot rounding. `risk_ccy` in the manifest = actual volume × stop × value. Divergence is tracked as a sizing leak (CO-08) |
| **CO-08** | §4.2 leak taxonomy L1–L5 | No category for **sizing / granularity leak**: events skipped because the minimum lot exceeds the risk budget (UK100 at 500 USD lost 41 of 98 armed days, and they were the wide-range days), and `f` dispersion between events | New **L6 Sizing leak**, monitored, not subtracted: share of armed sides skipped `lot < min` (gate: ≤ 10 %), and the effective-`f` range. A preset scored with L6 > 10 % is a different strategy and is not benchmarkable at that account size |
| **CO-09** | §4.5 regime tags: ATR(20) percentile tercile and 50-period ER; cells need `n ≥ 30` | (a) Timeframe unspecified. (b) CycleORB never trades the low-vol tercile by design, so cells collapse. (c) `n ≥ 30` per cell is unreachable | Tags: **range/ATR tercile within the traded set** (narrow / mid / wide), **side** (long / short), **trend side** where logged. Timeframe: H1 at range end. Qualifying cell: `n ≥ 15`. `regime_filtered = true`, so the 70 % concentration rule is reported, not gated (generic §4.5 exemption). `BM_worst > 0` is still required |
| **CO-10** | §7.2 G2 anchored walk-forward: re-select parameters each fold, OOS ≥ 6 months, ≥ 4 folds | Needs ≥ 2 years of OOS beyond IS. History is 16 months. The research-side WF (Ouroboros mirrors) failed on every asset by chasing sharp IS peaks | **G2a fixed-preset fold consistency:** 4 contiguous folds of the tester sample, `E > 0` in ≥ 3/4. **G2b:** research WF is reported, not gated. **G2c:** the **forward test is the only clean OOS** and is required for live promotion (§7) |
| **CO-11** | §7.3 MC-2 block length 20 | With n = 70–124, 20-event blocks leave 4–6 blocks per path: no resampling diversity | Block = **10 events** (≈ 1–2 months of trading). MC-1 shuffle is reported for drawdown only, because its terminal equity is order-invariant |
| **CO-12** | §7.3 MC-3 stress shrinks `WR` by `M` | With `M ≈ 9–11 pp`, MC-3 re-tests "is `EF > M`". Its median terminal falls below `C_0` exactly when G1 is Fragile, at any `f` | MC-3 is read as an **edge test**, gated only at live promotion. Its **P(ruin)** stays a sizing test at every stage |
| **CO-13** | §6.5 operate at ¼–½ Kelly of the pessimistic edge (`WR − M`) | Small n makes pessimistic Kelly tiny (EURUSD-NY 0.9 %), and lot granularity makes `f` non-continuous on a 500–1000 USD account | `f_max = min(½ f*_pess, f_DD25)`, where `f_DD25` is the `f` at which MC-2 P95 MaxDD = 25 %. Presets above `f_max` are flagged `OVER_SIZED`. A small-account **lot-minimum exception** is allowed only if documented (DE40, §8) |
| **CO-14** | §6.4 DD limit per EA | CycleORB runs several symbols in correlated session buckets. Per-EA limits ignore portfolio heat (DE40–UK100 daily ρ = 0.67) | Portfolio layer (§9): bucket caps, concurrent heat cap, portfolio MC |
| **CO-15** | §5.1 `FREQUENCY_STALL`: 90-day events < 50 % of baseline | Regime filters produce natural dry spells (DE40: 2 events in Aug 2026. US500 skips about 45 % of evaluated days on the ATR band) | Stall = 90-day events < 50 % of baseline **and** the armed-day rate also < 50 % of its baseline (filters stopped arming = market change). If days are armed but not filled, that is a fill-rate issue, not a stall |
| **CO-16** | §3.4 / §9.2 `RR − R` gap trigger "+25 % versus baseline" | The gap is structural (the target is a cap). On JP225 the gap is 0.12, so +25 % is 0.03R: pure noise | Trigger on **`R_W40 <` the bootstrap lower bound of `R`** (full sample), not on relative gap growth. The gap is reported |
| **CO-17** | §4.2 L1 execution leak | Silent on **calendar / session failures**: exits impossible because the market closed early (US500 2026: a Juneteenth position held over a weekend, −2.23R; 18,836 failed closes) | New **`CALENDAR_LEAK`** check: 0 failed exits and 0 overnight holds per window. Skip-date lists (`InpSkipDates`) must cover every traded year. Any hit → execution audit before any parameter change |
| **CO-18** | Generic EA is static between months | CycleORB's monthly capital cycle (soft halt −30 %, hard flatten −38 %, ratchet +20 %) makes sizing path-dependent | At the operating `f` (0.5–3 %) the cycle never engaged in any scored asset-month (2025-07 → 2026-10). MC ignores it (conservative). Re-model only if `f` > 3 % |
| **CO-19** | §7.5 verdict: production-worthy = all gates, "no partial passes" | Too binary for iterative work. The AI OS (`genericAIOS.md`) needs a looser experiment bar | **Promotion ladder** (§7): Research → Forward-eligible → Live-eligible → Scale. "No partial passes" applies *within* each rung |
| **CO-20** | §8.3 "version changes reset live baselines" | v1.09 only adds skip dates and retry backoff. Assets with empty skip lists (EURUSD, JP225) behave identically | A version change resets an asset's baseline **only if it changes that asset's events**. Verify with a tester re-run diff (same events = baseline kept) |
| **CO-21** | §3.5 `TAIL_RISK` via loss skewness < −2 or max loss > 15 % of GP | CycleORB losses are bounded near −1R. The real tail is execution (news slippage, gaps), which these statistics don't catch at small n | Keep the generic test (all assets pass) **and** add the tail monitor: losses < −1.2R per W40 (§6.2) |
| **CO-22** | No portfolio-of-setups view | Sessions overlap: EURUSD-NY, US500, NVDA and TSLA all trade the NY morning | Covered by §9 |

---

## 5. Per-asset baselines (validation vectors)

> **Update 2026-11-06 (AOS-P0).** The authoritative baseline is now `tools/aos_baseline.json`: every asset on v1.09, 1000 USD, 2025-07-01 → 2026-10-31. The tables below keep the 2026-11-05 vectors for reference. Changes versus them:
>
> - **EURUSD-NY:** n 146, `E` +0.263R, `EF` +9.3 pp > `M` 8.0, so **Fragile → Robust**. `f_max` 1.90 %: no longer `OVER_SIZED` at 1 %.
> - **EURUSD-LON0700:** n 191, `E` +0.134R, `EF` +5.3 pp, `M` 7.0, Fragile. The pessimistic Kelly is 0, so `f_max` = 0 and the 0.5 % preset is `OVER_SIZED`.
> - **JP225:** n 102, `E` +0.203R, `EF` +14.5 pp, `M` 9.5, Robust. `f_max` 4.6 %.
> - **Negative controls** (AAPL / MSFT / XOM) are now scored: all Negative after costs (`EF` −12.4 / −2.0 / −51.4 pp).
>
> DE40, UK100 and US500 are unchanged (they were already v1.09). Details: `doc/ai_OS.md` §2 and "AOS-P0 results".

### 5.1 Asset registry and evidence source

| Asset key | Preset | Session (local) | Declared regime filter | Designed RR | Evidence (baseline sample) | Operating `f` |
| --- | --- | --- | --- | ---: | --- | ---: |
| **EURUSD-NY** | `CycleORB-M5-EURUSD-6M-NY` | NY 08:00 + 30 (pre-release), flat 15:00 | Range/ATR 17.5–35 %, cost ≤ 10 % | 2.0 | v1.08 tester 2026-01-01 → 10-31 @ 500 USD | 1.0 % |
| **EURUSD-LON0700** | `CycleORB-M5-EURUSD-LON0700` | LON 07:00 + 60, flat 14:00 | Range/ATR ≥ 18 %, cost ≤ 20 % | 3.0 | v1.08 tester 2026-01-01 → 10-31 @ 500 USD | 0.5 % |
| **DE40** | `CycleORB-M5-DE40-6M-FRA-500USD` | FRA 09:15 + 60, flat 17:00 | Range/ATR 10–40 %, H1 vol ≥ 33 | 2.5 | **v1.09** tester 2025-07-01 → 2026-10-31 @ 1000 USD | 2.5 % (3 % cap, lot minimum) |
| **JP225** | `CycleORB-M5-JP225-6M-TKY` | TKY 09:00 + 60, flat 15:25 | Range/ATR 25–60 %, H1 vol ≥ 33 | 1.75 | v1.08 tester 2026-01-01 → 10-31 @ 500 USD | 1.0 % |
| **UK100** | `CycleORB-M5-UK100-6M-LON` | LON 08:15 + 60, flat 16:25 | Range/ATR 10–50 %, H1 vol ≥ 33 | 2.5 | **v1.09** tester 2025-12-17 → 2026-10-31 @ 1000 USD | 1.0 % |
| **US500** | `CycleORB-M5-US500-6M-NY` | NY 10:00 + 60, flat 15:00 | Range/ATR 10–40 %, cost ≤ 15 %, **D1 SMA20 trend side** | 2.0 | **v1.09** tester 2025-07-01 → 2026-10-31 @ 1000 USD | 1.0 % |

Assets without a benchmarkable tester blotter are in §10.

### 5.2 Health vector (generic §5.3, full baseline sample)

| Field | EURUSD-NY | LON0700 | DE40 | JP225 | UK100 | US500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `n` (label, CO-01) | 95 (Prov.) | 124 (Prov.) | 120 (Prov.) | 77 (Prov.) | 88 (Prov.) | 71 (Prov.) |
| Months of data | 9.8 | 9.9 | 15.5 | 9.7 | 9.2 | 15.5 |
| Events / 30 d | 9.7 | 12.5 | 7.7 | 8.0 | 9.6 | 4.6 |
| `WR` | 48.4 % | 52.0 % | 49.2 % | 51.9 % | 52.3 % | 56.3 % |
| `AW` / `AL` | 1.51 / 0.93 | 1.15 / 0.84 | 1.41 / 0.90 | 0.80 / 0.49 | 1.52 / 0.84 | 1.01 / 0.67 |
| `R` [95 % bootstrap CI] | 1.63 [1.36, 1.94] | 1.38 [1.11, 1.71] | 1.57 [1.28, 1.89] | 1.63 [1.15, 2.34] | 1.82 [1.48, 2.21] | 1.51 [1.14, 2.01] |
| `RR` / `RR − R` | 2.0 / 0.37 | 3.0 / 1.62 | 2.5 / 0.93 | 1.75 / 0.12 | 2.5 / 0.68 | 2.0 / 0.49 |
| `BWR` | 38.0 % | 42.0 % | 38.9 % | 38.0 % | 35.5 % | 39.8 % |
| `BM` | +10.4 pp | +10.0 pp | +10.2 pp | +14.0 pp | +16.8 pp | +16.5 pp |
| `FMI` | 0.27 | 0.24 | 0.26 | 0.37 | 0.47 | 0.42 |
| `E` (R / event) | +0.254 | +0.198 | +0.235 | +0.180 | +0.396 | +0.279 |
| `E_N` (AL units) | +0.273 | +0.238 | +0.263 | +0.369 | +0.472 | +0.416 |
| `PF` | 1.53 | 1.50 | 1.52 | 1.77 | 1.99 | 1.95 |
| `c_spread` (in fills) | 0.040R | 0.036R | 0.014R | 0.017R | 0.032R | 0.025R |
| `c_slip` (prior) | 0.034R | 0.035R | 0.013R | 0.016R | 0.029R | 0.023R |
| `Leak` | 1.3 pp | 1.5 pp | 0.5 pp | 0.6 pp | 1.0 pp | 0.9 pp |
| **`EF`** | **+9.1 pp** | **+8.5 pp** | **+9.7 pp** | **+13.4 pp** | **+15.7 pp** | **+15.6 pp** |
| **`M`** (Wilson 95 %) | 9.9 pp | 8.7 pp | 8.8 pp | 10.9 pp | 10.2 pp | 11.2 pp |
| **Stage 1 zone** | **Fragile** (EF/M 0.92) | **Fragile** (0.98) | **Robust** (1.10) | **Robust** (1.23) | **Robust** (1.54) | **Robust** (1.39) |
| Binomial p (`WR > BWR + Leak`) | 0.045 | 0.042 | 0.019 | 0.012 | 0.002 | 0.006 |
| Exit mix SL / TP / time | 43 / 28 / 28 % | 36 / 6 / 58 % | 41 / 15 / 44 % | 14 / 10 / 75 % | 35 / 17 / 48 % | 21 / 13 / 66 % |
| Time-exit mean | +0.56R | +0.67R | +0.62R | +0.19R | +0.69R | +0.36R |
| Worst event | −2.40R (NFP) | −1.06R | −1.41R | −1.03R | −1.13R | −1.05R |
| Loss streak obs. / expected | 5 / 6.9 | 7 / 6.6 | 5 / 7.1 | 7 / 5.9 | 7 / 6.1 | 7 / 5.1 |
| Closed-trade MaxDD (at `f`) | 4.7 % | 4.4 % | 13.8 % | 3.7 % | 5.2 % | 4.7 % |

**Reading the vector against the class priors (§1):** all six sit inside the breakout + time-stop bands. JP225 is the outlier inside the band: `AL` 0.49 and 75 % time exits make it a *session-drift* edge more than a breakout edge, so its monitoring keys on the time-exit mean, not the TP share. LON0700's `RR − R` gap of 1.62 shows a target that is never the exit (6 % TP), so its edge is pure session drift.

### 5.3 Regime and tag cells (CO-09: qualifying `n ≥ 15`)

`BM` per cell (pp) / mean R per event:

| Cell | EURUSD-NY | LON0700 | DE40 | JP225 | UK100 | US500 |
| --- | --- | --- | --- | --- | --- | --- |
| Range/ATR narrow | +6.3 / +0.16 | +8.4 / +0.19 | +17.7 / +0.48 | +16.3 / +0.25 | +25.1 / +0.62 | +17.7 / +0.33 |
| Range/ATR mid | +12.8 / +0.35 | +6.1 / +0.12 | +3.7 / +0.08 | +9.5 / +0.13 | +5.4 / +0.13 | +25.5 / +0.37 |
| Range/ATR wide | +12.2 / +0.25 | +16.9 / +0.28 | +7.4 / +0.14 | +16.6 / +0.17 | +19.4 / +0.44 | +7.2 / +0.15 |
| Long | +6.7 / +0.17 | +12.1 / +0.26 | **+0.7 / +0.02** | +19.7 / +0.25 | +21.7 / +0.50 | +14.9 / +0.24 |
| Short | +14.1 / +0.33 | +7.1 / +0.13 | +18.3 / +0.45 | +6.8 / +0.09 | +12.1 / +0.30 | n = 12 (not qualifying) |
| **`BM_worst`** | **+6.3** | **+6.1** | **+0.7** | **+6.8** | **+5.4** | **+7.2** |
| Best-cell share of net R (range / side) | 45 % / 68 % | 48 % / 70 % | 68 % / **97 %** | 44 % / 78 % | 51 % / 63 % | 43 % / 72 % |

**G3 result: every asset has `BM_worst > 0`.** Flags:

- **DE40:** the long side is at the frontier (+0.7 pp), and 97 % of net R comes from shorts. Its edge has become one-sided.
- **JP225 and US500:** long-heavy, which is partly index beta in a rising year (System Profile §3.3).

---

## 6. Stage 2 — health monitoring benchmarks

### 6.1 Lifecycle (CO-02, CO-03)

These rules are evaluated at each month end on W40, with W80 as confirmation. `E_base` is the §5.2 baseline `E`.

| State | Condition | Action |
| --- | --- | --- |
| **Expanding** | `EF_W40 > 0` and `E_W40 ≥ E_base + 0.10R` at 2 consecutive month ends | None. Note for the sizing review |
| **Stable** | `EF_W40 > 0` and `E_W40` within ±0.10R of `E_base` | Routine |
| **Compressing** | `EF_W40 > 0` and `E_W40 ≤ E_base − 0.10R` at 2 consecutive month ends, or `ΔD ≤ −5 pp` | Investigation (generic §9.3 order: data → execution → regime → structure) |
| **Near frontier** | `EF_W40 ≤ 0`, `EF_W80 > 0` | Halve `f` (or skip, if the lot minimum makes halving impossible) |
| **Below frontier** | `EF_W40 ≤ 0` and `EF_W80 ≤ 0` (or the full sample if n < 80) | `f = 0`. Rediscovery (generic §9.4) |

**Current state (end of the sample):**

| Asset | `EF` W20 / W40 / W80 | `E` W40 vs base | `ΔD` (W40 vs previous W40) | **State** |
| --- | --- | --- | --- | --- |
| EURUSD-NY | +6.9 / +9.8 / +10.6 pp | +0.27 vs +0.25 | −1.7 pp | **Stable** |
| EURUSD-LON0700 | +23.1 / +17.0 / +16.3 pp | +0.36 vs +0.20 | +1.4 pp | **Expanding** (first evaluation) |
| DE40 | **−2.2** / +3.1 / +6.0 pp | **+0.08 vs +0.24** | **−5.2 pp** | **Compressing**: investigation open |
| JP225 | +3.6 / +10.5 / — | +0.14 vs +0.18 | — (n < 80) | **Stable**, W20 weak |
| UK100 | +19.1 / +13.5 / +12.4 pp | +0.32 vs +0.40 | +2.2 pp | **Stable** |
| US500 | +12.8 / +14.1 / — | +0.25 vs +0.28 | — (n < 80) | **Stable** |

### 6.2 Trigger thresholds per asset (generic §9.2, with CO overrides)

| Trigger | Rule | EURUSD-NY | LON0700 | DE40 | JP225 | UK100 | US500 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| WR floor (EF = 0 at baseline R) | `WR_W40 < BWR + Leak` → Near frontier | 39.3 % | 43.5 % | 39.4 % | 38.6 % | 36.5 % | 40.7 % |
| Compressing line | `E_W40 ≤ E_base − 0.10R` | +0.15R | +0.10R | +0.14R | +0.08R | +0.30R | +0.18R |
| Payoff break (CO-16) | `R_W40 <` bootstrap low | 1.36 | 1.11 | 1.28 | 1.15 | 1.48 | 1.14 |
| SL-share ceiling | baseline + 15 pp | 58 % | 51 % | 56 % | 29 % | 50 % | 36 % |
| Time-exit decay | mean time-exit R over W40 ≤ 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Cost drift | `c_spread_W40 > 1.5 ×` baseline | 0.060R | 0.054R | 0.021R | 0.026R | 0.048R | 0.038R |
| Tail monitor (CO-21) | losses < −1.2R per W40 | > 3 | > 2 | > 3 | > 2 | > 2 | > 2 |
| `DEPENDENCE` | loss streak > ⌈1.5 × expected⌉ | 11 | 10 | 11 | 9 | 10 | 8 |
| `FREQUENCY_STALL` (CO-15) | 90-day events below, with armed days also < 50 % | 14 | 18 | 11 | 12 | 14 | 7 |
| `CALENDAR_LEAK` (CO-17) | failed exits or overnight holds | any | any | any | any | any | any |
| Sizing leak L6 (CO-08) | armed sides skipped `lot < min` | > 10 % | > 10 % | > 10 % | > 10 % | > 10 % | > 10 % |
| DD alarm | live DD ≥ 0.8 × asset DD limit (§8) | 8 % | 9 % | 20 % | 8 % | 10 % | 8 % |

### 6.3 Rolling-window reference series

These are rolling-20 expectancy (R) sampled at month ends. They are the baseline shape a live W20 should resemble (System Profile §7 and §13):

| Asset | Path (oldest → newest) | Min | Last |
| --- | --- | ---: | ---: |
| EURUSD-NY | +0.54 → +0.54 → +0.30 → +0.03 → +0.19 → +0.36 → +0.33 → +0.39 → +0.21 | −0.08 | +0.21 |
| EURUSD-LON0700 | −0.44 → −0.26 → +0.18 → +0.37 → −0.07 → +0.91 → +0.48 → +0.17 → +0.55 | −0.55 | +0.55 |
| DE40 | +0.33 → +0.17 → +0.15 → +0.30 → +0.53 → +0.57 → +0.31 → +0.11 → +0.01 → +0.13 → +0.17 → +0.26 → −0.15 → −0.03 | −0.25 | −0.03 |
| JP225 | +0.21 → +0.15 → +0.08 → +0.39 → +0.28 → +0.20 → +0.02 → +0.05 | +0.02 | +0.05 |
| UK100 | +0.49 → +0.15 → +0.25 → +0.59 → +0.28 → +0.20 → +0.17 → +0.44 | −0.08 | +0.44 |
| US500 | +0.19 → +0.39 → +0.43 → +0.51 → +0.48 → +0.30 → +0.30 → +0.25 → +0.37 → +0.32 → +0.32 → +0.18 → +0.25 | +0.15 | +0.25 |

**Normal noise:** a 20-event window of this edge class swings by about ±0.3R around its mean. That is why W20 never triggers action.

---

## 7. Stage 4 — gates and the promotion ladder (CO-19)

### 7.1 Rungs

| Rung | Meaning | Requires |
| --- | --- | --- |
| **R0 Research** | Preset exists, logic sound | — |
| **R1 Forward-eligible** | May run on demo with a frozen preset | G0′, G1′ (`EF > 0`), G2a, G3′, G4′ (MC-2 at `f`), G5′ |
| **R2 Live-eligible** | May run live at `f ≤ f_max` | R1 + ≥ 40 forward events with `E > 0` and `EF > 0`, **combined (tester + forward) `EF > M`**, MC-3 median terminal ≥ `C_0`, 0 `CALENDAR_LEAK` |
| **R3 Scale** | May raise `f` toward `f_max` | R2 + ≥ 100 forward events with `EF > M` on forward data alone |

### 7.2 Gate definitions (CycleORB versions)

| Gate | Generic | CycleORB version |
| --- | --- | --- |
| G0′ | Blotter, costs, n ≥ 385 | Journal adapter complete (every `PLACE` matched to a fill or a cancel), version pinned in `Init OK`, costs per §3, **L6 sizing leak ≤ 10 %**. No n gate (CO-01) |
| G1′ | `EF > M` (full and W500), binomial, R bootstrap | R1: `EF > 0`, binomial p < 0.05, `BWR(R_low) < WR − Leak`. **R2: `EF > M` on the combined sample** |
| G2a | Anchored WF with re-selection | 4 contiguous folds of the frozen preset, `E > 0` in ≥ 3/4 (CO-10). Research WF reported |
| G3′ | `BM_worst > 0`, concentration ≤ 70 % | `BM_worst > 0` on qualifying cells (n ≥ 15). Concentration reported (regime-filtered) |
| G4′ | MC-2 P95 MaxDD ≤ 25 %, median G > 0, ruin ≤ 1 %. MC-3 ruin ≤ 5 % and median ≥ `C_0` | MC-2 (block 10) at the operating `f`: P95 MaxDD ≤ **asset DD limit**, median terminal > 1, ruin ≤ 1 %. MC-3: ruin ≤ 5 % (R1). Median terminal ≥ 1 (R2) |
| G5′ | ±10 % perturbation, cost ×1.5 | Perturbation taken from the research cards (12/12–16/16 positive). **`EF > 0` at cost ×1.5** (gated), ×2.0 reported |

### 7.3 Gate matrix (baseline samples)

| Gate | EURUSD-NY | LON0700 | DE40 | JP225 | UK100 | US500 |
| --- | --- | --- | --- | --- | --- | --- |
| G0′ (L6 ≤ 10 %) | Pass (0 %) | **Fail at 500 USD** (34 of 296 sides = 11 %) | Pass at 1000 USD (0 %) | Pass | Pass at 1000 USD (0 %), **fail at 500** | Pass |
| G1′ R1 (`EF > 0`, p, R_low) | Pass | Pass | Pass | Pass | Pass | Pass |
| G1′ R2 (`EF > M`) | **Fail** (9.1 < 9.9) | **Fail** (8.5 < 8.7) | Pass (9.7 > 8.8) | Pass | Pass | Pass |
| G2a folds `E > 0` | 4/4 (+0.21, +0.22, +0.31, +0.27) | 3/4 (**−0.30**, +0.09, +0.61, +0.40) | 4/4 (+0.27, +0.48, +0.06, +0.14) | 4/4 (+0.33, +0.14, +0.22, +0.05) | 4/4 (+0.75, +0.38, +0.16, +0.30) | 4/4 (+0.08, +0.52, +0.27, +0.26) |
| G3′ `BM_worst` | +6.3 pp | +6.1 pp | **+0.7 pp** (marginal) | +6.8 pp | +5.4 pp | +7.2 pp |
| G4′ MC-2 P95 DD @ `f` | 7.5 % | 9.1 % | **23.6 %** | 6.0 % | 10.4 % | 7.3 % |
| G4′ MC-2 median terminal | 1.35 | 1.13 | 1.92 | 1.17 | 1.37 | 1.22 |
| G4′ MC-3 ruin / median terminal | 0 % / **0.97** | 0 % / **0.97** | **3.5 % / 0.86** | 0 % / 1.01 | 0 % / 1.03 | 0 % / 1.01 |
| G5′ `EF` @ cost ×1.5 / ×2.0 | +7.7 / +6.3 pp | +7.1 / +5.6 pp | +9.2 / +8.7 pp | +12.8 / +12.1 pp | +14.7 / +13.6 pp | +14.6 / +13.7 pp |
| `TAIL_RISK` (generic) | No (max loss 3.4 % of GP) | No | No | No | No | No |
| **Rung** | **R1** (Fragile: `f` halved, §8) | **R0 at 500 USD** (L6). Expected R1 once re-scored at ≥ 1000 USD (not yet run) | **R1 with sizing exception**, Compressing | **R1**, R2 pending forward | **R1 at ≥ 1000 USD**, R2 pending forward | **R1**, R2 pending forward |

**No asset is R2 yet**, because every R2 requires the forward test. **JP225, UK100 and US500 already meet every non-forward R2 condition.**

---

## 8. Stage 3 — sizing and survival benchmarks

| Asset | Operating `f` | Full Kelly `f*` (binary) | Pessimistic Kelly (`WR − M`) | ½ pessimistic | `f_DD25` (MC-2) | **`f_max` (CO-13)** | Asset DD limit | MC-2 median ann. G @ `f` | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EURUSD-NY | 1.0 % | 16.8 % | 0.9 % | 0.45 % | 3.6 % | **0.45 %** | 10 % | +45 % | **`OVER_SIZED`** → run at 0.5 % until combined `EF > M` |
| EURUSD-LON0700 | 0.5 % | 17.3 % | 2.3 % | 1.15 % | 1.4 % | **1.15 %** | 11 % | +16 % | OK |
| DE40 | 2.5 % | 16.7 % | 2.3 % | 1.15 % | 2.7 % | **1.15 %** | 25 % | +65 % | **`OVER_SIZED`** (lot-minimum exception, below) |
| JP225 | 1.0 % | 22.6 % | 5.0 % | 2.5 % | 4.5 % | **2.5 %** | 10 % | +21 % | OK, headroom |
| UK100 | 1.0 % | 26.0 % | 10.1 % | 5.0 % | 2.6 % | **2.6 %** | 13 % | +51 % | OK, headroom |
| US500 | 1.0 % | 27.5 % | 8.8 % | 4.4 % | 3.6 % | **3.6 %** | 10 % | +17 % | OK, headroom |

**Asset DD limit** = max(10 %, 1.25 × MC-2 P95 MaxDD at `f`), capped at the generic 25 %. **DD alarm** = 0.8 × that limit (§6.2).

**DE40 lot-minimum exception.** At 0.1 lot, DE40 risks about 0.116 USD per index point. Its stops run 50–220 points, so the minimum trade risks 5.8–25.5 USD. Holding `f ≤ f_max` (1.15 %) without skipping wide-range days needs about **2,200 USD**. At 500–1000 USD the choices are:

- (a) accept `f` ≈ 2–2.5 %, documented here as an exception;
- (b) cap at 2 % (MC-2 P95 DD 18.9 %, MC-3 ruin 0.6 %), accepting some skipped wide days (L6 rises);
- (c) wait for the account to reach about 2.2k USD.

Monte Carlo of DE40 by `f`:

| `f` | MC-2 P95 DD | MC-2 median terminal | MC-3 P95 DD | MC-3 ruin | MC-3 median terminal |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1.0 % | 9.7 % | 1.33 | 24.3 % | 0.0 % | 0.95 |
| 1.5 % | 14.4 % | 1.51 | 34.6 % | 0.0 % | 0.92 |
| 2.0 % | 18.9 % | 1.71 | 43.3 % | 0.6 % | 0.89 |
| 2.5 % | 23.5 % | 1.92 | 51.1 % | 3.5 % | 0.86 |
| 3.0 % | 27.8 % | 2.17 | 58.3 % | 10.0 % | 0.83 |

**Recommendation:** use option (b), **2 % cap at 1000 USD**, while DE40 is in the Compressing state. Return to the preset's 3 % cap only if the state returns to Stable.

---

## 9. Portfolio layer (CO-14, CO-22)

| Bucket | Members | UTC window (approx.) | Measured ρ (daily R) | Rule |
| --- | --- | --- | --- | --- |
| Asia | JP225 | 00:00–06:25 | ≈ 0 to everything | Independent. Best diversifier |
| Europe pre-open | EURUSD-LON0700 | 06:00–13:00 | −0.20 to +0.12 | Independent |
| **Europe open** | **DE40, UK100** | 07:15–15:25 | **0.67** | **One allocation:** combined `f` ≤ max single `f_max` (≤ 2.6 %) |
| US morning | EURUSD-NY, US500 (+ NVDA, TSLA if promoted) | 12:00–20:00 | −0.17 to +0.47 (n ≤ 23) | Combined concurrent `f` ≤ 2 % |

**Portfolio rules:**

- **Concurrent heat cap:** the sum of `f` across positions open at the same time ≤ **3 %**.
- **Portfolio DD limit:** 25 % (generic default), checked by MC-2 on the merged event stream ordered by time.
- **Portfolio alarm:** live DD ≥ 20 % → halve every `f`.

All six presets at 1R each over 2026 Jan–Oct gave 458 events, E +0.21R, closed-trade max DD 10.7R, and 8/10 months positive (System Profile §8).

---

## 10. Assets without a benchmark vector

| Asset | Status | Best evidence (System Profile / v1.07 review) | What is needed for a §5 vector |
| --- | --- | --- | --- |
| NVDA | R0 Research | Tester 9 months: 51 events, WR 64.7 %, +0.18R, 78 % time exits, RR 1.5 | v1.09 tester run (with US skip dates) over the longest window. Watch the cost cap (spread 0.29–0.33 USD) |
| TSLA | R0 Research, **broker-session dependent** | Mirror 33 months: 258 events, WR 47.3 %, +0.08R. Generic EF 4.1 < M 6.1 (Fragile) | v1.09 tester run. Confirm `WAIT NY` behaviour in the first US DST week (2027-03-08) |
| AAPL, MSFT, XOM | **Rejected** (negative edge). v1.09 control baselines in `tools/aos_baseline.json`. The AAPL research preset's 15:55 NY exit falls after the broker's Friday share-session end in winter (3 weekend holds, 2025-11 → 2026-01) | AAPL −0.19R (tester). MSFT −0.01R and XOM −0.26R (mirror). Gross breakout edge ≈ 0 against a 0.10–0.37R cost | None. Kept as *negative benchmarks*: any AI OS layer that makes these look positive is overfitting |

---

## 11. Caveats

### 11.1 Evidence caveats

1. **Tester only. No forward data exists.** Every vector is in-sample with respect to preset selection (the presets were picked from research sweeps on overlapping data). The forward test is the only clean OOS (CO-10).
2. **Mixed windows.** EURUSD-NY, LON0700 and JP225 vectors are 2026 Jan–Oct (v1.08). DE40, UK100 and US500 are v1.09 over longer windows. Cross-asset comparisons of `E` are approximate.
3. **One broker, one regime year.** YWO-Trade, real ticks from 2025-06. 2025–2026 was a rising index market. The long-side tilt of JP225, UK100 and US500 may shrink in a flat or falling year.
4. **Small n.** `M` is 9–11 pp everywhere, and every `R` CI is wide (JP225: 1.15–2.34). Fragile versus Robust is a ±1 pp call for EURUSD-NY, LON0700 and DE40.
5. **Slippage prior.** `c_slip` is the generic default, not a measurement. Release-day slippage (NFP −2.4R) exceeds it. Live fills replace it after 40 events.
6. **Regime tags are proxies.** Range/ATR tercile and side substitute for the generic vol / ER tags (CO-09). A deterministic regime tagger (generic roadmap #3, AI OS L1) should replace them.
7. **Holiday lists are static** and end on 2027-12-31. One early-close assumption (no NYSE early close on 2026-07-02) is unverified.
8. **Lot granularity** at 500–1000 USD makes `f` discrete. DE40 and UK100 vectors are only valid at the deposit they were scored at.
9. **The monthly cycle was never exercised.** Survival numbers assume it stays dormant (CO-18).

### 11.2 Canvas caveats

The companion canvas (`cycleorb-edge-framework.canvas.tsx`, in the Cursor project canvases folder):

- **It is a static snapshot** of §5–§8 as of 2026-11-05. It does not read logs or update itself. Re-score and regenerate after every tester run or month end.
- **The frontier chart plots point estimates.** Each asset's (`R`, `WR`) dot has a WR uncertainty of ±`M` (9–11 pp) and an `R` CI of up to ±0.6. Dots near the curve are not distinguishable from it.
- **The bars mix windows** (§11.1 item 2), and the rolling-20 lines have different lengths and start dates per asset.
- **Monte Carlo figures are single runs** (5,000 paths, fixed seed). Repeat runs move P95 DD by about ±0.5 pp.
- **It is not a monitoring tool.** Lifecycle states shown are as of the last tester event, not live.

---

## 12. Operating cadence

| When | Action |
| --- | --- |
| Every month end | Re-score each asset: W20 / W40 / W80 health vector, lifecycle state (§6.1), all §6.2 triggers, `CALENDAR_LEAK`, L6. Update the canvas |
| Every 40 forward events per asset | Replace `c_slip` with measured slippage. Re-run G1′ / G4′ on the combined sample. Check R2 |
| Every quarter | Full gate matrix (§7.3) and sizing table (§8) re-run. Portfolio MC (§9) |
| Each December | Extend `InpSkipDates` for the next year on every US, UK and DE preset |
| On any EA version change | Tester re-run diff per asset. Reset the baseline only if events changed (CO-20) |

---

## Appendix A — Computation notes

- `WR` excludes exact-zero events (generic §1.3 rule 5). `M` uses the Wilson half-width (generic §4.4, fixture FX-07).
- Bootstrap `R`: 10,000 resamples of the event vector, percentile 2.5 / 97.5.
- MC-1: uniform permutation. MC-2: block bootstrap, block 10 (CO-11). MC-3: MC-2 with each win converted to a loss of −`AL` with probability `M / WR`, wins × 0.9, and costs + 50 % of `c_R` per event. 5,000 paths each, compounded at `f`. Ruin = equity ≤ 0.5 × `C_0`.
- `f_DD25`: bisection on `f` such that MC-2 P95 MaxDD = 25 %.
- Annualised G = (MC-2 median terminal)^(12 / months) − 1.
- Folds (G2a): 4 contiguous slices of the event vector, equal by count.
- Every value is recomputed from the tester journals (`Tester/logs/20261105.log`) with the parser described in System Profile Appendix A.

## Appendix B — CycleORB reference vectors (for a future scoring engine)

A scoring engine run over the baseline journals must reproduce these values within ±0.005 on fractions and ±0.1 pp on margins. They extend the generic §10 fixtures.

| ID | Input | Expected |
| --- | --- | --- |
| CO-FX-01 | EURUSD-NY v1.08 2026 Jan–Oct, magic 26110202 | n 95, WR 0.484, R 1.63, BWR 0.380, BM +10.4 pp, E +0.254R |
| CO-FX-02 | US500 v1.09 2025-07 → 2026-10 @1000, magic 26110902 | n 71, WR 0.563, R 1.51, BM +16.5 pp, 0 `CLOSE FAIL`, 6 skip-date SKIPs |
| CO-FX-03 | UK100 v1.09 @500 versus @1000 | n 54 versus 88. L6 at 500 = 82 skipped sides |
| CO-FX-04 | DE40 v1.09 @500 versus @1000 | Identical event vectors (n 120, E +0.235R). Currency results differ only by lot rounding |
