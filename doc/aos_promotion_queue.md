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
