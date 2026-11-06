"""AOS-P3-T07: month-end lifecycle replay and edge_framework.md §6.2 trigger report.

For every month end, uses only events closed by then: W20 / W40 / W80 EF and E, ΔD, lifecycle state and the size
multiplier the EA's Health.mqh applies (Near frontier 0.5x, Below frontier 0x). Baseline E / Leak / triggers come
from tools/aos_baseline.json. With --ea, the EA's own state (ledger_decisions.csv column health_state) is shown next to it.

Usage:
  python aos_health.py --assets aos_assets.json [--tag P3T05] [--ea]
  python aos_health.py --run ../tester/aos/runs/<run_id> --asset DE40
"""
import argparse
import csv
import json
import math
import os
from collections import OrderedDict

import corb_metrics as cm
from corb_bench import load_run

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = {"Near frontier": 0.5, "Below frontier": 0.0}


def month_ends(events):
    months = OrderedDict()
    for e in events:
        months[e["exit_time"][:7]] = True
    return list(months)


def replay(events, base):
    """One row per month: state at that month end (applies to the next month's entries)."""
    rows = []
    for m in month_ends(events):
        closed = [e for e in events if e["exit_time"][:7] <= m]
        rs = [e["pnl_R"] for e in closed]
        life = cm.lifecycle(rs, base["E"], base["Leak"])
        w = life["windows"]
        last40 = closed[-40:]
        n40 = len(last40)
        sl_share = sum(1 for e in last40 if e["exit_type"] == "SL") / n40 if n40 else 0.0
        t_exits = [e["pnl_R"] for e in last40 if e["exit_type"] == "TIME"]
        c_spread = sum(e["c_spread_R"] for e in last40) / n40 if n40 else 0.0
        c40 = cm.core([e["pnl_R"] for e in last40]) if n40 >= 10 else None
        tr = base["triggers"]
        flags = []
        if c40 and c40["WR"] < tr["wr_floor"]:
            flags.append("WR<floor")
        if c40 and c40["R"] is not None and c40["R"] < tr["payoff_break"]:
            flags.append("payoff_break")
        if tr.get("sl_share_ceiling") and sl_share > tr["sl_share_ceiling"]:
            flags.append("SL_share")
        if len(t_exits) >= 10 and sum(t_exits) / len(t_exits) <= 0:
            flags.append("time_exit_decay")
        if c_spread > tr["cost_drift"]:
            flags.append("cost_drift")
        if sum(1 for e in last40 if e["pnl_R"] < -1.2) > 2:
            flags.append("tail")
        if cm.max_loss_streak(rs[-40:]) > base["dependence_threshold"]:
            flags.append("DEPENDENCE")
        rows.append(dict(month=m, n=len(rs), state=life["state"], size=SIZE.get(life["state"], 1.0),
                         EF20=w.get(20, {}).get("EF"), EF40=w.get(40, {}).get("EF"), EF80=w.get(80, {}).get("EF"),
                         E40=w.get(40, {}).get("E"), dD=life["dD"], flags=flags))
    return rows


def ea_states(run_dir):
    path = os.path.join(run_dir, "ledger_decisions.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r.get("health_state"):
                out[r["local_day"][:7].replace(".", "-")] = r["health_state"]
    return out


def fmt(x, pp=True):
    if x is None:
        return "   -  "
    return f"{100 * x:+6.1f}" if pp else f"{x:+6.3f}"


def next_month(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y + (mo == 12)}-{1 if mo == 12 else mo + 1:02d}"


def report(key, events, base, ea=None):
    print(f"\n[{key}] baseline E {base['E']:+.3f}R  Leak {100 * base['Leak']:.1f}pp  compressing line "
          f"{base['E'] - 0.10:+.3f}R")
    print("  month    n  EF_W20 EF_W40 EF_W80  E_W40   dD(pp)  state            size  EA next month    flags")
    for r in replay(events, base):
        # the state evaluated at this month end governs the next month's entries (EA ledger health_state)
        nxt = ea.get(next_month(r["month"]), "") if ea else ""
        print(f"  {r['month']} {r['n']:4} {fmt(r['EF20'])} {fmt(r['EF40'])} {fmt(r['EF80'])} {fmt(r['E40'], False)} "
              f"{fmt(r['dD'])}  {r['state']:<16} {r['size']:.1f}  {nxt:<16} {' '.join(r['flags'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", default=os.path.join(HERE, "aos_assets.json"))
    ap.add_argument("--baseline", default=os.path.join(HERE, "aos_baseline.json"))
    ap.add_argument("--tag", help="replay the tagged runs instead of the baselines")
    ap.add_argument("--ea", action="store_true", help="show the EA's own health_state from the ledger")
    ap.add_argument("--run")
    ap.add_argument("--asset")
    a = ap.parse_args()
    with open(a.baseline, encoding="utf-8") as f:
        baseline = json.load(f)["assets"]
    if a.run:
        report(a.asset, load_run(a.run)[1], baseline[a.asset], ea_states(a.run) if a.ea else None)
        return
    from aos_tape import tagged_dir, _spec
    spec, root = _spec(a.assets)
    for key, asset in spec["assets"].items():
        if asset.get("role") == "control":
            continue
        run_dir = os.path.join(root, asset["run_id"])
        if a.tag:
            run_dir = tagged_dir(root, asset["run_id"], a.tag)
        if not os.path.isdir(run_dir):
            print(f"[{key}] missing {run_dir}")
            continue
        report(key, load_run(run_dir)[1], baseline[key], ea_states(run_dir) if a.ea else None)


if __name__ == "__main__":
    main()
