Read `edge_framework.md` (v1.0 — metric dictionary, stages, gates, runbook,
adapter contract), `system design.md` (current execution engine + known limits),
`Edge Discovery.md` (isolated edge / bad cells), and `ai_OS.md` if it exists
(target layer stack L1–L6+). Do not reopen edge discovery. Do not wire AI into
live execution in this workstream.

GOAL
Produce `infrascaleup.md`: a phased infra + pipeline scale-up so we can train
and prove AI OS layers **offline**, then retrain, and only later wire them onto
the already-profitable engine.

This add-on is used once the EA is stable with the right pipeline/infra and
executions. There is **no forward testing for now**. Sequence is mandatory:

  1) build pipelines and infra
  2) train offline
  3) prove improvement per phase against the engine baseline
  4) only then discuss wiring
  5) retrain models on the new stack after wiring is justified

The engine already has its edge. Infra and AI exist to **protect it under
different conditions**, not to overfilter it into a different strategy.

────────────────────────────────────────
PROTECT, DON'T OVERFILTER (low gate bar)

AI / infra gates must be conservative on skipping, aggressive on logging.
Thresholds and scores stay LOW so we do not starve a working engine.

- Skip only when the layer is reasonably sure the cell is hostile
  (Edge Discovery BM_cell ≤ 0, or predicted-loser with modest confidence).
  When unsure: FIRE the engine and log. Default is allow.
- Do not raise skip-confidence, WR targets, or filter counts to "look more
  selective." Overfiltering is a first-class failure mode.
- Frozen objective: hold or lift E_N / EF; contain AL and MaxDD. WR and PF
  are diagnostics. WR up + E_N down = reject (payoff trap).
- Frequency: warn at < 70% of engine baseline fires; hard-concern at
  FREQUENCY_STALL (< 50%). Prefer under-skipping during infra phases.
- Iteration accept (offline, vs AOS-P0 / engine baseline):
    n remaining ≥ 100 (warn if < 385, do not kill)
    W250 EF ≥ baseline EF − 1pp
    W250 MaxDD ≤ baseline MaxDD + 2pp
    skip-rate modest; justify every skip cluster
- Full G0–G5 is NOT required to accept an infra/training phase. Promotion /
  wiring is a later phase with its own (still not discovery-strict) bar.

Speak two vocabularies:
- Framework **stages** (0–4) = how we score.
- AI OS **layers** (L1–Ln) = what will eventually sit on the engine.
- Infra **planes** below = what we build now so those layers can train offline.

────────────────────────────────────────
DELIVERABLE

Create `infrascaleup.md` with phases and task IDs (`INF-P#-T##`) so we execute
one task at a time. Go WILD AND BIG on infra (industry-standard, compensate
tester/EA limitations). Keep AI skip thresholds LOW.

Every task states: plane it belongs to, limitation it compensates, artefact
produced, how we know the phase improved things (offline metric / health-vector
delta — never "feels better"), and a **replay/eval recipe** (not a live preset).
No live .set wiring tasks until INF-P6+.

Also include: current-stack limitation map, target architecture, schema, what
the tester cannot do (so the dedicated box must), and how Cursor/the agent
gets easier access (paths, APIs, logs, fixtures).

────────────────────────────────────────
WHAT TO IMPROVE (industry baseline — propose a concrete stack)

Review the current stack from system design.md and propose upgrades. At
minimum cover, and add more if justified:

P-DATA   Pipeline / blotter
         Framework adapter contract as the source of truth (event_id, legs,
         costs, declared 1R, equity_at_open). Ingest from tester/EA exports
         → clean parquet/CSV landing → Postgres system of record.
         Compensate: tester history limits, fragmented logs, no event grouping.

P-STORE  Postgres + schema
         Named schemas, e.g. raw / core / features / train / score / ops.
         Tables for blotter, event manifest, EA metadata, regime tape,
         gate decisions, health vectors, model versions, eval runs.
         Migrations, not ad-hoc SQL. Deterministic event_id.

P-FEAT   Feature / label store (offline)
         L1 perception features and labels joined to trade events.
         Point-in-time correct: no leakage from future bars into training.

P-TRAIN  Offline training + eval harness
         Train L1/L2 on historical engine trades. Champion/challenger.
         Walk-forward folds (framework G2 style as a *harness*, not a
         promotion gate). Fit through decay, never only on the decay window.
         Report skip-rate, EF/E_N/MaxDD vs baseline per fold.

P-OBS    Logging / observability
         Structured JSON logs, correlation ids (event_id, run_id, model_semver).
         Reason codes for would-be skips even while gates are not wired.
         Metrics: fire/skip, lag, feature nulls, cost drift, FREQUENCY_STALL.
         Agent-readable log dirs + a single "latest eval" JSON scorecard.

P-PACK   Docker
         Images for: ingest, feature builder, trainer, scorer, postgres,
         eval runner. Compose for local; same images on the dedicated server.
         Pin versions. One command to replay a phase.

P-BOX    Dedicated server
         Tester stays on the trading box; heavy work (features, train, MC,
         walk-forward) moves to the dedicated server. Define CPU/RAM/disk,
         job queue, artefact store (models, reports, fixtures).

P-TEST   Infra testing (not forward testing)
         Contract tests on schema and adapter blotter.
         Golden FX fixtures from unified_edge_framework.md (FX-01…FX-16)
         for the scoring engine.
         Replay tests: freeze a blotter slice, expect stable health vector.
         Docker smoke, migration dry-run, permission checks.
         No live FT, no demo-account "see if it works."

P-ACCESS Agent / human access
         Repo layout, env files (no secrets in git), documented paths,
         `make ingest|features|train|score|report`, scorecards the agent
         can Read without clicking through tester UI.

Compensate named tester/EA limitations explicitly (single-thread, no
good blotter, no PIT features, no model registry, logs as print statements,
can't run MC/walk-forward, etc.) — each INF task should map to one of those.

────────────────────────────────────────
PHASES (offline-first; wiring is last)

INF-P0  LIMITATION MAP + BASELINE LOCK
        Catalogue current infra/tester limits. Lock engine health vector
        (from EDX / system design). Success criteria for later phases.
        No Docker, no training yet.

INF-P1  CONTRACT + SCHEMA
        Adapter blotter / manifest / metadata → Postgres schema + migrations.
        Landing zone for tester exports. Prove we can rebuild events and 1R.

INF-P2  INGEST PIPELINE
        Automated export → validate → load. Idempotent. Cost components
        defaulted vs measured flagged. Replay one historical dump end-to-end.

INF-P3  FEATURE / REGIME TAPE (offline L1)
        Build perception features PIT-correct. Join to events. Do not skip
        live trades. Dump a regime tape the trainer can consume.

INF-P4  OFFLINE TRAIN + EVAL HARNESS (L2 as a shadow, not wired)
        Train skip/enter models. Run them in **shadow**: log would-skip vs
        would-fire on historical events. Score counterfactual blotter
        (remove would-skips) vs baseline with the LOW skip bar.
        Accept only if protect-don't-overfilter iteration bar holds.
        Models versioned; never overwrite.

INF-P5  OBSERVABILITY + DOCKER + DEDICATED BOX
        Structured logs, compose stack, move heavy jobs off the tester.
        Infra tests (schema, fixtures, replay, smoke). Agent access paths.

INF-P6  PHASE-PROVE GATE (still offline)
        Per-layer / per-phase report: baseline vs shadow OS on W250/W500.
        Only if EF held/lifted and skip-rate not starving the engine do we
        even write a wiring plan. No live preset until this gate passes.

INF-P7  WIRING PLAN (design only unless explicitly authorised)
        How L2/L3 attach to the stable EA, champion/challenger, rollback,
        retrain cadence. Still not forward testing unless I say so.

INF-P8  RETRAIN LOOP ON THE NEW STACK
        After (and only after) infra is stable and a wiring plan exists:
        scheduled + trigger retrain (Compressing / Near frontier), PIT,
        versioned artefacts, shadow eval before any live model swap.

────────────────────────────────────────
REPLAY / EVAL RECIPES (replace live presets for now)

No live .set wiring in INF-P0–P6. Each task ends with a recipe:
  INF-P{phase}-T{task}_{plane}_{change}
  e.g. INF-P4-T02_train_L2shadow_skipRangeHighVol_2018-2024
Inputs, command(s), expected artefacts (scorecard JSON, skip ledger),
and the loose accept/reject vs engine baseline.

If a tester preset is needed for *exporting* a blotter slice, name it
EXP- not AOS-, and it must not change EA logic.

RULES OF ENGAGEMENT
- One task at a time.
- Offline > shadow > wire. Never skip the prove-per-phase gate.
- Default allow; skip is earned. When unsure, fire and log.
- L3-style hard limits may exist in the eval harness as *simulations*;
  they still outrank intelligence; they are not live until wiring.
- Intelligence never rewrites entries; it only permits or withholds
  (and for now, only in shadow).
- Speak framework numbers on every eval: WR, R, BWR, BM, Leak, EF, M,
  E_N, ΔD, MaxDD, skip-rate, fire-count vs baseline — not "AI confidence."
- Review system design limitations first; every proposed tool (Postgres,
  Docker, dedicated server, schema) must name the limitation it removes.
