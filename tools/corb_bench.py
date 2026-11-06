"""CycleORB scoring engine: health vector, Stage 1 zone, lifecycle, gates, sizing (edge_framework.md §5-§8).

Usage:
  python corb_bench.py <run_dir> [--f 0.01]                     score one run folder (from corb_parse.py)
  python corb_bench.py --assets aos_assets.json --out FILE.json  score every asset in a spec file
"""
import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime

import corb_metrics as cm

DD_LIMIT = 0.25


def load_run(run_dir):
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with open(os.path.join(run_dir, "events.csv"), encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    for e in events:
        for k in ("pnl_R", "c_spread_R", "c_slip_R", "atr_pct", "risk_pct_est", "slip_entry_R", "hold_min"):
            e[k] = float(e[k]) if e.get(k) not in (None, "") else None
    return meta, events


def score(meta, events, f_op, mc_iters=5000, seed=20261105):
    rs = [e["pnl_R"] for e in events]
    c = cm.core(rs)
    n = c["n"]
    cs = sum(e["c_spread_R"] for e in events) / n
    cl = sum(e["c_slip_R"] for e in events) / n
    lk = cm.leak(cl, c["R"])
    ef = c["BM"] - lk
    m = cm.wilson_half(c["WR"], n)
    zone = "Robust" if ef > m else ("Fragile" if ef > 0 else "Negative")
    r_lo, r_hi = cm.bootstrap_r(rs, seed=seed)
    exits = defaultdict(list)
    for e in events:
        exits[e["exit_type"]].append(e["pnl_R"])
    d0, d1 = date.fromisoformat(events[0]["day"]), date.fromisoformat(events[-1]["day"])
    months = ((d1 - d0).days + 1) / 30.44
    per30 = n / months
    # regime / tag cells (CO-09)
    atrs = sorted(e["atr_pct"] for e in events)
    q1, q2 = atrs[len(atrs) // 3], atrs[2 * len(atrs) // 3]
    cells = defaultdict(list)
    for e in events:
        band = "narrow" if e["atr_pct"] < q1 else ("mid" if e["atr_pct"] < q2 else "wide")
        cells["range_atr_" + band].append(e["pnl_R"])
        cells["side_" + e["side"]].append(e["pnl_R"])
    cell_out = {}
    for k, v in cells.items():
        cc = cm.core(v)
        cell_out[k] = dict(n=len(v), BM=cc["BM"], E=cc["E"], sumR=sum(v), qualifying=len(v) >= 15 and cc["BM"] is not None)
    qual = [v["BM"] for v in cell_out.values() if v["qualifying"]]
    life = cm.lifecycle(rs, c["E"], lk)
    stress = cm.mc3_stress(c["WR"], m, c["AL"], cs + cl)
    mc2 = cm.monte_carlo(rs, f_op, iters=mc_iters, seed=seed)
    mc3 = cm.monte_carlo(rs, f_op, iters=mc_iters, seed=seed, stress=stress)
    k_pess = max(0.0, cm.kelly_binary(c["WR"] - m, c["R"]))
    f_dd = cm.f_at_dd(rs, DD_LIMIT, seed=seed)
    exp_streak = cm.expected_streak(n, c["WR"])
    lot_min_share = meta["sides_lot_min"] / meta["sides_armed"] if meta.get("sides_armed") else 0.0
    return dict(
        run_id=meta["run_id"], symbol=meta["symbol"], version=meta["version"], window=meta["window"],
        deposit=meta["deposit"], f_op=f_op, n=n, months=round(months, 1), events_per_30d=per30,
        events_per_90d=per30 * 90 / 30.44,
        WR=c["WR"], AW=c["AW"], AL=c["AL"], R=c["R"], R_ci=[r_lo, r_hi], RR=float(meta["inputs"].get("InpTargetR", "nan")),
        BWR=c["BWR"], BM=c["BM"], FMI=c["FMI"], E=c["E"], E_N=c["E_N"], PF=c["PF"], sd=c["sd"],
        c_spread=cs, c_slip=cl, c_R=cs + cl, Leak=lk, EF=ef, M=m, zone=zone,
        p_binom=cm.binom_sf(c["wins"], c["wins"] + c["losses"], c["BWR"] + lk),
        g1_r_low_ok=cm.bwr(r_lo) < c["WR"] - lk,
        exits={k: dict(share=len(v) / n, mean=sum(v) / len(v)) for k, v in exits.items()},
        worst=min(rs), tail_share=-min(rs) / sum(x for x in rs if x > 0), loss_skew=cm.loss_skew(rs),
        losses_below_1_2R=sum(1 for x in rs if x < -1.2),
        streak=cm.max_loss_streak(rs), streak_expected=exp_streak,
        dependence_threshold=math.ceil(1.5 * exp_streak),
        maxdd_R=cm.max_drawdown_r(rs), lifecycle=life, cells=cell_out, BM_worst=min(qual) if qual else None,
        folds_E=cm.folds(rs), kelly_binary=cm.kelly_binary(c["WR"], c["R"]), kelly_pess=k_pess,
        f_dd25=f_dd, f_max=min(0.5 * k_pess, f_dd), mc2=mc2, mc3=mc3,
        EF_cost_x1_5=c["BM"] - (cl + 0.5 * (cs + cl)) / (c["R"] + 1),
        EF_cost_x2_0=c["BM"] - (cl + (cs + cl)) / (c["R"] + 1),
        L6_lot_min_share=lot_min_share, close_fail=meta["counters"].get("close_fail", 0),
        skip_date=meta["counters"].get("skip_skip_date", 0),
        triggers=dict(  # edge_framework.md §6.2
            wr_floor=c["BWR"] + lk, compressing_line=c["E"] - 0.10, payoff_break=r_lo,
            sl_share_ceiling=exits["SL"] and len(exits["SL"]) / n + 0.15, cost_drift=1.5 * cs,
            frequency_stall_90d=0.5 * per30 * 90 / 30.44),
    )


def fmt(s):
    p = lambda x: f"{100 * x:+.1f}"
    return (f"{s['run_id']}\n  n={s['n']} WR={100 * s['WR']:.1f}% R={s['R']:.2f} [{s['R_ci'][0]:.2f},{s['R_ci'][1]:.2f}] "
            f"E={s['E']:+.3f}R E_N={s['E_N']:+.3f} PF={s['PF']:.2f} BM={p(s['BM'])}pp Leak={100 * s['Leak']:.1f}pp "
            f"EF={p(s['EF'])}pp M={100 * s['M']:.1f}pp {s['zone']} | state={s['lifecycle']['state']} "
            f"BM_worst={'-' if s['BM_worst'] is None else p(s['BM_worst'])} folds={[round(x, 2) for x in s['folds_E']]}\n"
            f"  MC-2 P95DD={100 * s['mc2']['p95dd']:.1f}% med={s['mc2']['med_term']:.2f} | MC-3 ruin={100 * s['mc3']['ruin']:.1f}% "
            f"med={s['mc3']['med_term']:.2f} | f_op={100 * s['f_op']:.2f}% f_max={100 * s['f_max']:.2f}% "
            f"L6={100 * s['L6_lot_min_share']:.0f}% close_fail={s['close_fail']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--f", type=float, default=0.01, help="operating risk fraction for Stage 3 (single-run mode)")
    ap.add_argument("--assets", help="asset spec JSON (see aos_assets.json)")
    ap.add_argument("--out", help="write results JSON here")
    ap.add_argument("--freeze", action="store_true", help="wrap results with provenance (AOS-P0-T01 baseline file)")
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    results = {}
    hashes = {}
    if a.assets:
        with open(a.assets, encoding="utf-8") as f:
            spec = json.load(f)
        runs_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(a.assets)), spec["runs_root"]))
        for key, asset in spec["assets"].items():
            run_dir = os.path.join(runs_root, asset["run_id"])
            meta, events = load_run(run_dir)
            results[key] = dict(score(meta, events, asset["f_op"]), preset=asset["preset"], role=asset.get("role", "asset"))
            with open(os.path.join(run_dir, "events.csv"), "rb") as f:
                hashes[asset["run_id"]] = hashlib.sha256(f.read()).hexdigest()
            print(f"[{key}] " + fmt(results[key]))
    elif a.run_dir:
        meta, events = load_run(a.run_dir)
        results[meta["run_id"]] = score(meta, events, a.f)
        print(fmt(results[meta["run_id"]]))
    else:
        ap.error("give a run_dir or --assets")
    if a.out:
        payload = results
        if a.freeze:
            payload = dict(provenance=dict(
                task="AOS-P0-T01", frozen_at=datetime.now().isoformat(timespec="seconds"),
                framework="unified_edge_framework.md v1.0 + edge_framework.md v1.0 (CycleORB overrides)",
                engine="CycleORB v1.09, production presets, YWO-Trade real ticks",
                mc="block 10, 5000 paths, seed 20261105", events_sha256=hashes), assets=results)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        print("wrote", os.path.relpath(a.out, here))


if __name__ == "__main__":
    main()
