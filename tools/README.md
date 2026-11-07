# CycleORB tools (AI OS phase P0)

Python 3.10+, standard library only. Run everything from this folder.

| File | Task | Purpose |
| --- | --- | --- |
| `corb_parse.py` | AOS-P0-T02 | Journal adapter: Strategy Tester journal → one folder per run in `../tester/aos/runs/<run_id>/` (`meta.json`, `events.csv`, `decisions.csv`) |
| `corb_metrics.py` | AOS-P0-T02 | Unified Edge Framework metrics with the CycleORB overrides (pure functions) |
| `corb_bench.py` | AOS-P0-T02 / T01 | Scoring engine: health vector, Stage 1 zone, lifecycle, gates, sizing, Monte Carlo |
| `aos_assets.json` | AOS-P0-T01 | Which run is each asset's baseline, and its operating risk `f` |
| `aos_baseline.json` | AOS-P0-T01 | **Frozen baseline** (the numbers every AI OS layer must beat or hold), with provenance and `events.csv` hashes |
| `aos_compare.py` | AOS-P0-T04 | Variant vs baseline by `event_id`: deltas, skip precision, fire retention, accept / reject per `doc/ai_OS.md` §3 |
| `aos_tape.py` | AOS-P1-T07 | `collect` EA ledgers into run folders, `check` P1 exit criteria, `build` the pooled feature tape (`../tester/aos/tape/`) |
| `aos_health.py` | AOS-P3-T07 | Month-end lifecycle replay (W20 / W40 / W80 EF, E, ΔD, state, size) and `edge_framework.md` §6.2 triggers; `--ea` shows the EA's own `health_state` for the following month |
| `aos_gate_wf.py` | AOS-P4 | Pooled learned-gate walk-forward (ridge / shallow GBT, anchored monthly, per-asset in-sample threshold, random-skip benchmark, size mode, controls). Needs numpy, pandas, scikit-learn. 2026-11-06 verdict: shelved |
| `aos_portfolio.py` + `aos_portfolio_streams.json` | AOS-P6-T05 | Portfolio replay of the per-asset streams on one account (heat cap, Europe-open bucket throttle, MC-2, daily correlations). Re-run when an asset or a risk input changes |
| `tests/` | — | Generic fixtures FX-01…16, CycleORB fixtures CO-FX-01…04, compare behaviour |

## Infra (`doc/infrascaleup.md`)

`corb/` is the infra package. Run it from this folder with `python -m corb <command>` (P0–P2 commands are stdlib only).

| Command | Task | Output |
| --- | --- | --- |
| `python -m corb inventory` | INF-P0-T02 | `../infra/inventory.json`: every evidence file with sha256, run records, duplicate groups |
| `python -m corb baseline lock` | INF-P0-T03 | `../infra/baseline_lock.json`: verified against `aos_baseline.json`, with the pooled vector, frequency lines and the `AOS-P3-REC` secondary baseline. Not written if any check fails |
| `python -m corb baseline check` | INF-P0-T03 | Recomputes everything and diffs it against the committed lock (no write) |
| `python -m corb sources check` | INF-P0-T04 | Checks `../infra/sources.json` and measures broker history depth from the terminal's `bases/` cache |
| `python -m corb contract build` | INF-P1-T01 | Adapts + validates every run folder against `../infra/contract/datapackage.json` → `../var/contract/*.csv` |
| `python -m corb land runs` / `land verify` | INF-P1-T05 | Write-once landing by sha256 in `../var/landing/` / re-hash every landed file |
| `python -m corb db up` / `db migrate` | INF-P1-T02 | Start Postgres (Docker, port 127.0.0.1:5433) / apply `../infra/db/migrations` with dbmate |
| `python -m corb db migrate-check` | INF-P1-T02 | up / down / up on a scratch DB, compared with `../infra/db/schema.sql` |
| `python -m corb db load` / `db check [--reload]` | INF-P1-T04 | Full reload of the core tables / R rebuilt from legs, row counts, CO-FX in SQL, landing coverage, fingerprint |

| `python -m corb ingest` | INF-P2-T01 / T07 | Land everything new (run folders, journals, Common + VPS ledgers), load only new or changed runs; VPS live ledgers become monthly `kind=live` runs (`../infra/live.json`) |
| `python -m corb dq` | INF-P2-T03 / T06 | Ledger vs journal reconciliation + quality checks → `ops.dq_result`; cost sources and Leak vs the frozen baseline |
| `python -m corb replay <journal> --version X` | INF-P2-T05 | Re-parse a raw journal into `../var/replay/`; baselines must be byte- and number-identical |
| `python -m corb import ouroboros` | INF-P2-T08 | Land the frozen Ouroboros slices (refused if a hash moved since `sources check --freeze`) |

| `python -m corb tester exp` / `tester build` | INF-P2-T04 | EXP presets + inis / build the Wine + MT5 image `cycleorb-tester:<mt5 build>` |
| `python -m corb tester run [inis] --parallel N` / `tester parity` | INF-P2-T04 | Tester containers (login from `../infra/.env`) / container runs vs the committed native runs (balance, events bytes) |

| `python -m corb bars prepare` / `bars export` / `bars lake` | INF-P3-T02 | M1 bars from a headless export instance (`../var/mt5_export`, never the user's terminal) → `../var/lake/bars/` parquet |
| `python -m corb features registry` / `audit` / `build` | INF-P3-T01 / T04 / T03 | Feature registry (`../infra/features.json`), PIT audit + future-shift test, offline builder vs EA ledger parity |
| `python -m corb features tape` / `features cells` | INF-P3-T05 / T06 | Regime tape and decision-time cells into `features.*` |
| `python -m corb train regression` / `train folds` | INF-P4-T01 / T02 | Harness reproduces the AOS-P2…P4 verdicts / anchored monthly folds with the decay guard |
| `python -m corb train run --family F` | INF-P4-T03…T06 | Walk-forward evaluation against `../infra/policy_low_bar.json` → registry, shadow decisions, scorecard |

| `python -m corb ops journals` / `ops why <event_id>` | INF-P5-T01 | Landed journals → `raw.journal_line` / every journal line for one setup-day, in time order |
| `python -m corb ops metrics` / `ops reasons` | INF-P5-T02 / T03 | §6.2 trigger metrics → `ops.metric` (ok / warn / alarm) / reason-code catalogue → `ops.reason_code` |
| `python -m corb ops roles` | INF-P5-T06 | DB roles `ingest_rw`, `train_rw`, `agent_ro` (passwords generated into `../infra/.env`), permission tests, secret scan of git history |
| `python -m corb ops grafana` / `ops grafana-down` | INF-P5-T02 | Grafana 13 at `http://127.0.0.1:3000` (user `admin`, password `CORB_GRAFANA_ADMIN_PASSWORD` in `../infra/.env`), board "CycleORB infra" read through `agent_ro`; verifies every panel |
| `python -m corb jobs enqueue <corb command>` / `jobs work [--once]` | INF-P5-T05 | Postgres job queue `ops.job` (SKIP LOCKED); logs in `../var/log/jobs/<id>.log` |
| `python -m corb test lint` / `test golden [--update]` | INF-P5-T07 | Preset lint (inputs exactly the EA's, strings < 250 chars, skip dates ≥ 90 days ahead on live / EXP presets) / health-vector hash vs `../infra/golden/health_vectors.json` |
| `python -m corb test image` / `test replay` / `test all` | INF-P5-T04 / T07 | Pinned job image `cycleorb-jobs` / host vs container on the same commands / unit tests + migrations + lint + golden + replay |

`bars`, `features`, `train` and `test` need numpy, pandas, scikit-learn and pyarrow; the pinned set is `../infra/docker/jobs/requirements.lock` (the job image runs any command: `docker run --rm --network cycleorb_default -e CORB_DB_HOST=db -v <repo>:/repo -v <repo>/var:/corb/var cycleorb-jobs <command>`).

**Logs:** every command writes JSON lines to `../var/log/<command>/<date>.jsonl` (start, end, exit code, seconds; scorecards add `recipe`, `verdict`, `eval_id`, `model_semver`).

**Ledger collection:** a tag's `Common\Files` ledger holds only the last tester run with that tag. Never reuse a run tag across EA versions; `aos_tape collect` copies a reused tag into the newest version's folder only. `../infra/quarantine.json` lists the misfiled copies removed on 2026-11-07.

**Database:** Postgres runs in Docker as `cycleorb-db-1` (data volume `cycleorb_corb_pg`). Connect with any client at `127.0.0.1:5433`, database / user `corb`, password `CORB_DB_PASSWORD` from `../infra/.env`; read-only clients use `agent_ro`. Changing the contract means a new migration: regenerate with `python -m corb contract ddl` (the test suite fails if `002_core.sql` and the contract diverge).

**Agent read paths:** `../var/scorecards/latest.json` (the last verdict), `../var/scorecards/index.json` (every recipe → file), and `../infra/*.json`. `var/` is gitignored and regenerated by the commands.

**External roots** (optional overrides): `CORB_TERMINAL_DIR` (default: three levels above the repo), `CORB_COMMON_DIR` (default `%APPDATA%\MetaQuotes\Terminal\Common\Files`), `CORB_OUROBOROS_DIR` (default: `ouroboros.root` in `infra/sources.json`). `python -m corb sources check --freeze` re-records the Ouroboros slice hashes; do it only on purpose. Committed files store paths as `%REPO%`, `%TERMINAL%`, `%COMMON%` and `%OUROBOROS%`.

## EA ledger (AI OS P1, CycleORB ≥ v1.10)

- With `InpAosLedger=true` the EA writes `%APPDATA%\MetaQuotes\Terminal\Common\Files\CycleORB\CORB_<magicBase>_<symbol>_<tag>_{decisions,events,shadow}.csv`. In the tester, `tag` = `tester_<deposit>[_<InpAosRunTag>]`; live, `live`.
- `InpAosRunTag` is appended to the parser's `run_id`, so a tagged run gets its own folder next to its baseline.
- The event calendar is `Common\Files\CycleORB\events.csv`. Refresh it with the script `Scripts\CycleORB\CycleORB_ExportCalendar` (headless: `terminal64.exe /config:"<CycleORB>\tester\aos\export_calendar.ini"` with the terminal closed).

```powershell
python corb_parse.py "..\..\..\..\Tester\logs\20261106.log" --version 1.10
python aos_tape.py collect --tag P1obs
python aos_tape.py check   --tag P1obs
python aos_tape.py build   --tag P1obs
```

## Workflow

```powershell
# 1. Parse a tester journal (the terminal writes Tester\logs\YYYYMMDD.log; filter by version and symbol if needed)
python corb_parse.py "..\..\..\..\Tester\logs\20261106.log" --version 1.09

# 2. Score one run, or every asset in the spec
python corb_bench.py ..\tester\aos\runs\<run_id> --f 0.01
python corb_bench.py --assets aos_assets.json

# 3. Re-freeze the baseline (only when a baseline run changes, e.g. AOS-P0-T03)
python corb_bench.py --assets aos_assets.json --out aos_baseline.json --freeze

# 4. Judge an AI OS variant against its baseline (same symbol, window and deposit)
python aos_compare.py --pair ..\tester\aos\runs\<base> ..\tester\aos\runs\<variant> [--pair ...] [--control <base> <variant>]

# 5. Tests
python -m unittest discover -s tests -v
```

## Definitions

- **`event_id`** = `<magic>-<YYYYMMDD>` of the setup day (one setup-day = one event, `edge_framework.md` §2.2).
- **`pnl_R`** = signed (exit fill − entry fill) / |planned entry − initial stop|. Fills are bid/ask, so spread is included.
- **`c_spread_R` / `c_slip_R`**: spread in R (already inside `pnl_R`) and the slippage prior (0.5 × spread per market leg) that becomes `Leak`.
- **`pnl_ccy_est`**: account-currency P&L reconstructed from price × lots × one conversion factor per run, solved against the final balance (`meta.json: usd_per_price_lot`).
- **Skip precision**: withheld events (in the baseline, not in the variant) must have mean R < 0 and BM ≤ 0. Resized-down events must have mean R below the baseline E.

## Limits

- Comparisons are only valid between runs with the same symbol, window and deposit. A different deposit changes lots and lot-minimum skips (`CO-FX-03`).
- The journal adapter relies on the EA's log lines (`RANGE`, `SKIP`, `PLACE`, deal lines). Changing those messages in the EA requires updating `corb_parse.py`. The native ledger (AOS-P1-T01) will replace it.
- Monte Carlo values carry about ±0.5 pp of seed noise.
