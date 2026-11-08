# CycleORB AI OS — Promotion Queue (L8)

Every AI OS candidate needs one page here and a human sign-off before it reaches a live account. A candidate moves **Research → Forward test (AOS-P7, demo) → Live (`edge_framework.md` rung R2) → Scale (R3)**. It is never promoted on backtest evidence alone.

## Template

| Field | Content |
| --- | --- |
| Candidate | Preset set, EA version, date |
| Changes vs production | Exact inputs that differ from the frozen production presets |
| Evidence | Tester runs (`tester/aos/runs/...`), comparison harness verdicts, portfolio replay |
| Health deltas | E, E_N, EF, AL, worst event, MaxDD, fire retention, per asset |
| Skip precision / guard exits | Withheld or aborted trades and their baseline R |
| Negative controls | AAPL / MSFT / XOM stay at EF ≤ 0 |
| Risks and unknowns | What the backtest can't show |
| Forward-test plan | Account, duration, stop rules, what is measured |
| Sign-off | Name, date, decision |

---

## Candidate 1 — `AOS-P3-REC` (CycleORB v1.13)

| Field | Content |
| --- | --- |
| Candidate | `Presets/AOS/AOS-P3-REC_<asset>.set` for EURUSD-NY, EURUSD-LON0700, DE40, JP225, UK100 and US500. EA v1.13. Prepared 2026-11-06 |
| Changes vs production | **Strategy inputs unchanged.** Added: ledger observer on (`InpAosLedger`, context symbols, event currencies); L3 calendar kill, 0.25R entry-slippage abort, 10 % lot guard, the asset's DD limit (§8: 10 / 11 / 25 / 10 / 13 / 10 %), live clock refusal; L4 health observer (baseline E, leak) with **auto-sizing off**; DE40 only: 2 % risk cap while Compressing or worse. L2 policy (P2) and the learned gate (P4) are not included: both were rejected |
| Evidence | `doc/ai_OS.md` AOS-P3 results; runs `v1.13_*_P3G`, `v1.12_DE30_*_P3T06`; portfolio replay `tools/aos_portfolio.py` (AOS-P6) |
| Health deltas (backtest 2025-07 → 2026-10, 1000 USD) | EURUSD-NY: E +0.263 → +0.270R, AL 0.95 → 0.87, MaxDD 5.4 → 4.7 %, +15.9 USD. JP225: E +0.203 → +0.190R, −15.5 USD (one aborted winner). DE40: MaxDD 13.8 → 11.2 % for −0.9R. LON0700, UK100, US500: identical. Fire retention 100 % on all six |
| Guard exits | EURUSD-NY: 5 slippage aborts (−2.15R → −1.03R on those trades). JP225: 1 (+1.24R → −0.03R). Calendar kill, lot guard and DD halving: 0 triggers on production assets; functional tests passed (AAPL Friday holds, UK100 @ 500, DE40 at a tight limit) |
| Portfolio (six assets, one account, replay) | Ending equity ×5.92 over 16 months, MaxDD 14.2 %, MC-2 P95 DD **23.9 %** (limit 25 %), P(ruin) 0 %. Most risk open at once 5.7 %; worst day −4.6 %. Heat cap and bucket throttle rejected (they lower return / DD). DE40–UK100 daily ρ +0.70 |
| Negative controls | AAPL / MSFT / XOM EF −11.5 / −2.0 / −53.2 pp; unchanged by the guards |
| Risks and unknowns | (1) Everything is in-sample to preset selection; the forward test is the first clean out-of-sample evidence. (2) Slippage-abort effect rests on 6 events. (3) The calendar kill, lot guard and cross-chart behaviour can only be verified live (the tester runs one symbol). (4) Swap and fills on the live account may differ from the tester. (5) DE40 is in Compressing state; LON0700 is `OVER_SIZED` by the pessimistic Kelly rule (`f_max` 0) and Fragile. (6) Skip lists end 2027-12-31. (7) **Watch items:** the JP225 short-after-US-up-day pattern (P2/P4); NVDA / TSLA 15:50 exits on Fridays in US standard time (not part of this set) |
| Forward-test plan (AOS-P7) | Demo account, one chart per asset, the `AOS-P3-REC` presets unchanged. Duration: until each asset has ≥ 40 forward events (about 4–9 months). Monthly: `aos_tape.py collect/check` on the live ledgers, `aos_health.py`, comparison of live slippage and fills with the tester. **Stop rules:** any `CALENDAR_LEAK` → investigate before continuing; live DD ≥ 0.8 × the asset limit → halve risk (automatic); `Below frontier` two month-ends in a row → pause that asset and investigate. **Promote to live (R2)** per asset when: ≥ 40 forward events, forward E > 0 and EF > 0, combined EF > M, MC-3 median ≥ C₀, 0 calendar leaks |
| Sign-off | ☑ **Approved for the demo forward test (AOS-P7)** by the account owner, 2026-11-06. Live AI presets: `Profiles/Tester/ORB/AOS/AOS-P3-REC_<asset>.set` (mirrored in `Experts/CycleORB/Presets/AOS/`). All research and test presets (AOS-P1 / P2 / P3 tasks) moved to the `archive/` subfolders; their tester `.ini` files point there |

---

## Candidate 2 — L2 shadow skip models (INF-P6 phase-prove, 2026-11-08)

| Field | Content |
| --- | --- |
| Candidate | The three INF-P4 L2 families (cell rule, ridge + logistic, shallow GBT) under the pre-registered low bar (`infra/policy_low_bar.json` v1), each trained on (a) the P1obs tape and (b) tape + replica history (INF-P4-T07). Shadow only: no preset, no EA change |
| Changes vs production | None proposed. A pass would only have unlocked an INF-P7 wiring **design** |
| Evidence | `var/scorecards/INF-P6-T01_L2shadow_<family>_<data>.json` (report), `INF-P6-T02_…` (stability), summary `INF-P6-T01_train_phaseProve_L2shadow_W250-W500.json`; `python -m corb prove all`. Out of sample: 2026-02 → 10, 462 asset days, tester rows only |
| Health deltas (pooled, primary baseline) | cell rule: 42 skips (9 %), W250 EF +11.9 → +11.1 pp, withheld **+0.268R**. ridge + logistic: 39 (8 %), +11.9 → +11.2 pp, withheld +0.066R. GBT: 32 (7 %), +11.9 → +12.1 pp, W500 +11.2 → +12.3 pp, withheld −0.031R, `p_rand` 0.10. With replica history: cell rule +0.625R, ridge +0.581R, GBT +0.122R withheld (all worse) |
| Skip precision | Only GBT (tape) skips days with a negative mean (−0.031R); it fails on breadth: US500 loses > 0.05R / event and > 1 pp EF (one skipped +2.0R day), on the primary **and** the secondary (`AOS-P3-REC`) stream |
| Portfolio (AOS-P3-REC streams, one account) | Base: ×5.92, MaxDD 14.2 %, MC-2 P95 DD 23.9 %. GBT (tape): ×6.16, 14.2 %, 22.0 %. ridge: ×5.87, 13.3 %, 23.0 %. cell rule: ×5.34, 14.2 %, 24.2 %. No candidate breaks the portfolio drawdown check; none passes the per-asset bar |
| Stability (T02) | Verdict unchanged on 100 % of 10 perturbations (±1 step of each threshold, two seeds, 5 / 10 day embargo) for five candidates and 90 % for GBT + replica. **One isolated accept:** GBT + replica with `pred_e_max` −0.15 (19 skips, withheld −0.080R, `p_rand` 0.12) while every neighbour withholds +0.04 … +0.46R: a peak, not a plateau (1 accept in 60 runs is what chance produces). Size-only (half size instead of a skip): E_N +0.315 → +0.286 … +0.332 (at most +0.017, from the same GBT / ridge skips that fail the breadth checks) |
| Negative controls | AAPL / MSFT / XOM stay EF ≤ 0 under every candidate |
| Risks and unknowns | 462 out-of-sample asset days over 9 months; replica history lacks context-symbol, live-spread and pre-2025 calendar features |
| Decision proposed | **Shelved: every candidate.** The engine stays ungated and INF-P7 stays locked. Watch item: GBT with `pred_e_max` −0.15 may be pre-registered as policy v2 (it skips fewer days, which §8.2 allows) and judged **only** on forward ledger months, never on this data |
| Sign-off | ☐ Pending: account owner (L8) |
