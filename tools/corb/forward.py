"""INF-P7-T04: forward telemetry for the demo forward test (AOS-P7). Read-only: nothing here touches the EA, a preset
or the VPS terminal.

pull()     one-way copy of the VPS live ledgers from the synced folder in infra/live.json "pull_from" (the VPS side
           is infra/vps/push_ledgers.ps1) into the ingest inbox; `corb ingest` then splits them into kind=live runs
report()   per deployment: the forward health vector vs the AOS-P3-REC baseline, the R2 promotion check and the stop
           rules of doc/aos_promotion_queue.md Candidate 1, live vs tester costs
shadow()   the registered (shelved) L2 models scored on forward armed days: would-skip, reason code, and the
           cumulative forward skip precision; nothing is acted on
"""
import csv
import glob
import hashlib
import json
import os
import pickle
import shutil
from datetime import datetime

import numpy as np
import pandas as pd

import corb_metrics as cm
from corb import contract
from corb.ingest import LIVE, LIVE_CONFIG, RE_LIVE, parse_set
from corb.paths import INFRA, RUNS, TOOLS, VAR, resolve

R2_MIN_EVENTS = 40
C0 = 1.0                     # MC-3 median terminal must keep the starting capital (edge_framework.md §7, R2)
DD_WARN = 0.8                # live DD >= 0.8 x the asset limit: the EA halves size itself (L3), reported here
V2_WATCH = dict(pred_e_max=-0.15)   # INF-P6 watch item: judged on forward months only


def _config():
    with open(LIVE_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def pull(src=None, inbox=None):
    """Copy new or changed CORB_*_live_*.csv from the synced VPS folder into the inbox. Never writes to the source."""
    cfg = _config()
    src = src or cfg.get("pull_from") or ""
    src = resolve(src) or src                     # %REPO%-style or a plain absolute path (e.g. a OneDrive folder)
    inbox = inbox or resolve(cfg["inbox"]) or cfg["inbox"]
    if not src or not os.path.isdir(src):
        return dict(source=src or None, copied=[], note="pull_from not set or not reachable (infra/live.json)")
    os.makedirs(inbox, exist_ok=True)
    copied = []
    for p in sorted(glob.glob(os.path.join(src, "CORB_*_live_*.csv"))):
        if not RE_LIVE.match(os.path.basename(p)):
            continue
        dst = os.path.join(inbox, os.path.basename(p))
        if not os.path.exists(dst) or _sha(dst) != _sha(p):
            shutil.copyfile(p, dst)
            copied.append(os.path.basename(p))
    return dict(source=src, inbox=inbox, copied=copied)


# ---------------------------------------------------------------- forward events
def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _num(x):
    return float(x) if x not in (None, "") else None


def runs_by_deployment(live_root=LIVE):
    out = {}
    for d in sorted(glob.glob(os.path.join(live_root, "*_live"))):
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            out.setdefault(str(json.load(f)["magic_base"]), []).append(d)
    return out


def forward_events(dirs, point):
    events, decisions = [], []
    for d in dirs:
        ev, dec = contract.ledger_as_journal(_read(os.path.join(d, "ledger_decisions.csv")),
                                             _read(os.path.join(d, "ledger_events.csv")), point)
        events += ev
        decisions += [r for r in _read(os.path.join(d, "ledger_decisions.csv"))]
    for e in events:
        for k in ("pnl_R", "c_spread_R", "c_slip_R", "slip_entry_R", "hold_min", "pnl_ccy_est"):
            e[k] = _num(e.get(k))
        e["atr_pct"] = _num(e.get("atr_pct")) or 0.0
    events.sort(key=lambda e: e["entry_time"])
    return events, decisions


def _meta(dep, base, inputs, events, decisions):
    return dict(run_id=f"forward_{dep['asset']}_{base}", symbol=dep["symbol"], version=dep["ea_version"],
                window=[events[0]["day"], events[-1]["day"]] if events else [None, None], deposit=float(dep["deposit"]),
                inputs=inputs, counters={}, sides_lot_min=sum((d.get("skip_buy") == "lot_min") +
                                                              (d.get("skip_sell") == "lot_min") for d in decisions),
                sides_armed=sum(int(d.get("arm_buy") or 0) + int(d.get("arm_sell") or 0) for d in decisions))


def calendar_leaks(events):
    """Positions still open on a later day than their entry (failed time exit / overnight hold)."""
    return [e["event_id"] for e in events if e["exit_time"][:10] > e["entry_time"][:10]]


def month_end_states(rs_base, forward, e_base, leak):
    """Lifecycle state (W40 / W80 on baseline + forward events) at each forward month end."""
    out, rs = [], list(rs_base)
    by_month = {}
    for e in forward:
        by_month.setdefault(e["day"][:7], []).append(e["pnl_R"])
    for m in sorted(by_month):
        rs += by_month[m]
        out.append((m, cm.lifecycle(rs, e_base, leak)["state"]))
    return out


def live_dd_pct(events, deposit):
    eq = pk = float(deposit)
    dd = 0.0
    for e in events:
        eq += e["pnl_ccy_est"] or 0.0
        pk = max(pk, eq)
        dd = max(dd, 1 - eq / pk)
    return 100 * dd


def deployment_report(base, dep, dirs, sec, f_op):
    from corb_bench import load_run, score
    inputs = parse_set(resolve(dep["preset"]) or dep["preset"])
    events, decisions = forward_events(dirs, float(dep["point"]))
    _, base_events = load_run(os.path.join(RUNS, sec["run_id"]))
    out = dict(asset=dep["asset"], magic_base=base, months=len(dirs), events=len(events),
               armed_days=sum(d.get("decision") == "ARMED" for d in decisions), baseline_run=sec["run_id"],
               baseline=dict(E=sec["E"], EF=sec["EF"], E_N=sec["E_N"], AL=sec["AL"]))
    leaks = calendar_leaks(events)
    dd_limit = _num(inputs.get("InpAosDdLimitPct")) or 0.0
    dd = live_dd_pct(events, dep["deposit"])
    out.update(calendar_leaks=leaks, live_dd_pct=dd, dd_limit_pct=dd_limit)
    stops = []
    if leaks:
        stops.append(f"CALENDAR_LEAK on {len(leaks)} event(s): investigate before continuing")
    if dd_limit and dd >= DD_WARN * dd_limit:
        stops.append(f"live DD {dd:.1f} % >= 0.8 x the {dd_limit:.0f} % limit (the EA halves size)")
    if len(events) < 2:
        out.update(forward=None, r2=dict(eligible=False, note="fewer than 2 forward events"), stop_rules=stops)
        return out
    meta = _meta(dep, base, inputs, events, decisions)
    fwd = score(meta, events, f_op, mc_iters=1000)
    comb = score(dict(meta, run_id=meta["run_id"] + "_combined"), base_events + events, f_op, mc_iters=2000)
    states = month_end_states([e["pnl_R"] for e in base_events], events, sec["E"], fwd["Leak"])
    if len(states) >= 2 and all(s == "Below frontier" for _, s in states[-2:]):
        stops.append("Below frontier two month-ends in a row: pause this asset and investigate")
    base_cost = sum(e["c_spread_R"] for e in base_events) / len(base_events)
    base_slip = np.mean([e["slip_entry_R"] for e in base_events if e["slip_entry_R"] is not None])
    fwd_slip = np.mean([e["slip_entry_R"] for e in events if e["slip_entry_R"] is not None])
    checks = dict(events_ge_40=len(events) >= R2_MIN_EVENTS, forward_E_pos=fwd["E"] > 0, forward_EF_pos=fwd["EF"] > 0,
                  combined_EF_gt_M=comb["EF"] > comb["M"], mc3_median_ge_C0=comb["mc3"]["med_term"] >= C0,
                  no_calendar_leak=not leaks)
    out.update(
        forward={k: fwd[k] for k in ("n", "WR", "R", "E", "E_N", "AL", "EF", "M", "zone", "Leak", "worst", "maxdd_R")},
        combined=dict(n=comb["n"], EF=comb["EF"], M=comb["M"], mc3_median=comb["mc3"]["med_term"]),
        costs=dict(c_spread_R=[base_cost, fwd["c_spread"]], slip_entry_R=[float(base_slip), float(fwd_slip)]),
        month_end_states=states, r2=dict(checks, eligible=all(checks.values())), stop_rules=stops)
    return out


def report(live_root=LIVE):
    cfg = _config()
    with open(os.path.join(INFRA, "baseline_lock.json"), encoding="utf-8") as f:
        sec = json.load(f)["secondary"]["assets"]
    with open(os.path.join(TOOLS, "aos_assets.json"), encoding="utf-8") as f:
        f_op = {k: v["f_op"] for k, v in json.load(f)["assets"].items()}
    runs = runs_by_deployment(live_root)
    rows = []
    for base, dep in cfg["deployments"].items():
        rows.append(deployment_report(base, dep, runs.get(base, []), sec[dep["asset"]], f_op[dep["asset"]]))
    return rows


# ---------------------------------------------------------------- forward L2 shadow
def forward_rows(live_root=LIVE):
    """Forward armed days whose engine shadow filled, in the tape's format (aos_tape.build + aos_gate_wf.load)."""
    import aos_gate_wf as gw
    cfg = _config()
    rows = []
    for base, dirs in runs_by_deployment(live_root).items():
        dep = cfg["deployments"].get(base)
        if not dep:
            continue
        for d in dirs:
            shadow = {r["event_id"]: r for r in _read(os.path.join(d, "ledger_shadow.csv"))}
            for r in _read(os.path.join(d, "ledger_decisions.csv")):
                s = shadow.get(r["event_id"], {})
                if r["decision"] == "ARMED" and s.get("status") == "FILLED":
                    rows.append(dict(r, asset=dep["asset"], role="asset", shadow_status="FILLED", shadow_R=s["shadow_R"]))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["y"] = df["shadow_R"].astype(float)
    df["month"] = df["local_day"].str[:7].str.replace(".", "-", regex=False)
    for c in ("spread_live_pt", "spread_avg_pt", "ev_next_min"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["spread_ratio"] = df["spread_live_pt"] / df["spread_avg_pt"].replace(0, np.nan)
    df["ev_next_min"] = df["ev_next_min"].where(df["ev_next_min"] >= 0, 1440)
    for c in gw.NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    return df.sort_values(["local_day", "event_id"]).reset_index(drop=True)


def _models():
    from corb import db
    out = {}
    for ln in db.psql("SELECT model_semver, family, dataset_id, artefact_path, created_at FROM train.model_version "
                      "WHERE family IN ('cell_rule', 'ridge_logit', 'gbt') ORDER BY created_at;").splitlines():
        semver, fam, ds, art, _ = ln.split("\t")
        out[(fam, ds)] = (semver, os.path.join(VAR, art))     # latest per family and dataset
    return out


def shadow(live_root=LIVE):
    import aos_gate_wf as gw
    from corb import evaluate as ev
    fwd = forward_rows(live_root)
    if fwd.empty:
        return dict(rows=0, models=[], note="no forward armed days with a filled engine shadow yet")
    pol = ev.policy()
    mr = pol["model_rule"]
    tape_id = ev.dataset_info(ev.load())["dataset_id"]
    out = []
    for (fam, ds), (semver, art) in sorted(_models().items()):
        train = ev.datasets(with_replica=ds != tape_id)["base" if ds == tape_id else "ext"]
        train = train[train.role == "asset"]
        assets = sorted(train.asset.unique())
        with open(art, "rb") as f:
            blob = pickle.load(f)
        sd = fwd.assign(verdict="fire", reason_code="ALLOW_DEFAULT", severity=0.0, v2_skip=False)
        if fam == "cell_rule":
            cuts, neg = blob
            for i, row in enumerate(sd.itertuples()):
                hits = [neg[(row.asset, d, v)][0] for d, v in ev._cells_of(row, cuts).items() if (row.asset, d, v) in neg]
                if hits:
                    sd.loc[sd.index[i], ["verdict", "reason_code", "severity"]] = ["skip", "SKIP_CELL_BM_NEG", -min(hits)]
        else:
            reg, clf, mu, sdv, cols = blob
            _, xte = gw.design(train, fwd, assets)
            x = (xte.reindex(columns=cols, fill_value=0.0) - mu) / sdv
            pe, pl = reg.predict(x), clf.predict_proba(x)[:, 1]
            skip = (pe <= mr["pred_e_max"]) & (pl >= mr["p_loss_min"])
            sd.loc[skip, ["verdict", "reason_code"]] = ["skip", "SKIP_MODEL_LOSER"]
            sd.loc[(~skip) & (pe > mr["unsure_band"][0]) & (pe <= mr["unsure_band"][1]), "reason_code"] = "ALLOW_UNSURE"
            sd["severity"] = -pe
            sd["v2_skip"] = (pe <= V2_WATCH["pred_e_max"]) & (pl >= mr["p_loss_min"])
        sd = ev.apply_budget(sd, pol)
        held, v2 = sd[sd.verdict == "skip"], sd[sd.v2_skip]
        out.append(dict(model_semver=semver, family=fam, dataset_id=ds, forward_days=len(sd), skips=len(held),
                        withheld_mean=float(held.y.mean()) if len(held) else None,
                        kept_E=float(sd[sd.verdict == "fire"].y.mean()), all_E=float(sd.y.mean()),
                        v2_watch_skips=int(len(v2)), v2_withheld_mean=float(v2.y.mean()) if len(v2) else None,
                        by_month={m: dict(skips=int((g.verdict == "skip").sum()),
                                          withheld_sum=float(g[g.verdict == "skip"].y.sum()))
                                  for m, g in sd.groupby("month")},
                        skipped=held[["event_id", "asset", "month", "reason_code", "y"]].to_dict("records")))
    return dict(rows=len(fwd), months=sorted(fwd.month.unique()), models=out,
                note="shadow only: positive withheld means = the model would have skipped winners")
