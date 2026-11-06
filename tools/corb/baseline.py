"""INF-P0-T03: baseline lock (doc/infrascaleup.md §3).

Recomputes every asset from its run folder with the AOS-P0 scoring engine, verifies it against the frozen
tools/aos_baseline.json (CO-FX tolerances) and the figures quoted in infrascaleup.md §3, and adds what the infra
phases need: pooled vector (full / W250 / W500), fire and armed-day frequencies with their warn / stall lines,
and the secondary AOS-P3-REC baseline (per asset + portfolio replay).
"""
import hashlib
import json
import os
from datetime import datetime

import aos_portfolio as portfolio
import corb_metrics as cm
from aos_compare import _equity_dd_pct, _health
from corb_bench import load_run, score

from corb.paths import INFRA, TOOLS, git_info

ASSETS_SPEC = os.path.join(TOOLS, "aos_assets.json")
FROZEN = os.path.join(TOOLS, "aos_baseline.json")
STREAMS = os.path.join(TOOLS, "aos_portfolio_streams.json")
LOCK = os.path.join(INFRA, "baseline_lock.json")
RECIPE = "INF-P0-T03_train_baselineLock_2025-07_2026-10"

FRAC, PP = 0.005, 0.001   # CO-FX tolerances: fractions / R values, margins (0.1 pp)
FROZEN_FIELDS = [("n", 0), ("WR", FRAC), ("AW", FRAC), ("AL", FRAC), ("R", FRAC), ("BWR", FRAC), ("E", FRAC),
                 ("E_N", FRAC), ("PF", FRAC), ("worst", FRAC), ("maxdd_R", FRAC), ("events_per_90d", FRAC),
                 ("BM", PP), ("Leak", PP), ("EF", PP), ("M", PP), ("BM_worst", PP), ("f_max", PP)]
FIRE_WARN, FIRE_STALL = 0.70, 0.50

# Figures quoted in infrascaleup.md §3 (rounded there: E to 0.001R, percentages to 0.1 pp)
DOC_PRIMARY_MAXDD = {"EURUSD-NY": 5.4, "EURUSD-LON0700": 5.7, "DE40": 13.8, "JP225": 3.9, "UK100": 5.2, "US500": 4.9}
DOC_SECONDARY = {("EURUSD-NY", "E"): 0.270, ("EURUSD-NY", "maxdd_pct"): 4.7, ("JP225", "E"): 0.190,
                 ("DE40", "maxdd_pct"): 11.2}
DOC_PORTFOLIO = {"maxdd": 14.2, "mc2_p95dd": 23.9}
DOC_TOL_R, DOC_TOL_PCT = 0.0006, 0.051


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _round(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def vector(events):
    """Pooled health vector over events from several assets (same formulas as corb_bench.score)."""
    rs = [e["pnl_R"] for e in events]
    c = cm.core(rs)
    lk = cm.leak(sum(e["c_slip_R"] for e in events) / len(rs), c["R"])
    ef, m = c["BM"] - lk, cm.wilson_half(c["WR"], c["n"])
    return dict(n=c["n"], WR=c["WR"], R=c["R"], AL=c["AL"], BM=c["BM"], E=c["E"], E_N=c["E_N"], PF=c["PF"],
                Leak=lk, EF=ef, M=m, zone="Robust" if ef > m else ("Fragile" if ef > 0 else "Negative"),
                worst=min(rs), maxdd_R=cm.max_drawdown_r(rs))


def check(name, expected, got, tol):
    ok = expected == got if isinstance(expected, str) or expected is None or got is None \
        else abs(expected - got) <= tol + 1e-12
    return dict(name=name, expected=expected, got=got, tol=tol, ok=ok)


def build():
    with open(ASSETS_SPEC, encoding="utf-8") as f:
        spec = json.load(f)
    with open(FROZEN, encoding="utf-8") as f:
        frozen = json.load(f)
    with open(STREAMS, encoding="utf-8") as f:
        streams = json.load(f)
    runs_root = os.path.normpath(os.path.join(TOOLS, spec["runs_root"]))
    checks, primary, pooled_events, events_sha = [], {}, [], {}

    for key, asset in spec["assets"].items():
        run_dir = os.path.join(runs_root, asset["run_id"])
        meta, events = load_run(run_dir)
        s = score(meta, events, asset["f_op"])
        events_sha[asset["run_id"]] = _sha(os.path.join(run_dir, "events.csv"))
        checks.append(check(f"{key}.events_sha256", frozen["provenance"]["events_sha256"][asset["run_id"]],
                            events_sha[asset["run_id"]], 0))
        fz = frozen["assets"][key]
        checks += [check(f"{key}.{k}", fz[k], s[k], tol) for k, tol in FROZEN_FIELDS]
        checks.append(check(f"{key}.zone", fz["zone"], s["zone"], 0))
        checks.append(check(f"{key}.lifecycle", fz["lifecycle"]["state"], s["lifecycle"]["state"], 0))
        fires = s["events_per_90d"]
        armed = meta["armed_days"] * fires / s["n"]
        win = s["lifecycle"]["windows"]
        row = dict(run_id=asset["run_id"], preset=asset["preset"], role=asset.get("role", "asset"),
                   version=meta["version"], window=meta["window"], deposit=meta["deposit"], f_op=asset["f_op"],
                   **{k: s[k] for k in ("n", "WR", "AW", "AL", "R", "BWR", "BM", "E", "E_N", "PF", "Leak", "EF", "M",
                                        "zone", "worst", "maxdd_R", "BM_worst", "f_max")},
                   maxdd_pct=_equity_dd_pct(events, meta["deposit"]), mc2_p95dd=s["mc2"]["p95dd"],
                   lifecycle=s["lifecycle"]["state"],
                   W40=win.get(40), W80=win.get(80),
                   fires_90d=fires, armed_90d=armed, fires_warn_90d=FIRE_WARN * fires,
                   fires_stall_90d=FIRE_STALL * fires, armed_stall_90d=FIRE_STALL * armed)
        primary[key] = row
        if row["role"] == "asset":
            pooled_events += events
            if key in DOC_PRIMARY_MAXDD:
                checks.append(check(f"doc.{key}.maxdd_pct", DOC_PRIMARY_MAXDD[key], row["maxdd_pct"], DOC_TOL_PCT))

    pooled_events.sort(key=lambda e: e["exit_time"])
    pooled = dict(full=vector(pooled_events), W250=vector(pooled_events[-250:]), W500=vector(pooled_events[-500:]))

    s_root = os.path.normpath(os.path.join(TOOLS, streams["runs_root"]))
    secondary, rows = {}, []
    for key, st in streams["streams"].items():
        run_dir = os.path.join(s_root, st["run_id"])
        meta, events = load_run(run_dir)
        h = _health(events, meta["deposit"])
        secondary[key] = dict(run_id=st["run_id"], **{k: h[k] for k in ("n", "E", "E_N", "AL", "EF", "worst",
                                                                         "maxdd_R", "maxdd_pct")},
                              dE_vs_primary=h["E"] - primary[key]["E"],
                              dMaxDD_pct_vs_primary=h["maxdd_pct"] - primary[key]["maxdd_pct"])
        events_sha[st["run_id"]] = _sha(os.path.join(run_dir, "events.csv"))
        rows += portfolio.load_stream(key, run_dir, st.get("bucket", ""))
    for (key, field), expected in DOC_SECONDARY.items():
        checks.append(check(f"doc.secondary.{key}.{field}", expected, secondary[key][field],
                            DOC_TOL_R if field == "E" else DOC_TOL_PCT))
    arms = sorted(r["arm"] for r in rows)
    months = (arms[-1] - arms[0]).days / 30.44
    _, rets, _, _ = portfolio.replay(rows)
    pf = portfolio.stats(rets, "AOS-P3-REC, no portfolio rule", months)
    for k, expected in DOC_PORTFOLIO.items():
        checks.append(check(f"doc.portfolio.{k}", expected, 100 * pf[k], DOC_TOL_PCT))

    lock = dict(
        task="INF-P0-T03", recipe=RECIPE, generated_at=datetime.now().isoformat(timespec="seconds"),
        provenance=dict(
            git=git_info(),
            framework="unified_edge_framework.md v1.0 + edge_framework.md v1.0 (CycleORB overrides)",
            primary="engine only: CycleORB v1.11 production presets (tools/aos_baseline.json)",
            secondary="AOS-P3-REC guard set, v1.12 / v1.13 runs (tools/aos_portfolio_streams.json)",
            inputs_sha256={os.path.basename(p): _sha(p) for p in (ASSETS_SPEC, FROZEN, STREAMS)},
            events_sha256=events_sha, seeds=dict(bench=20261105, portfolio=20261106)),
        bar=dict(EF_slack_pp=1.0, MaxDD_slack_pp=2.0, fire_warn=FIRE_WARN, fire_stall=FIRE_STALL,
                 pooled_n_min=100, pooled_n_warn=385, controls="EF <= 0"),
        primary=primary, pooled=pooled,
        secondary=dict(assets=secondary, portfolio=dict(trades=pf["trades"], terminal=pf["terminal"],
                                                        maxdd=pf["maxdd"], mc2_p95dd=pf["mc2_p95dd"],
                                                        mc2_med_term=pf["mc2_med_term"], ruin=pf["ruin"])))
    return _round(lock), checks


def _numbers(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _numbers(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(d, (int, float, str)) or d is None:
        yield prefix, d


def diff_against_lock(lock):
    """Exact comparison of the recomputed numbers with the committed lock (provenance excluded)."""
    with open(LOCK, encoding="utf-8") as f:
        old = json.load(f)
    keys = ("primary", "pooled", "secondary")
    a = dict(_numbers({k: old[k] for k in keys}))
    b = dict(_numbers({k: lock[k] for k in keys}))
    return [check(k, a.get(k), b.get(k), 1e-9) for k in sorted(set(a) | set(b))]
