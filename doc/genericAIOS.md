AI OS

Read `edge_framework.md` , `system design.md` (the
profitable execution engine we already have), and `Edge Discovery.md` (what we
already isolated). Do not reopen edge discovery as the main workstream.

GOAL
Design and phase an **AI OS** that wraps the existing execution engine. The OS
does not replace the engine and does not chase raw profit. It supercharges the
engine through stacked AI layers that decide:

1. WHEN the engine is allowed to enter (regime / structure gates — skip or fire)
2. WHEN the edge is compressing or gone (health observer → de-risk / halt)
3. HOW to avoid the engine's known bad-trade / bad-regime cells
4. HOW to retrain / adapt over time so the edge stays alive without overfitting
   the decay window

Working hypothesis (confirm or reject from system design + Edge Discovery): the
engine already has a real edge; the remaining leak is **conditional** — it fires
in regimes and structures where BM_cell ≤ 0. The AI layers' job is to withhold
those fires, contain AL and MaxDD, and keep EF alive as price evolves.

THIS IS NOT EDGE DISCOVERY
- Do not produce another EDX scorecard as the deliverable.
- Do not re-optimise SL/TP/filters as the first move (runbook order still holds:
  data → execution → regime → structure).
- Frozen objective still applies: maximise E_N subject to EF > 0 and MaxDD
  acceptable. Never maximise WR, PF, or BM alone (90% WR / 0.15 payoff is still
  a fail). WR and PF are **diagnostics**, not OS objectives.
- Iteration bar is LOWER than production sign-off. We already have a profitable
  engine. AI-layer experiments are accepted if they do not collapse frequency or
  DD and they improve (or hold) EF vs the EDX baseline. Full G0–G5 is only for
  promoting an OS version to live — not for every layer experiment.

DELIVERABLE
Create `ai_OS.md` with phases and task IDs (`AOS-P#-T##`) so we execute one
task at a time. Go WILD AND BIG on the layer stack (many layers, ambitious
scope, rich regime/structure vocabulary). Keep scores, thresholds, and
pass/fail bars **loose for iteration**. Every task states: which layer it
belongs to, what it changes, which health-vector fields it should move,
expected skip/fire behaviour, and its test preset.

Speak two vocabularies without mixing them:
- Framework **stages** (0–4) = how we score the EA.
- AI OS **layers** (L1–Ln) = software we build around the engine.

────────────────────────────────────────
OS ARCHITECTURE — LAYERS TO PROPOSE

Propose a full stacked OS. At minimum these layers, and add more if justified.
Higher layers may advise; they must never override L3 Guardrails.

L1  PERCEPTION LAYER
    AI regime detection (vol tercile, trend vs range, plus richer: session
    microstructure, liquidity, news/event windows, session overlaps).
    Structure decoder (HH/HL vs LH/LL, range, breakout, failed auction —
    aligned with what system design.md already uses).
    Output: a live regime/structure tape every other layer consumes.

L2  INTELLIGENCE / POLICY LAYER
    Skip / enter gate on top of the engine's existing signal.
    Optional size modulator mapped to lifecycle states
    (Expanding / Stable / Compressing / Near frontier / Below frontier).
    Never invent a new entry model; only permit or withhold the engine.

L3  GUARDRAIL LAYER (hard, non-AI, cannot be overridden by L1/L2/L4)
    MaxDD / 0.8×DD_limit de-risk, FREQUENCY_STALL, cost-drift halt,
    Below-frontier f = 0, kill-switch. Guardrails beat intelligence.

L4  EDGE-HEALTH OBSERVER LAYER
    Rolling W100 (fast) / W250 (decision) / W500 (confirm) health vector,
    EF, ΔD, Leak, RR−R gap. This is how the OS "knows when the edge exits."
    Observer recommends; L3 commands.

L5  ADAPTATION / RETRAIN LAYER
    Scheduled and trigger-based retrain of L1/L2 models.
    Walk-forward style: fit on data through the decay, never only on the
    decay window (framework rediscovery rule). Version the model; no
    silent overwrite of a live gate.

L6  MEMORY / LEDGER LAYER
    Every skip, fire, size-change, and retrain logged with features +
    reason codes so humans can audit "why did it skip?"

L7+ (go bigger) extra layers that keep the edge alive: correlation /
    basket throttle, session-quality scorer, MAE/MFE early-abort advisor,
    multi-horizon regime ensemble, human-in-the-loop promotion queue.

────────────────────────────────────────
PHASES (build the layers, don't rediscover the edge)

AOS-P0  ENGINE BASELINE LOCK
    Import the current EDX / engine baseline health vector. This is the
    number the OS must beat or hold. No code yet.

AOS-P1  L1 PERCEPTION
    Define feature schema, labels, and how a live bar is tagged.
    Output: regime/structure tape L2 will consume.

AOS-P2  L2 POLICY GATES (skip / enter / size)
    Map Edge Discovery bad cells → skip rules first (deterministic), then
    AI classifiers on top. Size modulator only after skip-gate exists.
    Hypothesis: skip cells with BM_cell ≤ 0; do not skip merely "weaker"
    cells if they still have EF > 0.

AOS-P3  L3 GUARDRAILS + L4 HEALTH OBSERVER
    Wire hard limits and the rolling EF/ΔD observer to the engine's
    permission to trade.

AOS-P4  AVOIDANCE TRAINING (L2 on labelled engine trades)
    Train the gate on win/loss, MAE/MFE, regime, session, structure.
    Objective: reduce AL and MaxDD by skipping predicted-losers, without
    FREQUENCY_STALL (< 50% of baseline fires).

AOS-P5  L5 RETRAIN LOOP
    Cadence (e.g. monthly + on Compressing/Near-frontier triggers).
    Champion/challenger: new model only replaces live if W250 EF ≥
    baseline EF and MaxDD not worse. Loose bar: no G2–G5 required to
    *try*; G2–G5 required to *promote*.

AOS-P6  FULL STACK INTEGRATION + PRESETS
    End-to-end: L1 → L2 → engine → L4 → L5, with L3 always on and L6
    logging. Named presets for each layer combo so I can load and test.

AOS-P7  LIVE PROMOTION (only phase that uses full framework gates)
    One OS candidate vs engine-only baseline. Then G1 (EF > 0 is enough
    to keep iterating; EF > M to promote), G3 regime check, light G4
    (block bootstrap on skip-adjusted blotter), G5 cost stress. Do not
    set production-sign-off n=1068 as a blocker for experiments.

────────────────────────────────────────
ITERATION BAR (loose on purpose)

Accept a layer experiment when ALL of:
- n remaining after skips is still Provisional or better (n ≥ 100). Warn
  if n < 385; do not kill the experiment.
- W250 EF ≥ baseline EF − 1pp  (hold is a pass; small noise allowed)
- W250 MaxDD ≤ baseline MaxDD + 2pp
- 90-day fire count ≥ 50% of engine baseline (FREQUENCY_STALL warning,
  not instant fail — report it)
- AL not worse unless E_N clearly improved

Reject immediately when:
- WR up but E_N or EF down (payoff trap)
- Engine is skipped into a different strategy (layers must not rewrite
  entries, only permit/withhold)
- L3 would have halted and a higher layer overrode it

Promote to live only when Stage 1 is at least Fragile-or-better with EF
trending Stable/Expanding on W250, and MaxDD inside the mandate. Robust
(EF > M) is the promotion target, not the experiment entry ticket.

TEST PRESETS
For every task create a preset named with full context:
  AOS-P{phase}-T{task}_{layer}_{change}_{context}
  e.g. AOS-P2-T04_L2gate_skipRangeHighVol_LON-NY.set
Each preset lists: changed inputs only, hypothesis, skip/fire expected
rate, health-vector fields that must not regress vs AOS-P0.

RULES OF ENGAGEMENT
- One task at a time; each ends with a preset and a loose accept/reject.
- Review system design.md and Edge Discovery.md first; the layers must
  consume their bad-regime / bad-session / bad-structure findings rather
  than rediscovering them.
- L3 Guardrails outrank every intelligence layer.
- Retrain is versioned; champion/challenger; never fit only on the
  period that killed the previous edge.
- Speak framework: WR, R, BWR, BM, Leak, EF, M, E_N, ΔD, MaxDD, f —
  not "AI confidence" as a substitute for those numbers.




