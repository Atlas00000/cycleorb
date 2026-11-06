# Unified Edge Framework

**Version:** 1.0
**Status:** Normative specification
**Supersedes:** the shared mathematical content of `edge_creation.md`, `edge_detection.md`, `edge_realization.md` (those files remain as narrative commentary; where they conflict with this document, this document wins)

---

## 0. Purpose and Scope

This workspace defines **strategy-independent benchmarks** for evaluating Expert Advisors (EAs). It is not tied to any specific EA. Any EA that can emit the trade blotter defined in the Adapter Contract (Section 8) can be scored against every stage of this framework.

The framework answers five questions, in order:

| Stage | Question | Primary benchmark |
| --- | --- | --- |
| 0 — Core identities | What is the mathematical edge condition? | `WR > 1 / (1 + R)` |
| 1 — Creation / production gate | Does the edge survive costs and uncertainty? | `EF = BM − Leak > M` |
| 2 — Detection / health | Is the edge persistent, stable, and alive? | Persistent positive frontier margin across rolling windows |
| 3 — Realisation / capital | Does the edge convert into compounded wealth? | Max geometric growth subject to survival constraints |
| 4 — Validation protocol | Is the evidence trustworthy? | Gates G0–G5 all pass |

An EA is **production-worthy** only when it passes Stages 1, 2, and 4, and is **ranked** among other passing EAs by Stage 3.

---

## 1. Conventions and Units

### 1.1 The R-multiple is the canonical unit (Stages 0–2)

All per-trade quantities in Stages 0, 1, and 2 are expressed in **R-multiples**:

```
1R = the intended initial risk of the trade event, in account currency
   = |entry price − initial stop price| × position size × point value
```

A trade that risks $250 and nets +$500 is a **+2.0R** trade. A trade that loses $250 is **−1.0R**.

Rules:

- `1R` is fixed at trade entry from the **initial** stop. Later stop moves do not redefine R.
- If an EA does not use hard stops, `1R` MUST be defined as the EA's declared maximum intended loss per trade event (documented in the adapter metadata). An EA that cannot declare this cannot be benchmarked and fails Gate G0.
- Realised PnL in R: `pnl_R = pnl_net_currency / risk_currency`.

### 1.2 Percent-of-equity is the canonical unit for Stage 3

Stage 3 (compounding, drawdown, Kelly) operates on **per-period equity returns**:

```
r_t = f_t × pnl_R,t
```

where `f_t` is the fraction of equity risked on trade event `t` (e.g. `f = 0.01` means 1R = 1% of current equity). The conversion between stages is exactly this multiplication; no other conversion is permitted.

### 1.3 Trade event definition and basket aggregation

The atomic unit of the framework is the **trade event**, not the broker ticket.

```
Trade event = the complete lifecycle of one independent trading decision
```

Aggregation rules (normative):

1. **Single position, single ticket:** one ticket = one trade event.
2. **Scaled entries/exits of one decision** (partial fills, partial closes, pyramids into the same signal): all tickets sharing one `group_id` form **one trade event**. PnL is the sum of all legs, net of all leg costs.
3. **Baskets / grids:** all positions opened under one basket cycle share one `group_id` and form **one trade event**. `1R` = the EA's declared maximum intended basket risk, not the per-position stop.
4. **Hedged / offsetting positions within a cycle:** still one trade event; internal hedges are implementation detail.
5. A trade event is a **win** if `pnl_R > 0`, a **loss** if `pnl_R < 0`. Events with `pnl_R = 0` (exact scratch after costs) are excluded from WR and payoff statistics but counted in frequency and cost statistics.

Rationale: WR, payoff ratio, and BWR are only meaningful over units that approximate independent decisions. Computing them over correlated basket legs inflates WR and corrupts every downstream metric.

### 1.4 Worked basket example

A grid EA opens a 3-position basket with declared maximum basket risk $300 (= 1R). Legs close at +$150, −$80, +$40, total costs $10.

```
pnl_net = 150 − 80 + 40 − 10 = +$100
pnl_R   = 100 / 300 = +0.333R
```

This is **one** winning trade event of +0.333R — not two wins and one loss.

---

## 2. Metric Dictionary (frozen)

These symbols are canonical for every document, script, and report in this repository. Do not introduce synonyms.

| Symbol | Name | Definition | Unit |
| --- | --- | --- | --- |
| `WR` | Win rate | wins / (wins + losses), over trade events | fraction (report as %) |
| `AW` | Average win | mean `pnl_R` of winning events | R |
| `AL` | Average loss | mean absolute `pnl_R` of losing events | R |
| `R` | Realised payoff ratio | `AW / AL` | ratio |
| `RR` | Designed risk:reward | the EA's configured target reward per 1R | ratio |
| `BWR` | Breakeven win rate | `1 / (1 + R)` | fraction |
| `BM` | Breakeven margin (gross frontier distance) | `WR − BWR` | percentage points (pp) |
| `FMI` | Frontier margin index | `BM / BWR` | fraction |
| `E_N` | Normalised expectancy | `WR × (R + 1) − 1` | R (units of AL) |
| `c_R` | Total per-event cost | all frictions, in R | R |
| `Leak` | WR-equivalent execution leak | `c_R / (R + 1)` | pp |
| `EF` | Effective frontier edge | `BM − Leak` | pp |
| `M` | Uncertainty margin | `1.96 × sqrt(WR × (1 − WR) / n)` | pp |
| `ΔD` | Edge velocity | `EF_t − EF_{t−k}` across rolling windows | pp per window |
| `G` | Geometric growth rate | `(C_T / C_0)^(1/T) − 1` | fraction per period |
| `DD` | Drawdown | `1 − equity / running peak equity` | fraction |
| `MaxDD` | Maximum drawdown | max of `DD` over the sample | fraction |
| `f*` | Full Kelly fraction | see Section 6.5 | fraction of equity |
| `f` | Operating risk fraction | equity fraction risked per event (1R) | fraction |
| `PF` | Profit factor | gross profit / gross loss | ratio |
| `n` | Sample size | number of scored trade events | count |
| `WFE` | Walk-forward efficiency | `E_N(OOS) / E_N(IS)` | ratio |

Notes:

- `WR` always means win rate. The product of win rate and payoff is always written `WR × R`, never `WR` — this fixes the notation collision in `edge_creation.md` §2.
- `R` always means **realised** payoff. Designed risk:reward is always `RR`. Detection and monitoring MUST use `R`, never `RR`.
- `BM` replaces the synonyms `D_E` (creation) and "frontier distance". `EF` replaces "Effective Frontier Edge" / "net frontier distance".

---

## 3. Stage 0 — Core Identities

### 3.1 Expectancy

For a trade event population with win rate `WR`, average win `AW`, average loss `AL`:

```
E = WR × AW − (1 − WR) × AL          (in R, where AL defines 1 unit)
```

Dividing by `AL` and substituting `R = AW / AL`:

```
E_N = WR × R − (1 − WR)
    = WR × (R + 1) − 1
```

### 3.2 Breakeven win rate and the Breakeven Frontier

Setting `E_N = 0`:

```
BWR = 1 / (1 + R)
```

Equivalently, the minimum payoff for a given win rate:

```
R_BE = (1 − WR) / WR
```

The curve `WR = 1 / (1 + R)` in WR–payoff space is the **Breakeven Frontier**. It is the universal zero-expectancy reference for every strategy architecture.

Reference table (also fixture FX-01):

| R | BWR |
| ---: | ---: |
| 0.50 | 66.67% |
| 0.75 | 57.14% |
| 1.00 | 50.00% |
| 1.25 | 44.44% |
| 1.50 | 40.00% |
| 2.00 | 33.33% |
| 3.00 | 25.00% |
| 4.00 | 20.00% |
| 5.00 | 16.67% |

### 3.3 The decomposition identity

```
E_N = (R + 1) × (WR − BWR) = (R + 1) × BM
```

This is the central identity of the framework: expectancy equals the payoff multiplier times the distance above the frontier. Two consequences:

1. **Equal BM is not equal edge.** +5pp of margin is worth +0.10R at `R = 1` but +0.25R at `R = 4` (fixture FX-03).
2. **BM alone must never be the optimisation objective.** A 90% WR / 0.15 payoff system has positive BM (+3.04pp) but near-zero expectancy (+0.035R) — fixture FX-04.

### 3.4 Designed RR versus realised R

`RR` is an ex-ante design property. `R` is the observed statistic after early exits, slippage, partial closes, basket behaviour, and asymmetric market movement. All benchmarks in this framework use `R`. The gap `RR − R` is itself a monitored diagnostic (it is one visible symptom of execution leak, Section 4.2).

### 3.5 Assumption boundary (first-order model)

The identities above assume winners and losers are adequately summarised by their means and that trade events are approximately independent. These assumptions **fail** for:

- clustered losses (autocorrelated outcomes),
- heavily skewed payoff distributions (one tail loss dominating hundreds of small wins),
- grid/basket systems with nonlinear loss profiles.

Therefore Stage 0 verdicts are **necessary but not sufficient**. Section 7 (Gate G4: distributional tests, Monte Carlo with block bootstrap) is mandatory precisely because of this boundary. Any EA whose loss distribution has sample skewness < −2 or whose largest single loss exceeds 15% of gross profit must be flagged `TAIL_RISK` and cannot pass validation on first-order metrics alone.

---

## 4. Stage 1 — Creation / Production Gate

Stage 1 answers: *after realistic frictions and statistical uncertainty, does an edge still exist?*

### 4.1 Cost model (normative)

Every trade event carries a total friction cost `c_R`, in R, built from four measured components. All components are first expressed in **price units per round turn**, then normalised by the event's 1R price distance:

```
c_R = (spread_cost + commission_cost + swap_cost + slippage_cost) / risk_price_distance
```

| Component | Specification | Default when unmeasured |
| --- | --- | --- |
| `spread_cost` | Average quoted spread at entry plus at exit, in price units. For limit-entry systems, spread applies only where the fill crosses the spread. | Instrument's median session spread × 2 |
| `commission_cost` | Broker commission per round turn, converted to price units at the traded size | Broker rate card |
| `swap_cost` | Daily swap/financing × nights held (signed; credits allowed) | 0 for intraday, broker rate otherwise |
| `slippage_cost` | Measured live: `(actual fill − requested price)` summed over entry and exit legs | `0.5 × spread` per market-order leg |

Rules:

- Backtests MUST apply this cost model; a backtest with zero costs is not admissible evidence at any gate.
- Costs are recorded **per event** in the blotter (Section 8), so `c_R` distributions (not just means) are available. Cost stress testing (Gate G5) inflates these recorded values.
- For basket events, `c_R` sums costs across all legs, normalised by basket 1R.

### 4.2 Edge leak taxonomy (normative)

Leak is any mechanism that makes realised edge smaller than gross/backtest edge. The taxonomy separates leaks by **how they are estimated** and **where they enter the framework**, so nothing is double-counted:

| # | Leak type | Definition | How estimated | Where it enters |
| --- | --- | --- | --- | --- |
| L1 | **Execution leak** | Spread, commission, swap, slippage, latency, partial fills, rejected orders, missed fills | Measured per event via the cost model (`c_R`); fill-quality audit for misses/rejects | Subtracted inside `EF` |
| L2 | **Statistical leak** | Estimation error in WR and R from finite samples | Uncertainty margin `M` (Section 4.4) | The robustness threshold `EF > M` |
| L3 | **Regime leak** | Edge concentration in market conditions that may not persist | Regime-conditioned BM (Section 4.5); conservative scoring uses the worst regime | Gate G3 |
| L4 | **Model / overfitting leak** | Optimistic bias from parameter selection on the same data | Walk-forward efficiency `WFE` (Section 7.2) | Gate G2 |
| L5 | **Temporal decay** | Structural erosion of the edge over time | Edge velocity `ΔD` on rolling windows (Section 5.4) | Stage 2 lifecycle states |

**Double-counting rule:** only L1 is subtracted arithmetically inside `EF`. L2 sets the threshold. L3–L5 are enforced as gates and monitors. Summing all five into one number would overcount overlapping effects.

### 4.3 Converting cost to WR-equivalent leak

Because `E_N = (R + 1)(WR − BWR)`, a per-event cost of `c_R` reduces expectancy by exactly `c_R`, which is equivalent to a win-rate reduction of:

```
Leak = c_R / (R + 1)        (in percentage points of WR)
```

Example (fixture FX-05): `R = 1.2`, `c_R = 0.11R` → `Leak = 0.11 / 2.2 = 5.0pp`.

### 4.4 Uncertainty margin M (statistical leak)

`M` is the 95% half-width of the win-rate estimate:

```
M = 1.96 × sqrt(WR × (1 − WR) / n)
```

For small `n` (< 200) use the Wilson score interval half-width instead (fixture FX-07 gives the reference computation). `M` shrinks with sample size; it is recomputed for every window and every gate evaluation.

### 4.5 Regime conditioning (regime leak measurement)

Every trade event is tagged (by the scoring engine, not the EA) with:

- **Volatility regime:** tercile of the instrument's 20-period ATR percentile at entry (low / mid / high).
- **Trend regime:** trending vs ranging via 50-period efficiency ratio at entry (ER ≥ 0.3 trending, else ranging).

Compute `BM` conditioned on each regime cell with `n ≥ 30` events. Define:

```
BM_worst = min over qualifying regime cells of BM_cell
Regime concentration = share of total E_N contributed by the single best cell
```

Conservative production scoring uses `BM_worst`. A regime concentration > 70% is flagged `REGIME_CONCENTRATED` and fails Gate G3 unless the EA explicitly declares itself regime-filtered (i.e. it only trades that regime by design).

### 4.6 The production gate

```
BM  = WR − BWR                (gross margin)
EF  = BM − Leak               (effective frontier edge, after execution leak)
```

Three zones (normative verdicts):

| Zone | Condition | Verdict |
| --- | --- | --- |
| **Negative** | `EF ≤ 0` | No production edge. Reject or send to rediscovery. |
| **Fragile** | `0 < EF ≤ M` | Nominally profitable; indistinguishable from zero at 95% confidence. Not production-worthy. |
| **Robust** | `EF > M` | Passes the production gate (still subject to Stages 2 and 4). |

Worked example (fixture FX-06): `WR = 55%`, `R = 1.0`, `c_R = 0.06R`, `n = 500`.

```
BWR = 50%          BM = 5.0pp
Leak = 0.06 / 2.0 = 3.0pp
EF = 2.0pp
M = 1.96 × sqrt(0.55 × 0.45 / 500) = 4.36pp
EF (2.0) ≤ M (4.36)  →  FRAGILE. Not production-worthy despite positive expectancy.
```

---

## 5. Stage 2 — Detection / Health

Stage 2 answers: *is the edge persistent, stable, and in which lifecycle state?*

### 5.1 Rolling-window definition (normative)

Two window families are computed. Trade-count windows are **primary** because WR, R, BWR, BM, and E_N are per-event statistics; calendar windows are **secondary** and exist to detect frequency collapse (an EA that stops trading looks healthy on trade windows forever).

**Primary — trade-count windows:**

| Window | Size | Step | Role |
| --- | --- | --- | --- |
| W100 | last 100 events | every 25 events | fast signal, noisy (M ≈ ±9.8pp at WR 50%) |
| W250 | last 250 events | every 25 events | main monitoring window |
| W500 | last 500 events | every 25 events | baseline / slow drift |

All lifecycle decisions (Section 5.5) key off **W250**, cross-checked against W500. W100 alone never triggers de-risking; it may trigger investigation.

**Secondary — calendar windows:** rolling 30-day and 90-day. Monitored quantities: event frequency, cost per event, and `RR − R` gap. A 90-day event count below 50% of the EA's validated baseline frequency raises a `FREQUENCY_STALL` flag regardless of per-trade statistics.

### 5.2 Sample-size and significance rules (normative)

Minimum evidence tiers, derived from `n ≥ 1.96² × WR(1 − WR) / ε²` at the worst case `WR = 0.5`:

| Tier | Events (n) | WR precision (95%) | Permitted use |
| --- | ---: | --- | --- |
| Insufficient | < 100 | worse than ±9.8pp | No verdicts of any kind. Data collection only. |
| Provisional | 100 – 384 | ±9.8pp to ±5pp | Stage 0 estimates, exploratory only. Cannot pass gates. |
| Standard | ≥ 385 | ±5pp | Eligible for Gates G1–G3. |
| High confidence | ≥ 1068 | ±3pp | Eligible for full production sign-off (G1–G5). |

Rules:

- `WR` significance: the production gate `EF > M` already embeds the WR test. Additionally, a one-sided binomial test of `WR > BWR + Leak` at α = 0.05 must reject the null.
- `R` significance: payoff ratio is a ratio of means with no reliable closed-form interval. Compute its 95% CI by **bootstrap** (10,000 resamples of the event PnL vector, recomputing `AW/AL` each time; percentile interval). The gate requires the lower CI bound of `R` to keep `BWR` below the observed `WR − Leak`.
- Losing streaks: expected worst streak in `n` trials ≈ `ln(n) / ln(1 / (1 − WR))`. An observed streak more than 1.5× this value raises a `DEPENDENCE` flag and forces block-bootstrap Monte Carlo (Gate G4) before any verdict.

### 5.3 The health vector

Per window, the scoring engine emits:

```
{ n, WR, AW, AL, R, RR−R gap, BWR, BM, FMI, Leak, EF, M, E_N, PF, MaxDD_window, freq_30d }
```

### 5.4 Edge velocity

```
ΔD = EF(current W250) − EF(previous non-overlapping W250)
```

Velocity contextualises level: an EA at `EF = 8pp` falling 2pp per window is less healthy than one stable at `EF = 5pp`. Level and velocity are always reported together.

### 5.5 Lifecycle states (normative thresholds and actions)

Evaluated on W250, confirmed on W500:

| State | Condition | Mandatory action |
| --- | --- | --- |
| **Expanding** | `EF > M` and `ΔD ≥ +1pp` for 2+ consecutive evaluations | None. Note for sizing review (Stage 3). |
| **Stable** | `EF > M` and `abs(ΔD) < 1pp` | Routine monitoring. |
| **Compressing** | `EF > M` but `ΔD ≤ −1pp` for 2+ consecutive evaluations | Open investigation (runbook Section 9.3). |
| **Near frontier** | `0 < EF ≤ M` | De-risk: halve `f`. Investigation mandatory. |
| **Below frontier** | `EF ≤ 0` on W250 **and** W500 | Halt new entries. Enter rediscovery (Section 9.4). |

The dual-window requirement for halting prevents a single noisy fast window from killing a healthy system; the W250-only trigger for de-risking accepts a false-positive cost in exchange for capital preservation (drawdown asymmetry, Section 6.4, justifies this bias).

---

## 6. Stage 3 — Realisation / Capital

Stage 3 answers: *for EAs that pass Stages 1–2, which converts its edge into compounded wealth most efficiently?* It operates in percent-of-equity units (Section 1.2).

### 6.1 Geometric growth is the objective

```
G = (C_T / C_0)^(1/T) − 1
```

per period (annualise using the appropriate period count). Arithmetic mean return is not a ranking criterion: a +50% / −50% sequence has 0% arithmetic mean and G = −13.40% per period (fixture FX-09).

### 6.2 Volatility drag

```
g ≈ μ − σ² / 2
```

where `μ`, `σ` are the mean and standard deviation of per-period equity returns. Same `μ = 10%`: at `σ = 10%` growth ≈ 9.5%; at `σ = 30%` growth ≈ 5.5% (fixture FX-10). Raising return by raising variance can be self-defeating.

### 6.3 Drawdown and recovery burden

```
RecoveryReturn = DD / (1 − DD)
```

| DD | Required recovery |
| ---: | ---: |
| 10% | 11.11% |
| 20% | 25.00% |
| 30% | 42.86% |
| 50% | 100.00% |

Capital preservation has convex value; this asymmetry justifies the conservative bias throughout the framework.

### 6.4 Survival constraints (normative)

An EA's Stage 3 evaluation is run at its proposed operating fraction `f` and must satisfy:

```
P95 MaxDD (Monte Carlo, Section 7.3) ≤ DD_limit        (default DD_limit = 25%)
P(equity ≤ 0.5 × C_0 at any point)  ≤ 1%               (ruin definition: −50%)
Worst expected losing streak survivable at f without breaching DD_limit
```

Defaults may be overridden per portfolio mandate, but every scorecard must state the limits used.

### 6.5 Kelly sizing

Binary approximation (using `b = R`, `p = WR`):

```
f* = (b × p − q) / b ,   q = 1 − p
```

Continuous approximation from the event distribution in R:

```
f* ≈ E_N / σ_R²
```

where `σ_R` is the standard deviation of event PnL in R. Rules:

- Full Kelly is never an operating size. The default operating band is **quarter to half Kelly**, computed from **current W500 statistics with WR shrunk by M** (i.e. Kelly of the pessimistic edge, not the point estimate).
- Sizing must be recomputed whenever the lifecycle state changes. "Near frontier" halves `f` regardless of Kelly output; "Below frontier" sets `f = 0`.
- Fixture FX-12: `WR = 55%`, `b = 1.5` → `f* = 25%`; half Kelly 12.5%, quarter Kelly 6.25% of equity as 1R.

### 6.6 Realisation scorecard

EAs that pass Stages 1, 2, 4 are ranked on:

| Dimension | Metric |
| --- | --- |
| Growth | `G` at the operating `f`, from Monte Carlo median |
| Variance efficiency | `E_N / σ_R` |
| Drawdown efficiency | `G / P95 MaxDD` |
| Recovery efficiency | `G / mean recovery burden` |
| Survival | `P(ruin)` from Monte Carlo |
| Decay adaptivity | documented sizing response to lifecycle transitions |

The ranking objective, stated formally:

```
maximise E[ln(C_T / C_0)]   subject to   P95 MaxDD ≤ DD_limit,  P(ruin) ≤ 1%
```

---

## 7. Stage 4 — Validation Protocol

Stage 4 defines the evidence standard. Every gate is pass/fail with stated criteria; a scorecard lists all gate results.

### 7.0 Gate G0 — Admissibility

- Blotter conforms to the Adapter Contract (Section 8), including declared 1R for every event.
- Costs recorded per event (or defaulted per Section 4.1 with the default flagged).
- `n` meets at least the Standard tier (≥ 385 events) across IS + OOS combined.

### 7.1 Gate G1 — Production gate (Stage 1)

- `EF > M` on the full qualifying sample **and** on the most recent W500.
- One-sided binomial test `WR > BWR + Leak` rejects at α = 0.05.
- Bootstrap lower bound of `R` (Section 5.2) keeps the verdict positive.

### 7.2 Gate G2 — Walk-forward / out-of-sample protocol (normative)

Configuration:

- **Scheme:** anchored walk-forward. In-sample (IS) grows from the data start; out-of-sample (OOS) is the next contiguous segment.
- **Fold sizing:** OOS segments of 6 months or ≥ 100 events, whichever is larger; minimum 4 folds; step = OOS length (no OOS overlap).
- **Optimisation freedom:** parameters may be re-selected each fold **on IS only**, using the frozen objective `maximise E_N subject to EF > M` — never raw profit, never WR, never BM alone.

Pass criteria:

```
E_N(OOS) > 0 in ≥ 75% of folds
Pooled WFE = E_N(all OOS pooled) / E_N(all IS pooled) ≥ 0.5
Pooled OOS EF > 0
```

`(1 − WFE) × BM_IS` is recorded as the measured overfitting leak (L4) on the scorecard.

### 7.3 Gate G4 (with G3) — Monte Carlo sequencing method (normative)

Three procedures, all mandatory, all on the OOS + live event vector, 5,000 iterations each, evaluated at the proposed operating `f`:

| Procedure | Method | What it tests |
| --- | --- | --- |
| **MC-1 Shuffle** | Uniform random permutation of event order | Path/sequence risk under independence |
| **MC-2 Block bootstrap** | Resample blocks of 20 consecutive events with replacement to sample length | Path risk preserving clustering and dependence |
| **MC-3 Stress** | MC-2 with `WR` shrunk by `M`, `R` degraded 10%, costs inflated 50% | Pessimistic-edge survival |

Outputs per procedure: distribution of terminal `G`, `MaxDD`, longest losing streak, `P(ruin)`.

Pass criteria (on MC-2, the primary procedure):

```
P95 MaxDD ≤ DD_limit          median G > 0          P(ruin) ≤ 1%
```

and on MC-3: `P(ruin) ≤ 5%` and median terminal equity ≥ `C_0`.

**Gate G3 — Regime robustness** (evaluated alongside): `BM_worst > 0` across qualifying regime cells (Section 4.5), and regime concentration ≤ 70% unless declared regime-filtered.

### 7.4 Gate G5 — Perturbation and cost stress

- **Parameter perturbation:** re-run the backtest at ±10% on each continuous parameter (one at a time). Pass if `E_N` stays positive in ≥ 80% of perturbed runs and no single perturbation flips `EF` negative. This operationalises "stable region beats narrow peak".
- **Cost stress:** ×1.5 and ×2.0 on all cost components. Pass if `EF > 0` at ×1.5. The ×2.0 result is reported (not gated) as the EA's cost headroom.

### 7.5 Verdict assembly

```
PRODUCTION-WORTHY  = G0 ∧ G1 ∧ G2 ∧ G3 ∧ G4 ∧ G5
RANKING            = Stage 3 scorecard among production-worthy EAs
```

A single failed gate yields `NOT PRODUCTION-WORTHY` with the failing gate(s) named. There are no partial passes.

---

## 8. EA Adapter Contract

Any EA is benchmarked by emitting a **trade blotter** in this schema. The scoring engine computes everything else; EAs never self-report derived metrics.

### 8.1 Blotter record (one row per broker ticket / leg)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `event_id` | string | yes | Trade-event grouping key (Section 1.3). All legs of one decision share it. |
| `leg_id` | string | yes | Unique per ticket/leg |
| `symbol` | string | yes | Instrument |
| `direction` | `long` / `short` | yes | Leg direction |
| `entry_time` | ISO-8601 UTC | yes | |
| `entry_price` | decimal | yes | Actual fill |
| `entry_requested` | decimal | no | Requested price (enables slippage measurement) |
| `exit_time` | ISO-8601 UTC | yes | |
| `exit_price` | decimal | yes | Actual fill |
| `exit_requested` | decimal | no | |
| `initial_stop` | decimal | conditional | Required if the event's 1R derives from a stop |
| `volume` | decimal | yes | Lots/units |
| `pnl_gross_ccy` | decimal | yes | Before costs, account currency |
| `cost_spread_ccy` | decimal | yes* | *Or defaulted per Section 4.1, flagged |
| `cost_commission_ccy` | decimal | yes* | |
| `cost_swap_ccy` | decimal | yes* | |
| `cost_slippage_ccy` | decimal | yes* | |
| `pnl_net_ccy` | decimal | yes | After all costs |

### 8.2 Event manifest (one row per trade event)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `event_id` | string | yes | |
| `risk_ccy` | decimal | yes | Declared 1R in currency at event open (Section 1.1/1.3) |
| `equity_at_open` | decimal | yes | Account equity when the event opened (enables `f` and Stage 3) |
| `signal_tag` | string | no | EA's own signal/setup label (enables per-setup breakdown) |

### 8.3 EA metadata (once per submission)

| Field | Description |
| --- | --- |
| `ea_name`, `ea_version` | Identity; version changes reset live baselines |
| `designed_rr` | The configured `RR`, for the `RR − R` gap diagnostic |
| `risk_definition` | How 1R is defined (hard stop / declared max basket risk / other) |
| `regime_filtered` | Whether the EA intentionally trades only specific regimes (affects Gate G3) |
| `baseline_frequency` | Expected events per 90 days (for `FREQUENCY_STALL`) |
| `costs_defaulted` | Which cost components use defaults rather than measurements |

Format: CSV or JSON lines; UTC timestamps; one blotter + one manifest + one metadata block per submission.

---

## 9. Monitoring / Decay / Rediscovery Runbook

### 9.1 Cadence

| Frequency | Action |
| --- | --- |
| Per 25 events | Recompute W100/W250/W500 health vectors; evaluate lifecycle state |
| Weekly | Calendar-window review: frequency, cost drift, `RR − R` gap |
| Monthly | Regime-conditioned BM refresh; Kelly re-estimation at pessimistic edge; sizing review |
| Quarterly | Full Stage 4 re-validation on the trailing dataset for every live EA |

### 9.2 Trigger table

| Trigger | Threshold | Response |
| --- | --- | --- |
| Compressing state | `ΔD ≤ −1pp` × 2 evaluations | Open investigation (9.3) |
| Near frontier | `0 < EF ≤ M` on W250 | Halve `f`; investigation mandatory |
| Below frontier | `EF ≤ 0` on W250 and W500 | Halt entries; rediscovery (9.4) |
| `FREQUENCY_STALL` | 90-day events < 50% baseline | Investigation: filter drift vs market change |
| Cost drift | W250 mean `c_R` > 1.5× validated `c_R` | Execution audit before any parameter change |
| `RR − R` gap widening | gap grows > 25% vs validation baseline | Execution audit (exits, slippage, partial closes) |
| `DEPENDENCE` flag | Loss streak > 1.5× expected | Re-run MC-2/MC-3 at current `f`; de-risk if P95 MaxDD > limit |
| DD limit approach | live DD ≥ 0.8 × DD_limit | Halve `f` regardless of edge metrics |

### 9.3 Investigation order (mandatory sequence)

Diagnose in this order — cheapest and least destructive explanations first. Do not touch parameters until steps 1–3 are excluded:

1. **Data integrity:** blotter gaps, misgrouped events, wrong 1R declarations, symbol/session anomalies.
2. **Execution:** cost drift, slippage regime, broker changes, fill quality — compare `Leak` now vs validation baseline. If execution explains the compression, fix execution; the edge itself may be intact.
3. **Regime:** recompute regime-conditioned BM. If the edge is intact in its home regime but the market has left that regime, the correct response may be reduced size or dormancy, not re-optimisation.
4. **Structural decay:** only if 1–3 are excluded. WR down? R down? Both? Persistent across W250 and W500? Then proceed to rediscovery.

### 9.4 Rediscovery procedure

1. Freeze the incumbent configuration; `f = 0` (halted) or halved (compressing), per trigger table.
2. Search for new configurations using the frozen objective: **largest stable `EF` with `E_N` attractive**, never max profit. Search on data **through the decay period** — a configuration must explain the regime that killed its predecessor, and must never be fitted solely on the decay window.
3. Candidate configurations are new submissions: full Stage 4 gates, no shortcuts, no grandfathering.
4. Re-entry to production at quarter Kelly of the pessimistic edge, scaling to the normal band only after 100 live events with `EF > M`.

### 9.5 Retirement criteria

Retire (do not indefinitely rediscover) when any of:

- Two consecutive rediscovery cycles fail Stage 4.
- The edge's home regime has been absent for 4+ quarters and the EA is regime-concentrated.
- Structural market change removes the mechanism the EA exploits (documented rationale required).

Retirement is an expected lifecycle outcome, not a failure of the framework.

---

## 10. Reference Numeric Fixtures (golden vectors)

Every implementation of the scoring engine MUST reproduce these values. Tolerance: ±0.0001 absolute on fractions, ±0.01pp on margins, unless stated.

**FX-01 — BWR table.** `BWR = 1/(1+R)`: R 0.50 → 0.666667; 0.75 → 0.571429; 1.00 → 0.500000; 1.25 → 0.444444; 1.50 → 0.400000; 2.00 → 0.333333; 3.00 → 0.250000; 4.00 → 0.200000; 5.00 → 0.166667.

**FX-02 — Decomposition identity.** `WR = 0.57`, `R = 1.20` → `BWR = 0.454545`, `BM = 0.115455` (11.5455pp), `E_N = 2.2 × 0.115455 = 0.254000`. Cross-check: `0.57 × 2.2 − 1 = 0.254`.

**FX-03 — Equal margin, unequal edge.** All with `BM = 5pp`:
- A: `R = 1`, `WR = 0.55` → `E_N = 0.1000`
- B: `R = 2`, `WR = 0.383333` → `E_N = 0.1500`
- C: `R = 4`, `WR = 0.25` → `E_N = 0.2500`

**FX-04 — Frontier trap.** `WR = 0.90`, `R = 0.15` → `BWR = 0.869565`, `BM = +3.04pp`, `E_N = 0.90 × 1.15 − 1 = 0.0350`. Above the frontier, negligible edge.

**FX-05 — Cost-to-leak conversion.** `R = 1.2`, `c_R = 0.11` → `Leak = 0.11 / 2.2 = 0.0500` (5.00pp).

**FX-06 — Production gate (fragile).** `WR = 0.55`, `R = 1.0`, `c_R = 0.06`, `n = 500` → `BM = 5.00pp`, `Leak = 3.00pp`, `EF = 2.00pp`, `M = 1.96 × sqrt(0.2475/500) = 4.36pp` → verdict **FRAGILE**.

**FX-07 — Wilson interval.** `n = 100`, `WR = 0.55`, `z = 1.96` → interval ≈ `[0.4524, 0.6439]` (center 0.5482, half-width 0.0957).

**FX-08 — Sample-size tiers.** `n ≥ 3.8416 × 0.25 / ε²`: ε = 5pp → 385 events (384.16 rounded up); ε = 3pp → 1068 events (1067.1 rounded up).

**FX-09 — Geometric vs arithmetic.** Returns +50%, −50%: arithmetic mean 0%; terminal capital 0.7500 × `C_0`; `G = sqrt(0.75) − 1 = −0.133975` (−13.3975% per period).

**FX-10 — Volatility drag.** `g ≈ μ − σ²/2`: (μ 10%, σ 10%) → 9.50%; (μ 10%, σ 30%) → 5.50%.

**FX-11 — Recovery burden.** `DD/(1−DD)`: 20% → 25.00%; 50% → 100.00%.

**FX-12 — Kelly (binary).** `p = 0.55`, `b = 1.5` → `f* = (0.825 − 0.45)/1.5 = 0.2500`; half 0.1250; quarter 0.0625.

**FX-13 — Drawdown computation.** Equity returns +10%, −5%, −10%, +20% from 1.0000: path 1.1000, 1.0450, 0.9405, 1.1286. Running peak 1.1000 at trough 0.9405 → `MaxDD = 1 − 0.9405/1.1000 = 0.145000` (14.50%).

**FX-14 — Basket aggregation.** Basket 1R = $300; legs +$150, −$80, +$40; costs $10 → one winning event, `pnl_R = +0.3333`.

**FX-15 — FMI.** `WR = 0.50`, `BWR = 0.40` → `FMI = 0.10 / 0.40 = 0.2500`.

**FX-16 — Expected losing streak.** `WR = 0.55`, `n = 500` → expected worst streak ≈ `ln(500)/ln(1/0.45) = 6.2145/0.7985 ≈ 7.78` → 8 losses. `DEPENDENCE` flag threshold: 12 (1.5×, rounded up).

---

## 11. Versioning and Governance

- This document is versioned. Any change to a formula, threshold, gate, or the metric dictionary increments the version and must update the affected fixtures in Section 10.
- Scorecards always cite the framework version they were produced under. EAs are re-scored, not grandfathered, after a version change that affects their gates.
- The three original essays (`edge_creation.md`, `edge_detection.md`, `edge_realization.md`) are retained as background reading. They are **non-normative**: no threshold, symbol, or formula may be cited from them in a scorecard.

### Roadmap (next artifacts, in order)

1. **Reference scoring engine** implementing Sections 3–7 with the FX fixtures as its test suite.
2. **Scorecard template** (one page per EA per evaluation: gate results, health vector, lifecycle state, Stage 3 ranking).
3. **Regime tagger** implementing Section 4.5 deterministically from price data.
4. **Live monitoring job** implementing the Section 9 cadence and trigger table.
