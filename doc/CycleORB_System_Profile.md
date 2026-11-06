# CycleORB — System Profile

**Date:** 2026-11-05  
**EA:** `CycleORB.mq5` + `Include/*.mqh` (v1.08 for §1–§12, v1.09 for the §13 re-score)  
**Evidence:** 7 Strategy Tester runs in `Tester/logs/20261105.log` (YWO-Trade, real ticks, **2026-01-01 → 2026-10-31**, deposit **500 USD**, leverage 1:500, M5 chart). Presets from `MQL5/Profiles/Tester/ORB/`. **Update the same day:** 6 v1.09 re-score runs (DE40, UK100 and US500 at 500 and 1000 USD, longest valid window). See §13, which supersedes §1–§12 for those three presets.  
**Earlier evidence** (for comparison only): `doc/CycleORB_Review_v107.md`.  
**Companion docs:** `ROADMAP.md`, `doc/unified_edge_framework.md` (metric names and gates follow that framework).

---

## 1. Executive summary

**CycleORB is an intraday momentum / volatility-expansion breakout with a session time-stop.** It is a trend-following strategy on an intraday horizon, not mean reversion. In practice it behaves as a hybrid: *break of the first-hour range → hold the session drift to a fixed exit time*, with the take-profit acting as a cap.

**All six distinct presets were profitable in the 2026 Jan–Oct tester window, and every one matches the trend-following signature:** win rate 46–54 %, realised payoff R 1.3–1.6, losses capped at about −1R, and expectancy +0.12 to +0.37R per trade. Samples are small (n = 40–124 per preset). The sample-size tiers in the framework are treated as context, not a hard requirement: confidence comes from the uncertainty margin M (which already scales with n), consistency across months and rolling windows, and the forward test.

| Preset | n | WR | R (realised) | E (R/trade) | PF | Return @ 500 USD | Max DD (closed) | Months + | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EURUSD-NY (1 %) | 95 | 48.4 % | 1.63 | **+0.25** | 1.53 | +24.7 % | 4.7 % | 8 / 10 | Best overall. Borderline robust |
| EURUSD-LON0700 (0.5 %) | 124 | 51.6 % | 1.40 | +0.20 | 1.50 | +9.2 % | 4.4 % | 6 / 10 | Edge lives in 2 months. Fragile |
| DE40-500USD (3 % cap) | 68 | 45.6 % | 1.56 | +0.16 | 1.30 | +22.0 % | 11.4 % | 5 / 10 | Offline model confirmed. Fragile, compressing |
| JP225-TKY (1 %) | 77 | 51.9 % | 1.63 | +0.18 | **1.77** | +14.1 % | **3.7 %** | 8 / 10 | Highest quality. Robust, compressing |
| UK100-LON (1 %) | 54 | 53.7 % | 1.62 | **+0.37** | **1.88** | +14.2 % | 6.2 % | 6 / 10 | First tester confirmation, but biased sample (§9) |
| US500-NY (1 %) | 40 | 50.0 % | 1.30 | +0.12 | 1.30 | +4.1 % | 4.1 % | 6 / 10 | Weakest. Holiday bug cost 4.75R (§9) |

> **v1.09 re-score (§13):** with the holiday fix and the longer window, **US500 rises to +0.28R per trade (PF 1.95, 71 trades, rolling-20 never below +0.15R)**. **UK100 at 1000 USD has no lot-minimum bias: +0.40R (PF 1.99, 88 trades).** DE40-500USD over 16 months: +0.24R (PF 1.52, 120 trades), with a weak second half.

**Three new defects were found in the logs** (details in §9; the first two are fixed in v1.09):

1. **High: the time exit fails on exchange holidays.** US500 traded Memorial Day and Juneteenth. The CFD closed early, the 15:00 NY close was rejected (`Market closed`, retcode 10018) 18,836 times, and one position was held **over a weekend** and stopped out on the Sunday gap at **−2.23R**. Excluding the three US-holiday trades, US500 expectancy doubles from +0.12R to +0.26R.
2. **Medium: the 500 USD account changes the strategy.** Lot-minimum skips removed whole days on UK100 (41 of 98 armed days), LON0700 (34 order sides) and DE40 (20 sides). The skipped days are the wide-range days, so these runs are biased samples of the presets.
3. **Medium: indicator warm-up in the tester.** UK100 lost 2026-01-02 → 01-22 to `daily ATR unavailable` and `H1 vol percentile unavailable`, because the tester did not have the 500 H1 bars needed for the vol filter.

**Rolling windows:** EURUSD-NY and LON0700 finish strongest (rolling-20 expectancy +0.21R and +0.55R in October). **DE40 and JP225 are compressing:** DE40's rolling-20 expectancy has been negative since September, and JP225's fell from +0.39R in June to +0.05R, which is right at its research card's compression trigger.

---

## 2. System profile

### 2.1 What the EA does

| Element | Implementation |
| --- | --- |
| Class | Opening-range breakout (ORB), OCO stop orders, one trade per setup per day, flat every evening |
| Sessions | London, New York and Tokyo, each in exchange-local time with its own DST rules (`SessionClock.mqh`). Every preset runs **one** session |
| Range | High/low of M1 bars over a fixed local window (15–60 min) |
| Entry | Buy-stop above the high and sell-stop below the low, each offset by `max(k × avg spread, p % of range)`. OCO: a fill deletes the other side |
| Stop | Opposite range edge (every preset) |
| Target | `TargetR × stop distance`, never below the stop (validated twice) |
| Time rules | Unfilled orders cancelled at entry end. Everything closed at the session exit time |
| Filters | Range / D1 ATR(14) band (all). Spread / range cost cap (all). H1 ATR(20) percentile over 500 bars ≥ 33 (DE40, JP225, UK100, TSLA). D1 SMA(20) trend side (US500, AAPL) |
| Sizing | Risk = min((cycle equity − hard-flatten floor) / 8, `InpMaxRiskPct` × capital). Lots are floored to the volume step, and a side is skipped if the lot is below the broker minimum |
| Monthly cycle | Soft halt at −30 %, hard flatten at −38 %, ratchet arms at +20 % and locks max(10 %, 50 % of peak). It counts only this EA's deals on this symbol |
| Persistence | Ratchet peak and stopped flag are kept in terminal globals `CORB_<magic>_<symbol>_<yyyymm>_*` (v1.08: symbol added) |

### 2.2 Architecture

There are six files and about 900 lines, with no dependencies beyond `Trade.mqh`. Each module has one job: config/validation, clock, cycle, orders, setup and wiring. The order flow is defensive: OCO runs on both the fill transaction and the next tick, a restart guard prevents a second trade in a day, a session-gate `WAIT` avoids placing orders into a closed session, and orders are refused if price is already through the entry. The weak spot this profile adds (§9) is that **the exit path assumes the market is open at the exit time**.

### 2.3 Operating envelope (observed)

| Item | Value in these runs |
| --- | --- |
| Trades per month per preset | 4–12 (median ≈ 7–9) |
| Median hold | 2 h (EURUSD-NY) to 5 h (indices, LON0700) |
| Effective risk per trade | EURUSD-NY 0.50–1.01 % · LON0700 0.25–0.51 % · DE40 1.42–3.08 % · JP225 0.87–1.01 % · UK100 0.52–1.04 % · US500 0.47–0.92 % |
| Cycle guards triggered | **0 of 60 asset-months** (worst month −4.4 %, best intramonth peak +13.0 %) |
| Days lost to `InpNoEntryLastDay` | 9–10 per run (≈ 5 % of the sample) |

---

## 3. Edge profile

### 3.1 Strategy class and why it should win

**Class: intraday momentum / volatility-expansion breakout (trend-following), with a time-stop.** It is not mean reversion: it buys strength and sells weakness and never fades a move.

The structural argument for the edge has three parts.

1. **Information arrives in bursts at the open and at scheduled releases.** The first hour of a cash session (or the 08:30 NY data window on EURUSD) is when overnight news and order imbalances are priced. On days with real directional information, the move that breaks the first-hour range tends to persist into the session ("intraday momentum"; see Gao, Han, Li & Zhou 2018, *Market Intraday Momentum*; Crabel 1990; Holmberg, Lönnbark & Lundström 2013; Zarattini & Aziz 2023 on ORB in equity indices).
2. **The range defines the risk.** A stop at the opposite edge only gets hit if the market fully reverses the opening auction. That is a natural invalidation point, and its distance (25–45 % of daily ATR) is large relative to spread, so costs are 1–5 % of 1R on the instruments that work.
3. **The regime filters select the days where (1) is likely:** a normal-width range versus ATR (not dead, not already exhausted), volatility that is not in the low tercile, and, on US500, the side of the daily trend.

**Where it loses (by design):** range days. Price breaks one edge, fails, and either reverses to the stop (−1R) or drifts back and is closed flat at the time exit. That is the cost of being positioned for trend days, and it shows in the loss tables.

### 3.2 What the class implies for the metrics

A trend-following breakout with a fixed stop has a recognisable signature. The time exit then shifts that signature in a predictable way.

| Metric | Pure breakout (stop / target only) | **CycleORB (breakout + time-stop)** | Why |
| --- | --- | --- | --- |
| Win rate | 30–45 % | **45–55 %** | Time exits convert many would-be stop-outs and target misses into small wins and losses |
| Realised payoff R | ≈ RR | **≈ 0.55–0.85 × RR (1.3–1.7)** | Winners are capped by the session end before they reach TP |
| Breakeven WR = 1/(1+R) | 25–35 % | **37–44 %** | Follows from R |
| Margin BM = WR − BWR | — | **+5 to +15 pp** | Typical of a thin intraday edge |
| Expectancy | +0.1 to +0.4R | **+0.10 to +0.30R** | |
| Profit factor | 1.2–1.6 | **1.3–1.9** | |
| Exit mix | SL 50–65 %, TP 35–50 % | **SL 15–45 %, TP 5–30 %, time 30–75 %** | The target is a cap, and the time exit does most of the work |
| Return shape | Bimodal (−1R / +RR) | Bimodal plus a central hump of time exits | |
| Median trade | < 0 | **≈ 0** | Most trades are small. The edge is in the right tail |
| Concentration | A few trend days carry the P&L | **Top 5 trades ≈ 40–120 % of net R** | Expected for trend-following, not a defect |
| Losing streaks | Long | 5–8 | Expected `ln(n)/ln(1/(1−WR))` ≈ 5–7 |
| Worst loss | −1R plus slippage | −1R normally. **−1.4 to −2.4R on releases and gaps** | Stop orders fill at market |

**Consequences for setting RR:**

- **The target only needs to be "far enough".** On every preset the TP sits 0.5–0.8 daily ATR beyond entry (§4.2). That distance is reachable only on trend days, so raising RR mostly lowers the TP-hit share without raising expectancy. LON0700 (RR 3.0) hits TP 6 % of the time and realises R 1.40. JP225 (RR 1.75) realises R 1.63, almost all of its RR.
- **Monitor R, not RR.** The `RR − R` gap is a property of the design. Treat a *change* in the gap as the signal, not its level.
- **Win rate must stay above BWR + M.** Because R is structurally about 1.3–1.7, the WR floor is about 40–44 %. A rolling WR below that for 30+ trades means the regime filter has stopped selecting trend days.

### 3.3 Per-preset edge character (observed)

| Preset | Character | Evidence |
| --- | --- | --- |
| EURUSD-NY | **Event breakout** (08:30 US data). Closest to a pure breakout | TP 28 % / SL 43 % / time 28 %. R distribution is bimodal (36 trades at about −1R, 35 at ≥ +1R). RR − R gap is only 0.37 |
| EURUSD-LON0700 | **London-open drift**. The target is decorative | Time exits 58 % (avg +0.67R), TP 6 % at 3R. RR − R gap 1.60. The edge is concentrated in two months (§6.4) |
| DE40 | **Volatility-expansion breakout**. The most "trend-following" profile | Highest SL share (47 %), lowest WR (45.6 %), time exits avg +0.73R |
| JP225 | **Session drift hold**. Low variance, carry-like | 75 % time exits (avg +0.19R). Losses average only −0.49R because the time exit cuts losers before the stop. Lowest SD (0.82R). Rolling-20 never negative |
| UK100 | **Breakout plus long beta** | Long +0.65R/trade versus short +0.12R. February alone = 12.8R of 19.8R |
| US500 | **Trend-side breakout** (explicitly trend-following via D1 SMA) | Only the trend-side order is armed, so the fill rate is 40 %. Short side −0.14R (n = 10) |

**Cross-asset observation: the index edges carry a long bias.** JP225, UK100 and US500 earn far more on the long side, in a year when the indices rose. Part of the index edge is directional beta that the time exit harvests. That is legitimate, but it will shrink in a falling or sideways index year.

---

## 4. Preset and geometry review

### 4.1 Preset registry (tester presets in `Profiles/Tester/ORB`, all 43 inputs set)

| Preset | Symbol | Range (local) | Entry end / flat | RR | Range/ATR band | Other filters | Risk cap | Magic |
| --- | --- | --- | --- | ---: | --- | --- | ---: | ---: |
| EURUSD-6M-NY | EURUSD | NY 08:00 + 30 | 11:30 / 15:00 | 2.0 | 17.5–35 % | cost ≤ 10 % | 1.0 % | 26110200 |
| EURUSD-LON0700 | EURUSD | LON 07:00 + 60 | 11:00 / 14:00 | 3.0 | ≥ 18 % | cost ≤ 20 %, buffer 10 % range | 0.5 % | 26110210 |
| DE40-6M-FRA | DE30 | LON 08:15 + 60 | 11:30 / 16:00 | 2.5 | 10–40 % | vol ≥ 33 | 1.0 % | 26110300 |
| DE40-6M-FRA-500USD | DE30 | LON 08:15 + 60 | 11:30 / 16:00 | 2.5 | 10–40 % | vol ≥ 33 | 3.0 % | 26110310 |
| JP225-6M-TKY | JPN225 | TKY 09:00 + 60 | 11:30 / 15:25 | 1.75 | 25–60 % | vol ≥ 33 | 1.0 % | 26110500 |
| UK100-6M-LON | UK100 | LON 08:15 + 60 | 11:30 / 16:25 | 2.5 | 10–50 % | vol ≥ 33 | 1.0 % | 26110800 |
| US500-6M-NY | SPX500 | NY 10:00 + 60 | 12:00 / 15:00 | 2.0 | 10–40 % | cost ≤ 15 %, trend side | 1.0 % | 26110900 |
| NVDA-6M-NY | NVDA | NY 09:30 + 30 | 13:30 / 15:50 | 1.5 | ≥ 40 % | cost ≤ 10 % | 1.0 % | 26110400 |
| TSLA-6M-NY | Tesla | NY 09:45 + 15 | 11:30 / 15:50 | 2.5 | 10–40 % | cost ≤ 10 %, vol ≥ 33 | 0.5 % | 26110700 |
| AAPL / MSFT / XOM | — | research only | | | | | 0.25–0.5 % | 26110600 / 1100 / 1000 |

**Preset hygiene:** the v1.08 fixes are in place. Every tester preset lists all 43 inputs, every magic base is unique, and the `Profiles/Tester/ORB` copies match `Presets/*_chart.set` (DE40-FRA differs only in file encoding). `CycleORB_EURUSD_v1_baseline.set` and `_NYonly.set` are legacy optimiser files at 8 % risk on the wrong server clock. Archive them so they can't be loaded by mistake.

### 4.2 Geometry in daily-ATR units

Stop ≈ range + buffer. TP distance = RR × stop. Values are median armed ranges from the logs.

| Preset | Range ≈ % ATR | Stop ≈ % ATR | TP beyond entry ≈ % ATR | TP hit | Time-exit share (avg R) | RR − R gap |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| EURUSD-NY | 22.5 | 24 | 48 | 28 % | 28 % (+0.56) | 0.37 |
| EURUSD-LON0700 | 24.9 | 27 | 82 | 6 % | 58 % (+0.67) | 1.60 |
| DE40-500USD | 29.3 | 31 | 77 | 15 % | 38 % (+0.73) | 0.94 |
| JP225-TKY | 41.5 | 44 | 76 | 10 % | 75 % (+0.19) | 0.12 |
| UK100-LON | 30.5 | 32 | 80 | 22 % | 41 % (+0.47) | 0.88 |
| US500-NY | 27.8 | 29 | 58 | 10 % | 60 % (+0.45) | 0.70 |

**Reading:**

- **The TP needs a 0.5–0.8 ATR one-way extension after the first hour.** That only happens on trend days, so TP hit rates of 6–28 % are what the geometry predicts. Time exits are positive on average on every preset, which confirms the session-drift part of the edge.
- **EURUSD-NY has the tightest geometry** (TP 0.48 ATR) and the smallest RR − R gap. It is the only preset that behaves like a classic stop/target breakout.
- **LON0700's 3R target is effectively unreachable** (6 %). Lowering it would not obviously help: time exits average +0.67R, and the target is out of the way. Leave it, but don't read the 3R as the operating payoff.
- **JP225's wide range (41.5 % ATR) leaves little room for drift.** Hence most trades are small time exits, and the very low SD comes with low payoff per trade.
- **The cost-to-stop ratio is healthy everywhere tested** (median spread / range 0.9–4.2 %). Cost is not the binding constraint on these six.

---

## 5. Performance and key metrics

### 5.1 Health vector (framework §5.3)

R values come from tester fill prices, so spread is included. There is no commission on YWO. M is the Wilson 95 % half-width. "EF stressed" subtracts an extra slippage prior of one spread per trade.

| Preset | n | WR | AW | AL | R | RR | BWR | BM | M | EF stressed | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EURUSD-NY | 95 | 48.4 % | 1.51 | 0.93 | 1.63 | 2.0 | 38.0 % | +10.4 pp | 9.9 pp | +8.8 pp | Fragile (borderline) |
| EURUSD-LON0700 | 124 | 51.6 % | 1.15 | 0.82 | 1.40 | 3.0 | 41.6 % | +10.0 pp | 8.7 pp | +8.5 pp | Fragile (borderline) |
| DE40-500USD | 68 | 45.6 % | 1.49 | 0.96 | 1.56 | 2.5 | 39.1 % | +6.5 pp | 11.5 pp | +6.1 pp | Fragile |
| JP225-TKY | 77 | 51.9 % | 0.80 | 0.49 | 1.63 | 1.75 | 38.0 % | +14.0 pp | 10.9 pp | +13.4 pp | Robust |
| UK100-LON | 54 | 53.7 % | 1.46 | 0.90 | 1.62 | 2.5 | 38.2 % | +15.5 pp | 12.9 pp | +14.3 pp | Robust (biased sample, §9 N3) |
| US500-NY | 40 | 50.0 % | 1.07 | 0.82 | 1.30 | 2.0 | 43.6 % | +6.4 pp | 14.8 pp | +5.3 pp | Fragile |

### 5.2 Return and risk

| Preset | E (R) | Median R | PF | SQN | Σ R | Return | Max DD closed (% / R) | Max L-streak (expected) | Full Kelly | MC P50 / P95 DD* | MC P5 terminal* |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | --- | ---: |
| EURUSD-NY | +0.254 | −0.01 | 1.53 | 1.86 | +24.1 | +24.7 % | 4.7 % / 5.0R | 5 (6.9) | 16.8 % | 4.9 / 8.3 % | 1.10 |
| EURUSD-LON0700 | +0.198 | +0.06 | 1.50 | 1.83 | +24.5 | +9.2 % | 4.4 % / 11.3R | 7 (6.6) | 17.1 % | 3.1 / 6.2 % | 1.00 |
| DE40-500USD | +0.158 | −0.47 | 1.30 | 0.95 | +10.7 | +22.0 % | 11.4 % / 5.4R | 5 (6.9) | 10.6 % | 14.4 / **25.5 %** | 0.88 |
| JP225-TKY | +0.180 | +0.02 | 1.77 | 1.92 | +13.9 | +14.1 % | 3.7 % / 4.1R | 7 (5.9) | 22.6 % | 3.3 / 6.2 % | 1.05 |
| UK100-LON | +0.367 | +0.33 | 1.88 | 1.97 | +19.8 | +14.2 % | 6.2 % / 7.3R | **8 (5.2) — DEPENDENCE flag** | 25.1 % | 4.7 / 9.2 % | 1.00 |
| US500-NY | +0.121 | 0.00 | 1.30 | 0.69 | +4.9 | +4.1 % | 4.1 % / 5.3R | 7 (5.3) | 11.4 % | 3.9 / 8.3 % | 0.95 |

\* Block bootstrap (block 5, 5,000 paths) of the trade R sequence at each run's median effective risk.

**Key reads:**

- **Operating risk is 1/10 to 1/25 of full Kelly** on every preset. That is appropriately conservative given the sample uncertainty. The DE40-500USD variant is the exception: at a median 2.1 % risk its **P95 drawdown (25.5 %) breaches the framework's 25 % limit**.
- **SQN is about 1.8–2.0 on EURUSD-NY, LON0700, JP225 and UK100** (good for an intraday system on small samples), and below 1 on DE40-500USD and US500.
- **UK100's 8-loss streak is 1.5× its expected maximum.** This triggers the framework's DEPENDENCE flag (8 straight losses, 2026-06-29 → 09-02).
- **The tail is mild.** The largest single loss is 1–3 % of gross profit (10 % on US500 because of the holiday gap). The framework's TAIL_RISK flag (> 15 %) is not raised.

### 5.3 Fill and filter funnel (about 213–216 weekdays per run)

| Preset | Range ATR band too low | Too high | H1 vol < 33 | Other skips | **Armed days** | Order sides skipped (lot < min) | **Filled** | Fill / armed |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| EURUSD-NY | 98 | 13 | — | 10 last day, 2 price through | 95 | 0 | 95 | 100 % |
| EURUSD-LON0700 | 57 | 1 | — | 10 last day | 148 | 34 | 124 | 84 % |
| DE40-500USD | 0 | 60 | 64 | 10 last day | 79 | 20 | 68 | 86 % |
| JP225-TKY | 28 | 31 | 49 | 10 last day | 98 | 0 | 77 | 79 % |
| UK100-LON | 0 | 31 | 59 | 9 last day, ~14 warm-up | 98 | **82** | 54 | 55 % |
| US500-NY | 0 | 104 | — | 10 last day | 101 | 0 (one side only) | 40 | 40 % |

The filters remove 45–64 % of days. That is consistent with a regime-selected edge. EURUSD-NY fills on every armed day: the 08:30 release always breaks one side.

---

## 6. Trade profile — winners and losers

### 6.1 R distribution (trade counts)

| R bucket | EURUSD-NY | LON0700 | DE40-500USD | JP225 | UK100 | US500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| < −1.05 (slipped stop) | 6 | 1 | 8 | 0 | 2 | 4 |
| −1.05 … −0.5 | 36 | 48 | 26 | 17 | 20 | 9 |
| −0.5 … 0 | 7 | 11 | 3 | 20 | 3 | 7 |
| 0 … 0.5 | 4 | 14 | 7 | 15 | 3 | 5 |
| 0.5 … 1 | 7 | 24 | 3 | 11 | 11 | 6 |
| 1 … 2 | 19 | 18 | 10 | 14 | 3 | 6 |
| ≥ 2 | 16 | 8 | 11 | 0 | 12 | 3 |

**The shapes match §3.2.** EURUSD-NY, DE40 and UK100 are bimodal breakouts. JP225 and LON0700 have a large central hump of time exits.

### 6.2 Winners versus losers

| Preset | Avg win | Avg loss | Win/loss by exit | Long E (n) | Short E (n) | Median hold |
| --- | ---: | ---: | --- | --- | --- | ---: |
| EURUSD-NY | +1.51R | −0.93R | TP +1.96 · time +0.56 · SL −1.07 | +0.17 (46) | **+0.33** (49) | 126 min |
| EURUSD-LON0700 | +1.15R | −0.82R | TP +3.15 · time +0.67 · SL −1.01 | **+0.26** (66) | +0.13 (58) | 299 min |
| DE40-500USD | +1.49R | −0.96R | TP +2.50 · time +0.73 · SL −1.04 | +0.11 (33) | **+0.20** (35) | 277 min |
| JP225-TKY | +0.80R | −0.49R | TP +1.75 · time +0.19 · SL −1.01 | **+0.25** (44) | +0.09 (33) | 298 min |
| UK100-LON | +1.46R | −0.90R | TP +2.50 · time +0.47 · SL −1.02 | **+0.65** (25) | +0.12 (29) | 283 min |
| US500-NY | +1.07R | −0.82R | TP +2.02 · time +0.45 · SL −1.16 | **+0.21** (30) | −0.14 (10) | 219 min |

### 6.3 Worst trades — the loss tail

| Preset | Worst trades | Cause |
| --- | --- | --- |
| EURUSD-NY | −2.40R (2026-03-06), −1.77R (2026-01-09), −1.26R (05-13) | **Both of the worst are US payroll (NFP) Fridays.** The stop filled with slippage during the release (hold 26 min and 2 min) |
| US500-NY | −2.23R (06-19), −1.47R (05-25), −1.06R (02-16) | **All three are US holidays** (Juneteenth, Memorial Day, Presidents' Day). Juneteenth was held over the weekend and gapped through the stop |
| DE40-500USD | −1.41R (05-22), −1.13R, −1.12R | Stop slippage on fast moves |
| JP225 / LON0700 / UK100 | ≥ −1.13R | Clean: stops fill within about 0.1R |

Mean entry slippage is negligible (+0.004 to +0.044R). **The loss tail is an exit-side problem: news and gap stops.**

### 6.4 Concentration (top 5 trades as a share of net R)

EURUSD-NY 42 % · JP225 63 % · UK100 63 % · LON0700 66 % · DE40-500USD 117 % · US500 201 %.

That is the normal trend-following profile, but three cases deserve a flag.

- **LON0700:** July (+13.2R) and October (+11.7R) together make +24.9R, more than the full-sample +24.5R. **The other eight months net about 0.** The first half of the sample is negative (−0.11R/trade, PF 0.78). The second half is +0.50R (PF 2.66).
- **UK100:** February (+12.8R in 9 trades) is 65 % of net R. Excluding February: 45 trades at +0.16R.
- **DE40:** the five best trades exceed the total. The remaining 63 trades are net negative.

### 6.5 Day of week (indicative only, n = 6–28 per cell)

DE40 Friday −0.54R (n = 15) and UK100 Wednesday +1.10R (n = 12) stand out. Neither sample is large enough to filter on (ROADMAP P3-T04: data first).

---

## 7. Rolling windows

### 7.1 Rolling 20-trade expectancy (R), sampled at month end

| Month | EURUSD-NY | LON0700 | DE40-500USD | JP225 | UK100 | US500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-02 | +0.54 | −0.44 | — | — | — | — |
| 2026-03 | +0.54 | −0.26 | — | +0.21 | — | — |
| 2026-04 | +0.30 | +0.18 | +0.28 | +0.15 | — | — |
| 2026-05 | +0.03 | +0.37 | +0.09 | +0.08 | +0.53 | — |
| 2026-06 | +0.19 | −0.07 | +0.13 | +0.39 | +0.29 | +0.17 |
| 2026-07 | +0.36 | +0.91 | +0.17 | +0.28 | +0.07 | +0.18 |
| 2026-08 | +0.33 | +0.48 | +0.26 | +0.20 | −0.05 | +0.06 |
| 2026-09 | +0.39 | +0.17 | **−0.15** | +0.02 | +0.41 | +0.03 |
| 2026-10 | +0.21 | +0.55 | **−0.03** | **+0.05** | +0.23 | +0.04 |

### 7.2 Rolling 30-trade expectancy (R), sampled at month end

| Month | EURUSD-NY | LON0700 | DE40-500USD | JP225 | UK100 | US500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-03 | +0.47 | −0.31 | — | — | — | — |
| 2026-04 | +0.40 | −0.03 | — | — | — | — |
| 2026-05 | +0.15 | +0.21 | — | +0.22 | — | — |
| 2026-06 | +0.11 | +0.12 | +0.12 | +0.18 | +0.59 | — |
| 2026-07 | +0.31 | +0.41 | +0.14 | +0.34 | +0.26 | — |
| 2026-08 | +0.31 | +0.55 | +0.08 | +0.24 | +0.03 | +0.10 |
| 2026-09 | +0.38 | +0.17 | +0.11 | +0.14 | +0.22 | +0.01 |
| 2026-10 | +0.24 | +0.41 | +0.14 | +0.07 | +0.22 | +0.11 |

### 7.3 Rolling 20-trade win rate / profit factor, sampled at month end

| Month | EURUSD-NY | LON0700 | DE40-500USD | JP225 | UK100 | US500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-04 | 55 / 1.65 | 55 / 1.52 | 45 / 1.49 | 45 / 1.69 | — | — |
| 2026-05 | 45 / 1.07 | 65 / 2.62 | 40 / 1.14 | 50 / 1.26 | 55 / 2.43 | — |
| 2026-06 | 50 / 1.45 | 35 / 0.88 | 40 / 1.21 | 65 / 3.77 | 50 / 1.61 | 60 / 1.41 |
| 2026-07 | 60 / 1.87 | 65 / 4.52 | 50 / 1.36 | 55 / 2.44 | 40 / 1.13 | 55 / 1.44 |
| 2026-08 | 55 / 1.72 | 45 / 2.39 | 55 / 1.63 | 50 / 1.82 | 35 / 0.93 | 50 / 1.13 |
| 2026-09 | 50 / 1.78 | 50 / 1.53 | 45 / 0.69 | 45 / 1.06 | 50 / 1.90 | 45 / 1.06 |
| 2026-10 | 40 / 1.43 | 70 / 2.81 | 45 / 0.93 | 40 / 1.20 | 55 / 1.57 | 45 / 1.10 |

### 7.4 Rolling summary across all 20-trade windows

| Preset | Windows | Min | Max | Last | % windows > 0 | Min rolling PF | Reading |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EURUSD-NY | 76 | −0.08 | +0.72 | +0.21 | **96 %** | 0.85 | **Stable**: only one shallow dip (May) |
| EURUSD-LON0700 | 105 | **−0.55** | +0.93 | +0.55 | 70 % | 0.24 | **Regime-dependent**: long negative stretch Jan–Mar, strong recovery |
| DE40-500USD | 49 | −0.16 | +0.37 | −0.03 | 90 % | 0.69 | **Compressing**: below zero since September |
| JP225-TKY | 58 | +0.02 | +0.40 | +0.05 | **100 %** | 1.06 | **Most stable**, but sliding from +0.39 (June) to +0.05 |
| UK100-LON | 35 | −0.12 | +0.80 | +0.23 | 89 % | 0.82 | Volatile, driven by February |
| US500-NY | 21 | −0.02 | +0.36 | +0.04 | 90 % | 0.95 | Flat near zero since September |

### 7.5 Monthly results (trades / Σ R / cycle P&L %)

| Month | EURUSD-NY | LON0700 | DE40-500USD | JP225 | UK100 | US500 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-01 | 17 / +2.3R / +1.8 % | 14 / −6.7R / −2.5 % | 8 / +2.3R / +4.5 % | 7 / +0.4R / +0.5 % | 2 / −0.3R / −0.1 % | 2 / +1.4R / +1.4 % |
| 2026-02 | 7 / +4.5R / +4.0 % | 9 / −1.9R / −1.1 % | 3 / +3.0R / +7.8 % | 8 / +3.3R / +3.1 % | 9 / +12.8R / +9.3 % | 3 / +0.3R / +0.1 % |
| 2026-03 | 10 / +3.3R / +3.4 % | 9 / −1.2R / −0.2 % | 7 / −1.5R / −4.4 % | 12 / +1.0R / +1.1 % | 3 / +1.2R / +1.4 % | 4 / −2.1R / −1.6 % |
| 2026-04 | 8 / +0.9R / +0.9 % | 9 / +3.1R / +1.0 % | 4 / +1.5R / +1.9 % | 2 / +0.7R / +0.7 % | 3 / +0.2R / +0.4 % | 7 / +2.5R / +2.2 % |
| 2026-05 | 8 / −2.3R / −1.3 % | 15 / +5.1R / +1.8 % | 7 / +1.2R / +6.2 % | 9 / +3.3R / +3.2 % | 6 / −1.1R / −1.1 % | 3 / −0.1R / −0.2 % |
| 2026-06 | 7 / +5.1R / +4.2 % | 17 / −0.8R / −0.4 % | 11 / +3.3R / +8.3 % | 10 / +3.7R / +3.6 % | 8 / +5.5R / +3.0 % | 5 / +2.2R / +1.7 % |
| 2026-07 | 9 / +3.4R / +2.9 % | 13 / +13.2R / +5.0 % | 14 / −0.1R / −0.0 % | 8 / +1.4R / +1.3 % | 4 / −3.2R / −2.9 % | 3 / +0.1R / +0.2 % |
| 2026-08 | 7 / +2.0R / +1.9 % | 11 / +0.0R / +0.1 % | 2 / −0.3R / −1.5 % | 3 / −1.1R / −1.1 % | 2 / −2.1R / −1.7 % | 6 / −1.0R / −1.2 % |
| 2026-09 | 12 / +5.6R / +5.4 % | 13 / +2.1R / +0.8 % | 7 / +1.3R / −1.1 % | 8 / −0.5R / −0.5 % | 9 / +6.3R / +5.5 % | 2 / −1.4R / −1.1 % |
| 2026-10 | 10 / −0.5R / −0.5 % | 14 / +11.7R / +4.6 % | 5 / −0.0R / −0.7 % | 10 / +1.7R / +1.6 % | 8 / +0.5R / +0.2 % | 5 / +2.9R / +2.5 % |
| **Mean / median %** | **+2.25 / +2.38** | +0.91 / +0.48 | +2.09 / +0.94 | +1.34 / +1.16 | +1.39 / +0.27 | +0.41 / +0.17 |

**DE40-500USD shows lot granularity.** In September it made +1.3R but lost 1.1 % of capital, because the winners happened to trade at a smaller effective risk than the losers (0.1-lot steps at 500 USD). At this account size, R and % returns can diverge in sign within a month.

---

## 8. Portfolio view

Daily-R correlation on days when both presets traded (n = shared days):

| Pair | ρ | n | Reading |
| --- | ---: | ---: | --- |
| DE40 – UK100 | **0.67** | 28 | Same 08:15–09:15 London window. **One European-open bet, not two** |
| EURUSD-NY – UK100 | 0.47 | 23 | Small n |
| DE40 – US500 | 0.34 | 15 | Small n |
| JP225 – UK100 | 0.31 | 21 | Small n |
| All other pairs | −0.20 … +0.12 | 14–58 | Effectively independent |

All six presets at 1R each: 458 trades, Σ +97.9R, **E +0.21R**, closed-trade max DD 10.7R. Eight of ten months positive (January −0.6R, August −2.5R). **JP225 (Asia) and the EURUSD presets are the real diversifiers.**

---

## 9. Log review — defects and anomalies

| # | Severity | Finding | Evidence | Effect | Simplest fix |
| --- | --- | --- | --- | --- | --- |
| N1 | **High** — ✅ fixed v1.09 (`InpSkipDates`) | **The time exit fails when the market closes before the exit time (exchange holidays and early closes)** | US500: `CLOSE FAIL retcode=10018 [Market closed]` × 18,836 on 2026-05-25 (Memorial Day) and 2026-06-21 (after Juneteenth, Friday 06-19). Position #81 was held **Friday → Sunday** and stopped at 7470.90 against a 7487.03 stop | Overnight and weekend gap risk in an "always flat" EA. 3 holiday trades = −4.75R. Ex-holiday US500 E = +0.26R (versus +0.12R) | Add a holiday skip-date input (CSV of dates, which can share the ROADMAP P3-T03 news-blacklist mechanism) so no orders arm on those days. Same exposure for NVDA, TSLA and US500 on US holidays |
| N2 | Medium — ✅ fixed v1.09 | Close retries run on every tick | 3 log lines per tick × 18,836 ticks ≈ 56k lines (the log reached 16 MB) | Log flood. Tester slow-down | On retcode 10018, log once and retry at most once a minute |
| N3 | Medium | **Small-account sizing changes which days trade** | `lot below broker minimum`: UK100 82 order sides (41 of 98 armed days), LON0700 34, DE40-500USD 20 | The skipped days are the **wide-range** days, so the result is from a narrower-range subset than the preset was designed for. The UK100 +0.37R is not a test of the 1 % preset | Score presets at 10k deposit with a fixed `InpCycleCapital`. Treat 500 USD runs as a feasibility check |
| N4 | Medium | Indicator warm-up in the tester | UK100: `daily ATR unavailable` on 2026-01-02, 01-05 and 01-06, then `H1 vol percentile unavailable` 2026-01-07 → 01-22 | About 14 trading days with no trade decision at the start of the run | Start tester runs at least 1 month before the scoring window, or exclude the first month |
| N5 | Medium | Stop slippage on releases and gaps | EURUSD-NY −2.40R and −1.77R on NFP Fridays. DE40 −1.41R. US500 −2.23R gap | The real worst loss is about −2.4R, not −1R. Sizing assumes −1R (v1.07 review, issue 6) | Track the share of losses below −1.2R as a health metric. News-day handling remains a research item (P3-T03) |
| N6 | Low | The monthly cycle never engaged | 0 HALT / STOP / ratchet events in 60 asset-months. Largest intramonth giveback: DE40 January peak +11.7 % → close +4.5 % | Confirms the v1.07 finding: the cycle is a catastrophe guard at these risk levels | Decide its role (v1.07 review §4.6) |
| N7 | Low | Open items from v1.07 still present | The `WARNING built and defaulted for EURUSD` line fires on DE30, JPN225, UK100 and SPX500. Pending orders are still `ORDER_TIME_GTC` | Journal noise. Lost time exit if the terminal is down | As in the v1.07 review |
| N8 | Info — ✅ fixed v1.09 (`Init OK v1.09 … skip dates=N`) | The build that ran can't be identified from the log | The `Init OK` line has no version. Sources are stamped 2026-11-05 16:04 (after the runs) and the `.ex5` on disk is 2026-11-04 | Traceability | Print `__MQL5BUILD__` / the version in `Init OK` |
| N9 | Info | The LON0700 run was executed twice, with identical results | Final 546.14 USD both times | **Confirms deterministic replay** | — |
| N10 | Info | Holiday trading on other assets was harmless | EURUSD-NY (MLK Day +0.80R), LON0700 (UK bank holidays +0.81R and +0.58R), JP225 (JP holidays +0.46R and −0.18R). No close failures | FX and the JP225 CFD keep trading through those holidays | — |

---

## 10. How this evidence compares with the v1.07 review

| Preset | Previous evidence | Today (tester 2026 Jan–Oct, 500 USD) | Reading |
| --- | --- | --- | --- |
| EURUSD-NY | Tester 24 m: 199 tr, WR 44.7 %, +0.20R | 95 tr, WR 48.4 %, **+0.25R** | Consistent. Slightly stronger |
| EURUSD-LON0700 | Tester 12 m: 170 tr, +0.16R. Replica 6 y: +0.10R | 124 tr, +0.20R | Consistent, but with high month concentration |
| DE40 | Tester 17 m @1 %: 120 tr, +0.22R. Offline 500 USD projection Jan–Oct: 64 tr, +19.3 %, DD 10.8 % | 68 tr, +0.16R, **+22.0 %, DD 11.4 %** | **Offline 500 USD model confirmed by the tester** (pending item from v1.07 closed). Edge weaker in H2 |
| JP225 | Tester 17 m: 106 tr, WR 54.7 %, +0.17R | 77 tr, WR 51.9 %, +0.18R | Consistent. Rolling expectancy is now sliding |
| UK100 | Mirror 10.5 m: 94 tr, +0.32R (no tester) | **First tester run**: 54 tr, +0.37R | Directionally confirms. Sample biased by lot minimum (N3) |
| US500 | Mirror 45 m: 225 tr, +0.16R (no tester) | **First tester run**: 40 tr, +0.12R (+0.26R ex-holidays) | Directionally confirms. Holiday defect found (N1) |

---

## 11. Monitoring thresholds (forward test)

These come from the edge profile in §3.2 and the observed values above. Evaluate at each month end on the rolling 30-trade window.

| Metric | Healthy | Investigate | Stop / re-score |
| --- | --- | --- | --- |
| Rolling-30 expectancy | ≥ +0.10R | 0 to +0.10R | < 0 at two consecutive month ends |
| Rolling-30 WR | ≥ BWR + 5 pp (≈ 44–48 %) | BWR … BWR + 5 pp | < BWR (≈ 38–44 %) |
| Realised R | 1.3–1.8 | ±0.3 change from the preset's baseline | < 1.1 |
| SL share of exits | ≤ baseline + 10 pp | +10 to +20 pp | > baseline + 20 pp (filters no longer select trend days) |
| Losses < −1.2R | ≤ 1 in 30 | 2–3 in 30 | > 3 in 30 (execution or news problem) |
| Time-exit average R | > 0 | ≈ 0 | < 0 for 30 trades (session drift gone) |
| Max losing streak | ≤ 1.5 × `ln(n)/ln(1/(1−WR))` | — | Above that: DEPENDENCE review |

**Current flags:** DE40 rolling-20 is below zero, JP225's is at +0.05 (its card's compression trigger), and UK100 carries the DEPENDENCE flag.

---

## 12. Recommendations

**Priority 1 — before any forward test on US-session presets**

1. **Fix N1.** Add a holiday skip-date input so no orders are armed on exchange holidays or early-close days, and throttle the retcode-10018 retry loop (N2). This affects US500, NVDA and TSLA.
2. **Re-score at a realistic size:** 10,000 deposit, fixed `InpCycleCapital`, start one month before the scoring window (N3, N4). Use the longest real-tick window, 2025-06-18 → 2026-10-31. Run UK100, US500 and DE40 (1 %) first. NVDA, TSLA and MSFT are still pending from the v1.07 review.

**Priority 2 — allocation**

3. **Forward-test candidates:** EURUSD-NY (most stable rolling profile) and JP225 (highest quality, diversifying session). Hold DE40 and UK100 as **one** European-open allocation (ρ 0.67).
4. **DE40-500USD:** the tester confirms the offline model, but its P95 drawdown (25.5 %) exceeds the 25 % limit and the rolling edge is negative since September. Don't promote it until the rolling-30 expectancy is back above +0.10R.
5. **LON0700:** keep it at 0.5 % research size. Its whole year came from two months.

**Priority 3 — housekeeping**

6. Print the EA version in `Init OK` (N8). Drop the EURUSD init warning, and consider broker-side order expiry (N7).
7. Archive `CycleORB_EURUSD_v1_baseline.set` and `CycleORB_EURUSD_v1_NYonly.set` (wrong clock, 8 % risk).

**Out of scope (unchanged):** trailing stops, break-even moves, partial exits and re-entries. The geometry analysis (§4.2) shows the payoff is set by the session clock, not by trade management.

---

## 13. v1.09 re-score (2026-11-05): DE40, UK100, US500 at 500 and 1000 USD

### 13.1 What changed in v1.09

| Change | Where | Behaviour |
| --- | --- | --- |
| `InpSkipDates` (group "Calendar") | `Config.mqh`, `Setup.mqh` | Exchange-local dates (YYYYMMDD, comma-separated) on which no orders are armed. Logged as `SKIP <setup> <date>: skip date (holiday / early close)`. Invalid dates refuse init |
| Market-closed backoff | `Orders.mqh` | A delete or close rejected with `TRADE_RETCODE_MARKET_CLOSED` is retried at most once a minute, and each failure is logged with `(market closed, retry in 60 s)` |
| Version in the journal | `CycleORB.mq5` | `Init OK v1.09 <symbol> … skip dates=N` |
| Presets | `Presets/*.set`, `Profiles/Tester/ORB/*.set` | Every preset lists `InpSkipDates` (44 inputs). US500, NVDA, TSLA and the US research presets carry NYSE holidays and 13:00 early closes for 2026–2027. UK100 carries LSE holidays and half days. DE40 (both variants) carries Xetra holidays. EURUSD and JP225 are empty (those markets traded through local holidays without a failed exit) |

The build compiles with 0 errors and 0 warnings. **The lists end on 2027-12-31 and must be extended each year.**

### 13.2 Runs

| ini (`tester/`) | Preset | Window | Deposit |
| --- | --- | --- | --- |
| `run_v109_DE40_FRA_500USD_2025Jul_2026Oct_{500,1000}USD` | DE40-6M-FRA-500USD (3 % cap) | 2025-07-01 → 2026-10-31 | 500 / 1000 |
| `run_v109_US500_NY_2025Jul_2026Oct_{500,1000}USD` | US500-6M-NY (1 %) | 2025-07-01 → 2026-10-31 | 500 / 1000 |
| `run_v109_UK100_LON_2025Dec_2026Oct_{500,1000}USD` | UK100-6M-LON (1 %) | 2025-12-17 → 2026-10-31 (broker history starts here) | 500 / 1000 |

DE40 uses the 500USD variant because at 500–1000 USD the 1 % preset would skip most days (0.1 lot × ~1.16 USD/pt × a median 101-point stop ≈ 11.8 USD, more than 1 % of 1000).

### 13.3 Results

| Run | n | WR | R | E (R) | PF | SQN | Return | Max DD (closed) | Cycle months + | MC P95 DD | Rolling-20 last / min |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| DE40-500USD @ 500 | 120 | 49.2 % | 1.57 | **+0.235** | 1.52 | 1.91 | +86.3 % | 15.1 % | 12 / 16 | 24.5 % | −0.03 / −0.25 |
| DE40-500USD @ 1000 | 120 | 49.2 % | 1.57 | **+0.235** | 1.52 | 1.91 | +102.2 % | 13.8 % | 10 / 16 | 27.4 % | −0.03 / −0.25 |
| UK100 @ 500 | 54 | 53.7 % | 1.62 | +0.367 | 1.88 | 1.97 | +14.2 % | 6.2 % | 6 / 10 | 9.4 % | +0.23 / −0.12 |
| **UK100 @ 1000** | **88** | 52.3 % | 1.82 | **+0.396** | **1.99** | **2.77** | +28.6 % | 5.2 % | 6 / 10 | 9.1 % | +0.44 / −0.08 |
| US500 @ 500 | 71 | 56.3 % | 1.51 | **+0.279** | 1.95 | 2.35 | +16.1 % | 4.0 % | 11 / 16 | 7.0 % | +0.25 / **+0.15** |
| US500 @ 1000 | 71 | 56.3 % | 1.51 | **+0.279** | 1.95 | 2.35 | +18.6 % | 4.7 % | 11 / 16 | 7.4 % | +0.25 / **+0.15** |

Framework view: all three presets are Robust (stressed EF > M). DE40: BM +10.2 pp vs M 8.8 pp. UK100 @ 1000: +16.8 vs 10.2. US500: +16.5 vs 11.2.

### 13.4 Findings

1. **The holiday fix works.** US500 logged 6 skip-date SKIPs (2026-01-19, 02-16, 05-25, 06-19, 07-03, 09-07), **0 `CLOSE FAIL` lines** (versus 18,836), and its worst loss is now −1.05R (versus −2.23R). In Jan–Oct 2026 alone, US500 went from 40 trades at +0.12R to 37 trades at **+0.26R**, which matches the ex-holiday estimate in §9.
2. **Holidays not on a list still leak, which confirms the mechanism.** The 2025 part of the window has no skip dates. US500 traded the 2025-07-03 early close (−0.56R, exit 9 h late) and the 2025-12-24 early close, where the position was **held about 38 hours, through Christmas**, until the first tick on Dec 26 (+0.47R by luck). Every year that is traded needs its dates.
3. **Deposit size matters only where the minimum lot binds.**
   - **US500:** identical trades at 500 and 1000 (0.1-lot steps of 1 USD/pt are fine-grained enough).
   - **DE40-500USD:** identical trades at 500 and 1000 over this window, because by 2026 the account had compounded past the lot-minimum threshold. A *fresh* 500 USD start still skips wide-range days (20 order sides in the Jan–Oct 2026 run).
   - **UK100:** at 500 USD, 82 order sides are skipped and only 54 trades remain. **At 1000 USD there are no skips: 88 trades, and expectancy and PF are both higher.** UK100 needs about 1000 USD at 1 % risk to trade as designed.
4. **UK100 is now the strongest index preset:** 88 trades, +0.40R, PF 1.99, SQN 2.77, rolling-20 positive in 97 % of windows. The long/short split is balanced in the full sample (+0.50R / +0.30R), unlike the biased 500 USD subset. February 2026 is still the best month (+14.7R). Excluding it: 76 trades, +0.27R.
5. **US500 has the cleanest profile once holidays are removed:** WR 56 %, losses average only −0.67R (66 % time exits), and rolling-20 never below +0.15R across 16 months.
6. **DE40 works but is weakening.** The first half is +0.37R (PF 2.02) and the second half +0.10R (PF 1.18). Rolling-20 has been −0.15R and −0.03R since September, while rolling-30 is still +0.14R. The edge is mostly on the short side (+0.45R versus +0.02R long). **At 2.2–2.6 % effective risk, the P95 drawdown (24.5–27.4 %) sits on the framework's 25 % limit.**
7. **The monthly cycle is still dormant.** The largest intramonth peak was +17.5 % (DE40 @ 500, Dec 2025), short of the +20 % ratchet arm. No soft halt or hard flatten.

### 13.5 Verdicts at a 500–1000 USD deposit

| Preset | Verdict | Condition |
| --- | --- | --- |
| **US500-NY** | **Forward-test candidate** (upgraded from "weakest") | v1.09 with skip dates. Extend the date list for every year traded |
| **UK100-LON** | **Forward-test candidate at ≥ 1000 USD** | At 500 USD it trades a biased subset. Treat it and DE40 as one European-open allocation (ρ 0.67) |
| **DE40-500USD** | Keep, on watch | Rolling-20 below zero. Stop rule from §11: rolling-30 < 0 at two consecutive month ends. Consider a 2 % cap once the account is ≥ 1000 USD: 0.1 lot then covers stops up to ≈ 170 points, which should bring the P95 drawdown under 25 % (not yet tested) |

---

## Appendix A — Method

- **Parsing:** each run was split on `testing of ... started with inputs`. Trades were rebuilt from `PLACE`, `order [#n] triggered`, `deal #… done (based on order #n)`, `stop loss triggered` / `take profit triggered` / `market … close #n`. Filters come from `RANGE` / `SKIP` lines, and monthly results from `CYCLE_END` / `CYCLE_PARTIAL`.
- **R per trade** = signed (exit fill − entry fill) / |planned entry − stop|. Fills are at bid/ask, so spread is included. YWO charges no commission. Swap affects only the two US500 overnight holds.
- **USD reconciliation:** one conversion factor per run, solved against the final balance. Sanity checks: EURUSD 100,000 / lot (exact), DE30 ≈ 1.165 (EURUSD), UK100 ≈ 1.357 (GBPUSD), JPN225 ≈ 1/159, SPX500 0.92 (below 1.0 because of swap on the two holiday holds).
- **Drawdown** is on closed-trade equity. Tester equity drawdown (intratrade) will be slightly higher.
- **Monte Carlo:** block bootstrap with block length 5 and 5,000 paths, compounded at the run's median effective risk.
- **Holiday lists:** US (NYSE), UK and DE bank holidays, and JP national holidays for 2026.
- The duplicate LON0700 run is excluded from all aggregates.

## Appendix B — Sources

- `Tester/logs/20261105.log` (runs at 15:44–15:57, 2026-11-05)
- `MQL5/Profiles/Tester/ORB/*.set` and `Experts/CycleORB/Presets/*.set`
- `Experts/CycleORB/CycleORB.mq5`, `Include/{Config, SessionClock, Cycle, Orders, Setup}.mqh`
- `Experts/CycleORB/ROADMAP.md`, `doc/CycleORB_Review_v107.md`, `doc/unified_edge_framework.md`
